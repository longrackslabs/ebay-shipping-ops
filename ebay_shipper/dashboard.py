"""eBay Shipper Dashboard — FastAPI web server."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ebay_shipper.printer import print_file

logger = logging.getLogger(__name__)

STALE_LOG_SECONDS = 600  # 10 minutes — service polls every 5 min

# Fulfillment flow: each state advances to the next
# Manual steps: printed → packed → pickup_scheduled → porched
# Auto steps (tracking poll): porched → in_transit → out_for_delivery → delivered
FLOW = [
    "pending_confirmation", "packed", "pickup_scheduled", "porched",
    "in_transit", "out_for_delivery", "delivered",
]

# Terminal states that can happen from any point — not part of the happy path
TERMINAL_STATES = {"delivered", "cancelled", "lost", "return_to_sender"}


def _read_orders(data_dir: Path) -> list[dict]:
    """Read all orders from data dir, merging state.json + order.json."""
    orders_dir = data_dir / "orders"
    if not orders_dir.exists():
        return []

    orders = []
    for order_dir in sorted(orders_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        state_file = order_dir / "state.json"
        order_file = order_dir / "order.json"
        if not state_file.exists():
            continue

        state = json.loads(state_file.read_text())
        order_data = json.loads(order_file.read_text()) if order_file.exists() else {}

        items = ", ".join(
            f"{i.get('sku', '?')} x{i.get('quantity', 1)}"
            for i in order_data.get("lineItems", [])
        )

        # Use directory mtime as the processed timestamp
        mtime = order_dir.stat().st_mtime
        processed_at = datetime.fromtimestamp(mtime, timezone.utc).isoformat()

        orders.append({
            "order_id": state.get("order_id", order_dir.name),
            "status": state.get("status", "unknown"),
            "tracking_number": state.get("tracking_number", ""),
            "rate": state.get("rate", ""),
            "shipment_id": state.get("shipment_id", ""),
            "buyer": order_data.get("buyer", {}).get("username", ""),
            "items": items,
            "total": order_data.get("pricingSummary", {}).get("total", {}).get("value", ""),
            "processed_at": processed_at,
        })

    return orders


def _read_pickup(data_dir: Path) -> dict:
    """Read pickup state from data dir."""
    path = data_dir / "pickup_state.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _read_health(data_dir: Path) -> dict:
    """Read service health from log file."""
    log_path = data_dir / "service.log"
    log_lines = []
    service_ok = False

    if log_path.exists():
        lines = log_path.read_text().strip().splitlines()
        log_lines = lines[-10:]  # last 10 lines

        # Check if log is recent (within STALE_LOG_SECONDS)
        mtime = log_path.stat().st_mtime
        age = datetime.now(timezone.utc).timestamp() - mtime
        service_ok = age < STALE_LOG_SECONDS

    return {
        "log_lines": log_lines,
        "service_ok": service_ok,
    }


def create_app(data_dir: Path, config: dict | None = None) -> FastAPI:
    """Create the FastAPI dashboard app."""
    _config = config or {}
    printer_name = _config.get("printer_name", "Label_Printer")
    app = FastAPI(title="eBay Shipper Dashboard")

    @app.get("/api/orders")
    def get_orders():
        return _read_orders(data_dir)

    @app.get("/api/pickup")
    def get_pickup():
        return _read_pickup(data_dir)

    @app.get("/api/health")
    def get_health():
        return _read_health(data_dir)

    @app.post("/api/orders/{order_id}/reprint")
    def reprint_order(order_id: str):
        order_dir = data_dir / "orders" / order_id
        state_file = order_dir / "state.json"
        if not state_file.exists():
            raise HTTPException(404, f"Order {order_id} not found")

        state = json.loads(state_file.read_text())
        if not state.get("label"):
            raise HTTPException(400, f"Order {order_id} has no label to reprint")

        packing_ok = print_file(Path(state["packing_list"]), printer_name)
        label_ok = print_file(Path(state["label"]), printer_name)

        return {"success": packing_ok and label_ok}

    @app.post("/api/orders/{order_id}/retry")
    def retry_order(order_id: str):
        order_dir = data_dir / "orders" / order_id
        state_file = order_dir / "state.json"
        if not state_file.exists():
            raise HTTPException(404, f"Order {order_id} not found")

        state = json.loads(state_file.read_text())
        if state["status"] != "label_failed":
            raise HTTPException(400, f"Order status is '{state['status']}', not label_failed")

        return {"success": True, "message": "Order queued for retry"}

    @app.post("/api/orders/{order_id}/cancel")
    def cancel_order(order_id: str):
        order_dir = data_dir / "orders" / order_id
        state_file = order_dir / "state.json"
        if not state_file.exists():
            raise HTTPException(404, f"Order {order_id} not found")

        state = json.loads(state_file.read_text())
        if state["status"] in TERMINAL_STATES:
            raise HTTPException(400, f"Order is already at terminal status '{state['status']}'")

        previous = state["status"]
        state["status"] = "cancelled"
        state_file.write_text(json.dumps(state, indent=2))
        logger.info("Order %s: %s → cancelled", order_id, previous)

        return {"success": True, "previous": previous, "status": "cancelled"}

    @app.post("/api/orders/{order_id}/advance")
    def advance_order(order_id: str):
        order_dir = data_dir / "orders" / order_id
        state_file = order_dir / "state.json"
        if not state_file.exists():
            raise HTTPException(404, f"Order {order_id} not found")

        state = json.loads(state_file.read_text())
        current = state["status"]

        if current not in FLOW:
            raise HTTPException(400, f"Order status '{current}' is not in the fulfillment flow")

        idx = FLOW.index(current)
        if idx >= len(FLOW) - 1:
            raise HTTPException(400, f"Order is already at final status '{current}'")

        next_status = FLOW[idx + 1]
        state["status"] = next_status
        state_file.write_text(json.dumps(state, indent=2))
        logger.info("Order %s: %s → %s", order_id, current, next_status)

        return {"success": True, "previous": current, "status": next_status}

    @app.get("/", response_class=HTMLResponse)
    def index():
        html_path = Path(__file__).parent / "templates" / "index.html"
        return html_path.read_text()

    return app
