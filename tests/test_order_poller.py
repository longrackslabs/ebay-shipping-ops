"""Tests for order poller."""

import json
from unittest.mock import MagicMock, patch

from ebay_shipper.order_poller import OrderPoller


def make_mock_auth():
    auth = MagicMock()
    auth.get_access_token.return_value = "fake-token"
    return auth


SAMPLE_ORDER_RESPONSE = {
    "orders": [
        {
            "orderId": "12-34567-89012",
            "creationDate": "2026-02-18T10:30:00Z",
            "buyer": {"username": "testbuyer123"},
            "pricingSummary": {
                "total": {"value": "19.99", "currency": "USD"},
            },
            "lineItems": [
                {"sku": "NZ-2MM", "title": "2mm Nozzle", "quantity": 1},
            ],
        },
    ],
    "total": 1,
}


@patch("ebay_shipper.order_poller.requests.get")
def test_poll_returns_new_orders(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_ORDER_RESPONSE
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    poller = OrderPoller(make_mock_auth(), tmp_path)
    orders = poller.poll()

    assert len(orders) == 1
    assert orders[0]["orderId"] == "12-34567-89012"


@patch("ebay_shipper.order_poller.requests.get")
def test_poll_skips_already_processed(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_ORDER_RESPONSE
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    poller = OrderPoller(make_mock_auth(), tmp_path)

    # First poll picks it up
    orders1 = poller.poll()
    assert len(orders1) == 1

    # Second poll skips it
    orders2 = poller.poll()
    assert len(orders2) == 0


@patch("ebay_shipper.order_poller.requests.get")
def test_poll_logs_orders_to_jsonl(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_ORDER_RESPONSE
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    poller = OrderPoller(make_mock_auth(), tmp_path)
    poller.poll()

    log_file = tmp_path / "orders.jsonl"
    assert log_file.exists()
    entries = [json.loads(line) for line in log_file.read_text().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["order_id"] == "12-34567-89012"
    assert entries[0]["buyer"] == "testbuyer123"


@patch("ebay_shipper.order_poller.requests.get")
def test_poll_empty_response(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.json.return_value = {"orders": [], "total": 0}
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    poller = OrderPoller(make_mock_auth(), tmp_path)
    orders = poller.poll()
    assert len(orders) == 0


@patch("ebay_shipper.order_poller.requests.get")
def test_poll_persists_processed_orders_across_instances(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_ORDER_RESPONSE
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    # First instance processes the order
    poller1 = OrderPoller(make_mock_auth(), tmp_path)
    poller1.poll()

    # New instance loads from disk
    poller2 = OrderPoller(make_mock_auth(), tmp_path)
    orders = poller2.poll()
    assert len(orders) == 0
