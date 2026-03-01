"""Tests for dashboard API."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


TEST_CONFIG = {
    "easypost_api_key": "EZTK_test_key",
    "from_name": "George Peden",
    "from_street": "1994 NW 129th Pl",
    "from_city": "Portland",
    "from_state": "OR",
    "from_zip": "97229",
    "from_phone": "5033494247",
    "from_company": "Longracks Labs",
    "pickup_instructions": "Packages in bin on front porch",
    "printer_name": "Label_Printer",
}


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
    app = create_app(data_dir, TEST_CONFIG)
    return TestClient(app)


def test_get_orders_returns_all(client):
    """GET /api/orders returns all orders with state + order details."""
    resp = client.get("/api/orders")
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) == 3

    ids = {o["order_id"] for o in orders}
    assert ids == {"11-11111-11111", "22-22222-22222", "33-33333-33333"}

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
    c = TestClient(app)
    resp = c.get("/api/orders")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_pickup_no_state(tmp_path):
    """GET /api/pickup returns empty when no pickup state exists."""
    from ebay_shipper.dashboard import create_app
    app = create_app(tmp_path)
    c = TestClient(app)
    resp = c.get("/api/pickup")
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


def test_get_health_no_log(tmp_path):
    """GET /api/health reports not OK when no log exists."""
    from ebay_shipper.dashboard import create_app
    app = create_app(tmp_path)
    c = TestClient(app)
    resp = c.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["service_ok"] is False


@patch("ebay_shipper.dashboard.print_file")
def test_reprint_order(mock_print, data_dir, client):
    """POST /api/orders/{id}/reprint reprints packing list + label."""
    order_dir = data_dir / "orders" / "22-22222-22222"
    (order_dir / "packing_list.pdf").write_bytes(b"fake pdf")
    (order_dir / "label.png").write_bytes(b"fake png")

    mock_print.return_value = True
    resp = client.post("/api/orders/22-22222-22222/reprint")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert mock_print.call_count == 2


@patch("ebay_shipper.dashboard.print_file")
def test_reprint_no_label(mock_print, data_dir, client):
    """POST /api/orders/{id}/reprint rejects orders with no label."""
    resp = client.post("/api/orders/33-33333-33333/reprint")
    assert resp.status_code == 400
    mock_print.assert_not_called()


def test_reprint_not_found(client):
    """POST /api/orders/{id}/reprint returns 404 for missing orders."""
    resp = client.post("/api/orders/99-99999-99999/reprint")
    assert resp.status_code == 404


@patch("ebay_shipper.dashboard.print_file")
def test_retry_order(mock_print, data_dir, client):
    """POST /api/orders/{id}/retry accepts failed orders."""
    resp = client.post("/api/orders/33-33333-33333/retry")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@patch("ebay_shipper.dashboard.print_file")
def test_retry_wrong_status(mock_print, data_dir, client):
    """POST /api/orders/{id}/retry rejects non-failed orders."""
    resp = client.post("/api/orders/11-11111-11111/retry")
    assert resp.status_code == 400
    mock_print.assert_not_called()


@patch("ebay_shipper.dashboard.EasyPostProvider")
def test_advance_order_through_manual_flow(mock_provider_cls, data_dir, client):
    """POST /api/orders/{id}/advance walks through the manual fulfillment steps."""
    mock_provider = MagicMock()
    mock_provider.schedule_pickup.return_value = "EMC123456789"
    mock_provider_cls.return_value = mock_provider

    oid = "22-22222-22222"

    # pending_confirmation → packed
    resp = client.post(f"/api/orders/{oid}/advance")
    assert resp.status_code == 200
    assert resp.json()["status"] == "packed"

    # packed → pickup_scheduled (triggers real EasyPost pickup call)
    resp = client.post(f"/api/orders/{oid}/advance")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pickup_scheduled"
    mock_provider.schedule_pickup.assert_called_once()

    # Verify tracking_detail has pickup info
    state = json.loads((data_dir / "orders" / oid / "state.json").read_text())
    assert state["status"] == "pickup_scheduled"
    assert "EMC123456789" in state["tracking_detail"]

    # pickup_scheduled has no manual advance — tracking poll handles the rest
    resp = client.post(f"/api/orders/{oid}/advance")
    assert resp.status_code == 400


def test_advance_rejects_failed_orders(data_dir, client):
    """POST /api/orders/{id}/advance rejects label_failed orders (use retry instead)."""
    resp = client.post("/api/orders/33-33333-33333/advance")
    assert resp.status_code == 400


def test_cancel_order(data_dir, client):
    """POST /api/orders/{id}/cancel sets status to cancelled."""
    resp = client.post("/api/orders/22-22222-22222/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    state = json.loads((data_dir / "orders" / "22-22222-22222" / "state.json").read_text())
    assert state["status"] == "cancelled"


def test_get_states(client):
    """GET /api/states returns all state definitions."""
    resp = client.get("/api/states")
    assert resp.status_code == 200
    states = resp.json()
    assert "pending_confirmation" in states
    assert states["pending_confirmation"]["label"] == "Printed"
    assert "advance" in states["pending_confirmation"]["actions"]
    assert states["delivered"]["actions"] == []


def test_cancel_rejects_terminal(data_dir, client):
    """POST /api/orders/{id}/cancel rejects already-cancelled orders."""
    # First cancel the order
    oid = "22-22222-22222"
    client.post(f"/api/orders/{oid}/cancel")

    resp = client.post(f"/api/orders/{oid}/cancel")
    assert resp.status_code == 400


def test_check_tracking_maps_failure_to_lost(tmp_path):
    """check_tracking_updates maps EasyPost 'failure' to 'lost'."""
    from unittest.mock import MagicMock
    from ebay_shipper.main import check_tracking_updates

    orders_dir = tmp_path / "orders"
    order_dir = orders_dir / "66-66666-66666"
    order_dir.mkdir(parents=True)
    (order_dir / "state.json").write_text(json.dumps({
        "order_id": "66-66666-66666",
        "status": "in_transit",
        "tracking_number": "9400136208303461675547",
    }))

    provider = MagicMock()
    provider.check_tracking.return_value = {"status": "failure", "detail": "Package lost"}

    check_tracking_updates(orders_dir, provider)

    state = json.loads((order_dir / "state.json").read_text())
    assert state["status"] == "lost"
    assert state["tracking_detail"] == "Package lost"


def test_check_tracking_maps_return_to_sender(tmp_path):
    """check_tracking_updates maps EasyPost 'return_to_sender' correctly."""
    from unittest.mock import MagicMock
    from ebay_shipper.main import check_tracking_updates

    orders_dir = tmp_path / "orders"
    order_dir = orders_dir / "77-77777-77777"
    order_dir.mkdir(parents=True)
    (order_dir / "state.json").write_text(json.dumps({
        "order_id": "77-77777-77777",
        "status": "in_transit",
        "tracking_number": "9400136208303461675547",
    }))

    provider = MagicMock()
    provider.check_tracking.return_value = {"status": "return_to_sender", "detail": "Returned to sender"}

    check_tracking_updates(orders_dir, provider)

    state = json.loads((order_dir / "state.json").read_text())
    assert state["status"] == "return_to_sender"
    assert state["tracking_detail"] == "Returned to sender"


def test_check_tracking_updates_scheduled_to_in_transit(tmp_path):
    """check_tracking_updates auto-advances pickup_scheduled orders when USPS scans them."""
    from unittest.mock import MagicMock
    from ebay_shipper.main import check_tracking_updates

    orders_dir = tmp_path / "orders"
    order_dir = orders_dir / "44-44444-44444"
    order_dir.mkdir(parents=True)
    (order_dir / "state.json").write_text(json.dumps({
        "order_id": "44-44444-44444",
        "status": "pickup_scheduled",
        "tracking_number": "9400136208303461675547",
    }))

    provider = MagicMock()
    provider.check_tracking.return_value = {"status": "in_transit", "detail": "Accepted at USPS Origin Facility"}

    check_tracking_updates(orders_dir, provider)

    state = json.loads((order_dir / "state.json").read_text())
    assert state["status"] == "in_transit"
    assert state["tracking_detail"] == "Accepted at USPS Origin Facility"


@patch("ebay_shipper.dashboard.EasyPostProvider")
def test_advance_to_scheduled_fails_on_pickup_error(mock_provider_cls, data_dir, client):
    """Advance from packed fails if EasyPost pickup fails, state stays packed."""
    mock_provider = MagicMock()
    mock_provider.schedule_pickup.return_value = None  # pickup failed
    mock_provider_cls.return_value = mock_provider

    oid = "22-22222-22222"

    # pending_confirmation → packed
    client.post(f"/api/orders/{oid}/advance")

    # packed → pickup_scheduled should fail
    resp = client.post(f"/api/orders/{oid}/advance")
    assert resp.status_code == 500

    # State should still be packed
    state = json.loads((data_dir / "orders" / oid / "state.json").read_text())
    assert state["status"] == "packed"


@patch("ebay_shipper.dashboard.EasyPostProvider")
def test_advance_to_scheduled_no_shipment_id(mock_provider_cls, data_dir):
    """Advance from packed fails if order has no shipment_id."""
    from ebay_shipper.dashboard import create_app
    # Create order with no shipment_id
    orders_dir = data_dir / "orders"
    order_dir = orders_dir / "88-88888-88888"
    order_dir.mkdir(parents=True)
    (order_dir / "state.json").write_text(json.dumps({
        "order_id": "88-88888-88888",
        "status": "packed",
        "tracking_number": "9400111899223456789012",
        "rate": "5.00",
        "shipment_id": "",
        "packing_list": str(order_dir / "packing_list.pdf"),
        "label": str(order_dir / "label.png"),
    }))

    app = create_app(data_dir, TEST_CONFIG)
    c = TestClient(app)

    resp = c.post("/api/orders/88-88888-88888/advance")
    assert resp.status_code == 400
    mock_provider_cls.assert_not_called()


def test_next_pickup_date_weekday():
    """next_pickup_date returns tomorrow on a weekday."""
    from datetime import datetime
    from ebay_shipper.label_provider import next_pickup_date, PACIFIC

    # Mock a Wednesday
    with patch("ebay_shipper.label_provider.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 4, 10, 0, tzinfo=PACIFIC)  # Wednesday
        mock_dt.strptime = datetime.strptime
        result = next_pickup_date()
        assert result == "2026-03-05"  # Thursday


def test_next_pickup_date_saturday():
    """next_pickup_date skips Sunday when called on Saturday."""
    from datetime import datetime
    from ebay_shipper.label_provider import next_pickup_date, PACIFIC

    with patch("ebay_shipper.label_provider.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 2, 28, 10, 0, tzinfo=PACIFIC)  # Saturday
        mock_dt.strptime = datetime.strptime
        result = next_pickup_date()
        assert result == "2026-03-02"  # Monday


def test_check_tracking_skips_non_porched(tmp_path):
    """check_tracking_updates skips orders not in porched/tracking state."""
    from ebay_shipper.main import check_tracking_updates

    orders_dir = tmp_path / "orders"
    order_dir = orders_dir / "55-55555-55555"
    order_dir.mkdir(parents=True)
    (order_dir / "state.json").write_text(json.dumps({
        "order_id": "55-55555-55555",
        "status": "packed",
        "tracking_number": "9400136208303461675547",
    }))

    provider = MagicMock()
    check_tracking_updates(orders_dir, provider)

    provider.check_tracking.assert_not_called()
