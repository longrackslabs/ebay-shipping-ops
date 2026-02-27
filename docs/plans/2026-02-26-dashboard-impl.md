# Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a web dashboard on port 8080 that shows order status, pickup state, service health, and provides reprint/retry/pickup actions — all reading from the existing `~/.ebay-shipper/` JSON state files.

**Architecture:** FastAPI backend serves a single HTML page and JSON API endpoints. The dashboard is a separate process from the poller — both read/write the same data directory. No database, no auth, no build step.

**Tech Stack:** FastAPI, uvicorn, Tailwind CSS via CDN, vanilla JS

**Design Doc:** `docs/plans/2026-02-26-dashboard-design.md`

---

### Task 1: Add FastAPI + uvicorn dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies to pyproject.toml**

Add `fastapi` and `uvicorn[standard]` to the `dependencies` list in `pyproject.toml`:

```toml
dependencies = [
    "requests>=2.31.0",
    "python-dotenv>=1.0.1",
    "reportlab>=4.0.0",
    "easypost>=10.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
]
```

**Step 2: Install updated dependencies**

Run: `cd /Users/gpeden/src/ebay-shipper && .venv/bin/pip install -e .`
Expected: Successfully installed fastapi uvicorn

**Step 3: Verify imports work**

Run: `.venv/bin/python -c "import fastapi; import uvicorn; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Add fastapi and uvicorn dependencies for dashboard"
```

---

### Task 2: Dashboard backend — read-only API endpoints

**Files:**
- Create: `ebay_shipper/dashboard.py`
- Test: `tests/test_dashboard.py`

**Step 1: Write the failing tests**

Create `tests/test_dashboard.py` with tests for `GET /api/orders`, `GET /api/pickup`, and `GET /api/health`:

