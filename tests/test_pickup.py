"""Tests for USPS pickup scheduling."""

import json
from unittest.mock import MagicMock, patch

from ebay_shipper.label_provider import (
    EasyPostProvider,
    ShipFromAddress,
    _load_pickup_state,
    _save_pickup_state,
)


SHIP_FROM = ShipFromAddress(
    name="George Peden",
    street="1994 NW 129th Pl",
    city="Portland",
    state="OR",
    zip_code="97229",
    phone="5033494247",
    company="Longracks Labs",
)


@patch("ebay_shipper.label_provider.easypost.EasyPostClient")
def test_schedule_pickup_creates_and_buys(mock_client_cls, tmp_path):
    """Test that schedule_pickup creates a pickup and buys it."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_pickup = MagicMock()
    mock_pickup.id = "pickup_123"
    mock_client.pickup.create.return_value = mock_pickup

    mock_bought = MagicMock()
    mock_bought.confirmation = "WTC12345"
    mock_client.pickup.buy.return_value = mock_bought

    provider = EasyPostProvider("test_key")
    result = provider.schedule_pickup("shp_abc", SHIP_FROM, tmp_path, "Front porch")

    assert result == "WTC12345"

    # Verify pickup was created with correct address
    create_call = mock_client.pickup.create.call_args
    assert create_call.kwargs["address"]["name"] == "George Peden"
    assert create_call.kwargs["address"]["phone"] == "5033494247"
    assert create_call.kwargs["address"]["company"] == "Longracks Labs"
    assert create_call.kwargs["address"]["street1"] == "1994 NW 129th Pl"
    assert create_call.kwargs["address"]["zip"] == "97229"
    assert create_call.kwargs["shipment"] == {"id": "shp_abc"}
    assert create_call.kwargs["instructions"] == "Front porch"

    # Verify pickup was bought with USPS
    mock_client.pickup.buy.assert_called_once_with(
        "pickup_123", carrier="USPS", service="NextDay",
    )

    # Verify state was saved
    state = _load_pickup_state(tmp_path)
    assert state["status"] == "scheduled"
    assert state["confirmation"] == "WTC12345"
    assert state["pickup_id"] == "pickup_123"


@patch("ebay_shipper.label_provider.easypost.EasyPostClient")
def test_schedule_pickup_skips_if_already_scheduled(mock_client_cls, tmp_path):
    """Test that schedule_pickup skips if a pickup is already scheduled for tomorrow."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # Pre-save a pickup state for tomorrow (Pacific time, matching the code)
    pacific = ZoneInfo("America/Los_Angeles")
    tomorrow = (datetime.now(pacific) + timedelta(days=1)).strftime("%Y-%m-%d")
    _save_pickup_state(tmp_path, {
        "pickup_date": tomorrow,
        "pickup_id": "pickup_existing",
        "confirmation": "WTC_EXISTING",
        "status": "scheduled",
    })

    provider = EasyPostProvider("test_key")
    result = provider.schedule_pickup("shp_xyz", SHIP_FROM, tmp_path)

    assert result == "WTC_EXISTING"
    # Should NOT have called the API
    mock_client.pickup.create.assert_not_called()


@patch("ebay_shipper.label_provider.easypost.EasyPostClient")
def test_schedule_pickup_reschedules_for_new_day(mock_client_cls, tmp_path):
    """Test that schedule_pickup creates a new pickup if existing one is for a different day."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # Pre-save a pickup state for yesterday (stale)
    _save_pickup_state(tmp_path, {
        "pickup_date": "2026-01-01",
        "pickup_id": "pickup_old",
        "confirmation": "WTC_OLD",
        "status": "scheduled",
    })

    mock_pickup = MagicMock()
    mock_pickup.id = "pickup_new"
    mock_client.pickup.create.return_value = mock_pickup

    mock_bought = MagicMock()
    mock_bought.confirmation = "WTC_NEW"
    mock_client.pickup.buy.return_value = mock_bought

    provider = EasyPostProvider("test_key")
    result = provider.schedule_pickup("shp_abc", SHIP_FROM, tmp_path)

    assert result == "WTC_NEW"
    mock_client.pickup.create.assert_called_once()


@patch("ebay_shipper.label_provider.easypost.EasyPostClient")
def test_schedule_pickup_handles_api_error(mock_client_cls, tmp_path):
    """Test that schedule_pickup returns None on API failure."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.pickup.create.side_effect = Exception("API error")

    provider = EasyPostProvider("test_key")
    result = provider.schedule_pickup("shp_abc", SHIP_FROM, tmp_path)

    assert result is None
    # No state should be saved on failure
    state = _load_pickup_state(tmp_path)
    assert state == {}


def test_pickup_state_persistence(tmp_path):
    """Test that pickup state saves and loads correctly."""
    state = {
        "pickup_date": "2026-02-23",
        "pickup_id": "pickup_123",
        "confirmation": "WTC12345",
        "status": "scheduled",
    }
    _save_pickup_state(tmp_path, state)
    loaded = _load_pickup_state(tmp_path)
    assert loaded == state


def test_pickup_state_returns_empty_when_missing(tmp_path):
    """Test that loading missing state returns empty dict."""
    loaded = _load_pickup_state(tmp_path)
    assert loaded == {}
