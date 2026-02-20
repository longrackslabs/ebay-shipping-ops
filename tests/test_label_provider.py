"""Tests for label provider module."""

from pathlib import Path

from ebay_shipper.label_provider import (
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