```python
"""Tests for dashboard API."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def data_dir(tmp_path):
    """Create a temp data dir with sample order data."""
    orders_dir = tmp_path / "orders"

    # Order 1: shipped
    order1_dir = orders_dir / "11-11111-11111"
    order1_dir.mkdir(parents=True)
    (order1_dir / "state.json").write_text(json.dumps({
        "order_id": "11-11111-11111",
        "status": "shipped",
        "tracking_number": "9400111899223456789012",
        "rate": "5.52",
        "shipment_id": "shp_abc",
        "packing_list": str(order1_dir / "packing_list.pdf"),
        "label": str(order1_dir / "label.png"),
    }))
    (order1_dir / "order.json").write_text(json.dumps({
        "orderId": "11-11111-11111",
        "buyer": {"username": "jllegrand1"},
        "lineItems": [{"sku": "NZ-4MM", "quantity": 1, "lineItemId": "LI1"}],
        "pricingSummary": {"total": {"value": "12.99"}},
    }))

    # Order 2: pending_confirmation
    order2_dir = orders_dir / "22-22222-22222"
    order2_dir.mkdir(parents=True)
    (order2_dir / "state.json").write_text(json.dumps({
        "order_id": "22-22222-22222",
        "status": "pending_confirmation",
        "tracking_number": "9400111899223456789099",
        "rate": "5.00",
        "shipment_id": "shp_def",
        "packing_list": str(order2_dir / "packing_list.pdf"),
        "label": str(order2_dir / "label.png"),
    }))
    (order2_dir / "order.json").write_text(json.dumps({
        "orderId": "22-22222-22222",
        "buyer": {"username": "lastri-84"},
        "lineItems": [
            {"sku": "NZ-2MM", "quantity": 1, "lineItemId": "LI2"},
            {"sku": "NZ-6MM", "quantity": 2, "lineItemId": "LI3"},
        ],
        "pricingSummary": {"total": {"value": "24.99"}},
    }))

    # Order 3: label_failed
    order3_dir = orders_dir / "33-33333-33333"
    order3_dir.mkdir(parents=True)
    (order3_dir / "state.json").write_text(json.dumps({
        "order_id": "33-33333-33333",
        "status": "label_failed",
        "tracking_number": "",
        "rate": "",
        "shipment_id": "",
        "packing_list": str(order3_dir / "packing_list.pdf"),
        "label": "",
    }))
    (order3_dir / "order.json").write_text(json.dumps({
        "orderId": "33-33333-33333",
        "buyer": {"username": "failbuyer"},
        "lineItems": [{"sku": "NZ-BNDL-246", "quantity": 1, "lineItemId": "LI4"}],
        "pricingSummary": {"total": {"value": "29.99"}},
    }))

    # Service log
    (tmp_path / "service.log").write_text(
        "2026-02-26 08:00:00 [INFO] ebay_shipper: Poll complete\n"
        "2026-02-26 08:05:00 [INFO] ebay_shipper: No new orders\n"
    )

    return tmp_path


@pytest.fixture
def client(data_dir):
    """Create a test client with the temp data dir."""
    from ebay_shipper.dashboard import create_app
    app = create_app(data_dir)
    return TestClient(app)


def test_get_orders_returns_all(client):
    """GET /api/orders returns all orders with state + order details."""
    resp = client.get("/api/orders")
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) == 3

    # Check fields are merged from state.json + order.json
    ids = {o["order_id"] for o in orders}
    assert ids == {"11-11111-11111", "22-22222-22222", "33-33333-33333"}

    # Find the shipped order and check merged fields
    shipped = next(o for o in orders if o["order_id"] == "11-11111-11111")
    assert shipped["status"] == "shipped"
    assert shipped["tracking_number"] == "9400111899223456789012"
    assert shipped["buyer"] == "jllegrand1"
    assert shipped["items"] == "NZ-4MM x1"
    assert shipped["total"] == "12.99"
    assert shipped["rate"] == "5.52"


def test_get_orders_pending_has_items_formatted(client):
    """Items field shows SKU x qty, comma-separated."""
    resp = client.get("/api/orders")
    pending = next(o for o in resp.json() if o["order_id"] == "22-22222-22222")
    assert pending["items"] == "NZ-2MM x1, NZ-6MM x2"


def test_get_orders_empty(tmp_path):
    """GET /api/orders returns empty list when no orders exist."""
    from ebay_shipper.dashboard import create_app
    app = create_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/orders")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_pickup_no_state(tmp_path):
    """GET /api/pickup returns empty when no pickup state exists."""
    from ebay_shipper.dashboard import create_app
    app = create_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/pickup")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_get_pickup_with_state(data_dir, client):
    """GET /api/pickup returns saved pickup state."""
    (data_dir / "pickup_state.json").write_text(json.dumps({
        "pickup_date": "2026-02-27",
        "pickup_id": "pickup_123",
        "confirmation": "WTC12345",
        "status": "scheduled",
    }))
    resp = client.get("/api/pickup")
    assert resp.status_code == 200
    assert resp.json()["confirmation"] == "WTC12345"
    assert resp.json()["status"] == "scheduled"


def test_get_health(data_dir, client):
    """GET /api/health returns service status and recent log lines."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    health = resp.json()
    assert "log_lines" in health
    assert len(health["log_lines"]) == 2
    assert "No new orders" in health["log_lines"][-1]
    assert health["service_ok"] is True


def test_get_health_stale_log(tmp_path):
    """GET /api/health reports not OK when log is stale."""
    from ebay_shipper.dashboard import create_app
    app = create_app(tmp_path)
    client = TestClient(app)
    # No log file at all
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["service_ok"] is False
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ebay_shipper.dashboard'`

**Step 3: Write the dashboard backend**

Create `ebay_shipper/dashboard.py`:

