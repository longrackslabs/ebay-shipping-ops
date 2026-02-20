"""Tests for label provider module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ebay_shipper.label_provider import (
    EasyPostProvider,
    Parcel,
    ShipFromAddress,
    StubLabelProvider,
    calculate_weight,
)


def test_calculate_weight_single_nozzle():
    items = [{"sku": "NZ-2MM", "quantity": 1}]
    assert calculate_weight(items) == 3


def test_calculate_weight_bundle():
    items = [{"sku": "NZ-BNDL-246", "quantity": 1}]
    assert calculate_weight(items) == 9


def test_calculate_weight_multiple_singles():
    items = [
        {"sku": "NZ-2MM", "quantity": 2},
        {"sku": "NZ-4MM", "quantity": 1},
    ]
    assert calculate_weight(items) == 9  # 3*2 + 3*1


def test_calculate_weight_mixed():
    items = [
        {"sku": "NZ-BNDL-246", "quantity": 1},
        {"sku": "NZ-6MM", "quantity": 1},
    ]
    assert calculate_weight(items) == 12  # 9 + 3


def test_calculate_weight_unknown_sku():
    items = [{"sku": "UNKNOWN", "quantity": 1}]
    assert calculate_weight(items) == 3  # default weight


def test_stub_label_provider(tmp_path):
    provider = StubLabelProvider()
    ship_to = {
        "fullName": "Test Buyer",
        "contactAddress": {
            "addressLine1": "123 Test St",
            "city": "Denver",
            "stateOrProvince": "CO",
            "postalCode": "80202",
        },
    }
    ship_from = ShipFromAddress(
        name="George Peden",
        street="456 Ship St",
        city="Boulder",
        state="CO",
        zip_code="80301",
    )
    parcel = Parcel(length=9, width=6, height=1, weight=3)
    output_path = tmp_path / "label.txt"

    label = provider.create_label(ship_to, ship_from, parcel, output_path)

    assert label.tracking_number == "STUB-0000000000"
    assert label.label_path == output_path
    assert output_path.exists()
    content = output_path.read_text()
    assert "Test Buyer" in content
    assert "George Peden" in content


@patch("ebay_shipper.label_provider.requests.get")
@patch("ebay_shipper.label_provider.easypost.EasyPostClient")
def test_easypost_provider_creates_label(mock_client_cls, mock_get, tmp_path):
    """Test EasyPostProvider creates a label via EasyPost API."""
    # Set up mock EasyPost client
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_rate = MagicMock()
    mock_rate.carrier = "USPS"
    mock_rate.service = "GroundAdvantage"
    mock_rate.rate = "4.50"

    mock_shipment = MagicMock()
    mock_shipment.id = "shp_123"
    mock_shipment.lowest_rate.return_value = mock_rate
    mock_client.shipment.create.return_value = mock_shipment

    mock_bought = MagicMock()
    mock_bought.tracking_code = "9400111899223456789012"
    mock_bought.postage_label.label_url = "https://easypost.com/label.pdf"
    mock_client.shipment.buy.return_value = mock_bought

    # Mock label download
    mock_response = MagicMock()
    mock_response.content = b"%PDF-1.4 fake label content"
    mock_get.return_value = mock_response

    # Create provider and generate label
    provider = EasyPostProvider("test_key")
    ship_to = {
        "fullName": "Test Buyer",
        "contactAddress": {
            "addressLine1": "123 Test St",
            "city": "Denver",
            "stateOrProvince": "CO",
            "postalCode": "80202",
            "countryCode": "US",
        },
    }
    ship_from = ShipFromAddress(
        name="George Peden",
        street="456 Ship St",
        city="Boulder",
        state="CO",
        zip_code="80301",
    )
    parcel = Parcel(length=9, width=6, height=1, weight=3)
    output_path = tmp_path / "label.pdf"

    label = provider.create_label(ship_to, ship_from, parcel, output_path)

    assert label.tracking_number == "9400111899223456789012"
    assert label.rate == "4.50"
    assert label.carrier == "USPS"
    assert label.service == "GroundAdvantage"
    assert label.label_path.exists()
    assert label.label_path.suffix == ".png"

    # Verify EasyPost API was called correctly
    create_call = mock_client.shipment.create.call_args
    assert create_call.kwargs["to_address"]["name"] == "Test Buyer"
    assert create_call.kwargs["from_address"]["name"] == "George Peden"
    assert create_call.kwargs["parcel"]["weight"] == 3
    assert create_call.kwargs["options"]["label_format"] == "PNG"

    mock_client.shipment.buy.assert_called_once_with("shp_123", rate=mock_rate)
    mock_shipment.lowest_rate.assert_called_once_with(carriers=["USPS"])


@patch("ebay_shipper.label_provider.easypost.EasyPostClient")
def test_easypost_provider_handles_missing_address_fields(mock_client_cls, tmp_path):
    """Test EasyPostProvider handles missing optional address fields."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    provider = EasyPostProvider("test_key")

    # Ship-to with minimal fields (no addressLine2, no countryCode)
    ship_to = {
        "fullName": "Minimal Buyer",
        "contactAddress": {
            "addressLine1": "789 Main St",
            "city": "Portland",
            "stateOrProvince": "OR",
            "postalCode": "97201",
        },
    }
    ship_from = ShipFromAddress(
        name="George", street="123 St", city="City", state="ST", zip_code="00000"
    )
    parcel = Parcel(length=9, width=6, height=1, weight=3)

    mock_rate = MagicMock()
    mock_rate.carrier = "USPS"
    mock_rate.service = "GroundAdvantage"
    mock_rate.rate = "3.00"

    mock_shipment = MagicMock()
    mock_shipment.id = "shp_456"
    mock_shipment.lowest_rate.return_value = mock_rate
    mock_client.shipment.create.return_value = mock_shipment

    mock_bought = MagicMock()
    mock_bought.tracking_code = "TRACK123"
    mock_bought.postage_label.label_url = "https://easypost.com/label2.pdf"
    mock_client.shipment.buy.return_value = mock_bought

    with patch("ebay_shipper.label_provider.requests.get") as mock_get:
        mock_get.return_value = MagicMock(content=b"fake pdf")
        label = provider.create_label(ship_to, ship_from, parcel, tmp_path / "label.pdf")

    # Should default country to US
    create_call = mock_client.shipment.create.call_args
    assert create_call.kwargs["to_address"]["country"] == "US"
    assert create_call.kwargs["to_address"]["street2"] == ""
    assert label.tracking_number == "TRACK123"
