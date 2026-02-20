"""Tests for packing list generation."""

from pathlib import Path

from ebay_shipper.packing_list import generate_packing_list

SAMPLE_ORDER = {
    "orderId": "12-34567-89012",
    "creationDate": "2026-02-18T10:30:00Z",
    "buyer": {"username": "testbuyer123"},
    "pricingSummary": {
        "total": {"value": "19.99", "currency": "USD"},
    },
    "fulfillmentStartInstructions": [
        {
            "shippingStep": {
                "shipTo": {
                    "fullName": "Jane Smith",
                    "contactAddress": {
                        "addressLine1": "789 Buyer Ave",
                        "addressLine2": "Apt 4B",
                        "city": "Portland",
                        "stateOrProvince": "OR",
                        "postalCode": "97201",
                    },
                },
            },
        }
    ],
    "lineItems": [
        {
            "sku": "NZ-2MM",
            "title": "2mm Brass Nozzle for 3D Printer",
            "quantity": 1,
        },
    ],
}


def test_generate_packing_list_creates_pdf(tmp_path):
    output = tmp_path / "packing_list.pdf"
    result = generate_packing_list(SAMPLE_ORDER, output)
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_generate_packing_list_pdf_header(tmp_path):
    """Verify the output is a valid PDF."""
    output = tmp_path / "packing_list.pdf"
    generate_packing_list(SAMPLE_ORDER, output)
    with open(output, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


def test_generate_packing_list_multiple_items(tmp_path):
    order = {
        **SAMPLE_ORDER,
        "lineItems": [
            {"sku": "NZ-2MM", "title": "2mm Nozzle", "quantity": 2},
            {"sku": "NZ-4MM", "title": "4mm Nozzle", "quantity": 1},
        ],
        "pricingSummary": {
            "total": {"value": "39.97", "currency": "USD"},
        },
    }
    output = tmp_path / "packing_list.pdf"
    result = generate_packing_list(order, output)
    assert result == output
    assert output.exists()