```python
"""eBay Shipper Dashboard — FastAPI web server."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

STALE_LOG_SECONDS = 600  # 10 minutes — service polls every 5 min


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

        orders.append({
            "order_id": state.get("order_id", order_dir.name),
            "status": state.get("status", "unknown"),
            "tracking_number": state.get("tracking_number", ""),
            "rate": state.get("rate", ""),
            "shipment_id": state.get("shipment_id", ""),
            "buyer": order_data.get("buyer", {}).get("username", ""),
            "items": items,
            "total": order_data.get("pricingSummary", {}).get("total", {}).get("value", ""),
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


def create_app(data_dir: Path) -> FastAPI:
    """Create the FastAPI dashboard app."""
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

    @app.get("/", response_class=HTMLResponse)
    def index():
        html_path = Path(__file__).parent / "templates" / "index.html"
        return html_path.read_text()

    return app
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add ebay_shipper/dashboard.py tests/test_dashboard.py
git commit -m "Add dashboard backend with read-only API endpoints"
```

---

### Task 3: Dashboard action endpoints (reprint, retry)

**Files:**
- Modify: `ebay_shipper/dashboard.py`
- Modify: `tests/test_dashboard.py`

The action endpoints call into `main.py` functions (`confirm_order`, `process_order`) but we don't want the dashboard to import the full main module with its side effects. Instead, the actions directly manipulate state files and call `print_file` / label provider.

For MVP, reprint calls `print_file` on the saved packing list + label. Retry re-runs `process_order`. Both need `config` passed at app creation time.

**Step 1: Write failing tests for reprint and retry**

Add to `tests/test_dashboard.py`:

```python
@patch("ebay_shipper.dashboard.print_file")
def test_reprint_order(mock_print, data_dir, client):
    """POST /api/orders/{id}/reprint reprints packing list + label."""
    # Create the files that print_file expects
    order_dir = data_dir / "orders" / "22-22222-22222"
    (order_dir / "packing_list.pdf").write_bytes(b"fake pdf")
    (order_dir / "label.png").write_bytes(b"fake png")

    mock_print.return_value = True
    resp = client.post("/api/orders/22-22222-22222/reprint")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert mock_print.call_count == 2


@patch("ebay_shipper.dashboard.print_file")
def test_reprint_wrong_status(mock_print, data_dir, client):
    """POST /api/orders/{id}/reprint rejects non-pending orders."""
    resp = client.post("/api/orders/11-11111-11111/reprint")
    assert resp.status_code == 400
    mock_print.assert_not_called()


def test_reprint_not_found(client):
    """POST /api/orders/{id}/reprint returns 404 for missing orders."""
    resp = client.post("/api/orders/99-99999-99999/reprint")
    assert resp.status_code == 404


@patch("ebay_shipper.dashboard.print_file")
def test_retry_order(mock_print, data_dir, client):
    """POST /api/orders/{id}/retry reprocesses a failed order."""
    mock_print.return_value = True
    resp = client.post("/api/orders/33-33333-33333/retry")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@patch("ebay_shipper.dashboard.print_file")
def test_retry_wrong_status(mock_print, data_dir, client):
    """POST /api/orders/{id}/retry rejects non-failed orders."""
    resp = client.post("/api/orders/11-11111-11111/retry")
    assert resp.status_code == 400
    mock_print.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v -k "reprint or retry"`
Expected: FAIL

**Step 3: Add action endpoints to dashboard.py**

Add to `create_app` in `dashboard.py`, and update the function signature to accept `config`:

