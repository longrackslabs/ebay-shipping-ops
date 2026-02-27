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
