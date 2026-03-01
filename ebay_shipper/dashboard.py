"""eBay Shipper Dashboard — FastAPI web server."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ebay_shipper.label_provider import EasyPostProvider, ShipFromAddress, next_pickup_date
from ebay_shipper.printer import print_file

logger = logging.getLogger(__name__)

STALE_LOG_SECONDS = 600  # 10 minutes — service polls every 5 min

# Single source of truth for all order states.
# Each state defines: display label, badge style, next state in flow,
# advance button label, available actions, and whether it needs attention.
STATES = {
    "pending_confirmation": {
        "label": "Printed", "badge": "pending",
        "next": "packed", "advance_label": "Pack",
        "actions": ["reprint", "advance", "cancel"],
        "needs_attention": True, "attention_label": "to pack",
    },
    "packed": {
        "label": "Packed", "badge": "pending",
        "next": "pickup_scheduled", "advance_label": "Schedule",
        "actions": ["reprint", "advance", "cancel"],
        "needs_attention": True, "attention_label": "to schedule",
    },
    "pickup_scheduled": {
        "label": "Scheduled", "badge": "shipped",
        "next": None, "actions": ["reprint", "cancel"],
        "needs_attention": False,
    },
    "in_transit": {
        "label": "In Transit", "badge": "shipped",
        "next": None, "actions": [],
        "needs_attention": False,
    },
    "out_for_delivery": {
        "label": "Out for Delivery", "badge": "shipped",
        "next": None, "actions": [],
        "needs_attention": False,
    },
    "delivered": {
        "label": "Delivered", "badge": "shipped",
        "next": None, "actions": [],
        "needs_attention": False,
    },
    "cancelled": {
        "label": "Cancelled", "badge": "terminal",
        "next": None, "actions": [],
        "needs_attention": False,
    },
    "lost": {
        "label": "Lost", "badge": "failed",
        "next": None, "actions": [],
        "needs_attention": False,
    },
    "return_to_sender": {
        "label": "Returned", "badge": "failed",
        "next": None, "actions": [],
        "needs_attention": False,
    },
    "label_failed": {
        "label": "Failed", "badge": "failed",
        "next": None, "actions": ["retry"],
        "needs_attention": True, "attention_label": "failed",
    },
}

# Derived from STATES — used by endpoints for validation
TERMINAL_STATES = {s for s, cfg in STATES.items() if cfg["next"] is None and not cfg.get("actions")}


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
            "tracking_detail": state.get("tracking_detail", ""),
            "pickup_confirmation": state.get("pickup_confirmation", ""),
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

    @app.get("/api/states")
    def get_states():
        return STATES

    @app.get("/api/orders")
    def get_orders():
        return _read_orders(data_dir)

    @app.get("/api/pickup")
    def get_pickup():
        return _read_pickup(data_dir)

    @app.get("/api/health")
    def get_health():
        return _read_health(data_dir)

    def _validate_action(order_id: str, action: str):
        """Load order state and validate that the action is allowed."""
        order_dir = data_dir / "orders" / order_id
        state_file = order_dir / "state.json"
        if not state_file.exists():
            raise HTTPException(404, f"Order {order_id} not found")

        state = json.loads(state_file.read_text())
        status = state["status"]
        state_cfg = STATES.get(status, {})

        if action not in state_cfg.get("actions", []):
            raise HTTPException(400, f"Action '{action}' not available for status '{status}'")

        return order_dir, state_file, state, state_cfg

    @app.post("/api/orders/{order_id}/reprint")
    def reprint_order(order_id: str):
        _, _, state, _ = _validate_action(order_id, "reprint")

        if not state.get("label"):
            raise HTTPException(400, f"Order {order_id} has no label to reprint")

        packing_ok = print_file(Path(state["packing_list"]), printer_name)
        label_ok = print_file(Path(state["label"]), printer_name)

        return {"success": packing_ok and label_ok}

    @app.post("/api/orders/{order_id}/retry")
    def retry_order(order_id: str):
        _validate_action(order_id, "retry")
        return {"success": True, "message": "Order queued for retry"}

    @app.post("/api/orders/{order_id}/cancel")
    def cancel_order(order_id: str):
        _, state_file, state, _ = _validate_action(order_id, "cancel")

        previous = state["status"]
        state["status"] = "cancelled"
        state_file.write_text(json.dumps(state, indent=2))
        logger.info("Order %s: %s → cancelled", order_id, previous)

        return {"success": True, "previous": previous, "status": "cancelled"}

    @app.post("/api/orders/{order_id}/advance")
    def advance_order(order_id: str):
        _, state_file, state, state_cfg = _validate_action(order_id, "advance")

        current = state["status"]
        next_status = state_cfg["next"]

        # When advancing to pickup_scheduled, actually schedule via EasyPost
        if next_status == "pickup_scheduled":
            api_key = _config.get("easypost_api_key", "")
            if not api_key:
                raise HTTPException(500, "No EASYPOST_API_KEY configured")

            shipment_id = state.get("shipment_id", "")
            if not shipment_id:
                raise HTTPException(400, "Order has no shipment_id — cannot schedule pickup")

            provider = EasyPostProvider(api_key)
            ship_from = ShipFromAddress(
                name=_config.get("from_name", ""),
                street=_config.get("from_street", ""),
                city=_config.get("from_city", ""),
                state=_config.get("from_state", ""),
                zip_code=_config.get("from_zip", ""),
                phone=_config.get("from_phone", ""),
                company=_config.get("from_company", ""),
            )

            confirmation = provider.schedule_pickup(
                shipment_id, ship_from, data_dir,
                instructions=_config.get("pickup_instructions", "Front porch"),
            )
            if not confirmation:
                raise HTTPException(500, "Failed to schedule USPS pickup")

            pickup_date = next_pickup_date()
            state["pickup_confirmation"] = f"Pickup {pickup_date} ({confirmation})"

        state["status"] = next_status
        state_file.write_text(json.dumps(state, indent=2))
        logger.info("Order %s: %s → %s", order_id, current, next_status)

        return {"success": True, "previous": current, "status": next_status}

    @app.get("/", response_class=HTMLResponse)
    def index():
        html_path = Path(__file__).parent / "templates" / "index.html"
        return html_path.read_text()

    return app