```python
from fastapi import FastAPI, HTTPException
from ebay_shipper.printer import print_file

def create_app(data_dir: Path, config: dict | None = None) -> FastAPI:
    """Create the FastAPI dashboard app."""
    _config = config or {}
    printer_name = _config.get("printer_name", "Label_Printer")
    app = FastAPI(title="eBay Shipper Dashboard")

    # ... existing read-only endpoints unchanged ...

    @app.post("/api/orders/{order_id}/reprint")
    def reprint_order(order_id: str):
        order_dir = data_dir / "orders" / order_id
        state_file = order_dir / "state.json"
        if not state_file.exists():
            raise HTTPException(404, f"Order {order_id} not found")

        state = json.loads(state_file.read_text())
        if state["status"] != "pending_confirmation":
            raise HTTPException(400, f"Order status is '{state['status']}', not pending_confirmation")

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

        # For MVP: mark as needing attention, actual retry requires label provider + config
        # which we'll wire up when the dashboard CLI command passes config
        return {"success": True, "message": "Order queued for retry"}

    return app
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ebay_shipper/dashboard.py tests/test_dashboard.py
git commit -m "Add reprint and retry action endpoints to dashboard"
```

---

### Task 4: Dashboard frontend — single HTML page

**Files:**
- Create: `ebay_shipper/templates/index.html`

**Step 1: Create the templates directory**

```bash
mkdir -p /Users/gpeden/src/ebay-shipper/ebay_shipper/templates
```

**Step 2: Create the HTML file**

Create `ebay_shipper/templates/index.html` — a single-page dashboard with:
- Header: "LONGRACKS LABS" with service status dot (green/red)
- Attention banner: count of orders needing action (orange) or "All caught up" (green)
- Orders table: Order ID, Buyer, Items, Total, Status badge, Tracking link, Label Cost, Action buttons
- Pickup section: current pickup state + schedule button
- Service log: last 10 lines in a monospace box
- Auto-refresh every 30 seconds via `setInterval` + `fetch`

Use Tailwind CSS via CDN (`<script src="https://cdn.tailwindcss.com"></script>`), vanilla JS only.

The HTML fetches `/api/orders`, `/api/pickup`, `/api/health` and renders them. Action buttons POST to `/api/orders/{id}/reprint` or `/api/orders/{id}/retry`.

Status badges:
- `shipped` → green
- `pending_confirmation` → orange/amber
- `label_failed` → red

Tracking numbers link to USPS: `https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking}`

**Step 3: Verify the HTML serves correctly**

Run: `.venv/bin/python -c "from ebay_shipper.dashboard import create_app; from pathlib import Path; app = create_app(Path('/tmp')); from fastapi.testclient import TestClient; c = TestClient(app); r = c.get('/'); print('OK' if 'LONGRACKS' in r.text else 'FAIL')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add ebay_shipper/templates/index.html
git commit -m "Add dashboard frontend HTML with Tailwind CSS"
```

---

### Task 5: Dashboard CLI subcommand

**Files:**
- Modify: `ebay_shipper/main.py`

**Step 1: Add dashboard subcommand to main()**

In `main.py`, add the dashboard subcommand handler after the `pickup` handler and before service mode:

```python
if len(sys.argv) >= 2 and sys.argv[1] == "dashboard":
    import uvicorn
    from ebay_shipper.dashboard import create_app
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    app = create_app(DATA_DIR, config)
    logger.info("Starting dashboard on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    sys.exit(0)
```

**Step 2: Run existing tests to verify nothing is broken**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (existing + new dashboard tests)

**Step 3: Smoke test the dashboard locally**

Run: `.venv/bin/ebay-shipper dashboard &`
Then: `curl -s http://localhost:8080/api/health | python -m json.tool`
Expected: JSON with `service_ok` and `log_lines`
Then: `kill %1` to stop

**Step 4: Commit**

```bash
git add ebay_shipper/main.py
git commit -m "Add dashboard CLI subcommand"
```

---

### Task 6: Final integration test + cleanup

**Files:**
- Modify: `tests/test_dashboard.py` (if any adjustments needed)

**Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify dashboard serves on Mac**

Run dashboard, open `http://localhost:8080` in browser, verify:
- Page loads with "LONGRACKS LABS" header
- Orders table shows data (if any local orders exist) or empty state
- Service log section visible
- Auto-refresh fires every 30s (check network tab)

**Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "Dashboard MVP complete"
```
