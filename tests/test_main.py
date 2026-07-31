"""Tests for order processing — specifically the SKU recognition gate.

One-off/personal sales and odd-sized items don't have a configured SKU
prefix. These must be held for manual shipping, never guessed at with
default weight/box dimensions.
"""

import json

from ebay_shipper.label_provider import StubLabelProvider
from ebay_shipper.main import process_order
from ebay_shipper.packing_list import generate_packing_list  # noqa: F401 — ensures reportlab deps resolve

TEST_CONFIG = {
    "easypost_api_key": "",
    "from_name": "Longracks Labs (George Peden)",
    "from_street": "1994 NW 129th Pl",
    "from_city": "Portland",
    "from_state": "OR",
    "from_zip": "97229",
    "from_phone": "5033494247",
    "from_company": "Longracks Labs",
    "pickup_instructions": "Packages in bin on front porch",
    "printer_name": "Label_Printer",
    "pickup_enabled": False,
    "sku_config": {
        "NZ-BNDL": {"weight_oz": 4},
        "NZ-": {"weight_oz": 2},
    },
}


def make_order(order_id, line_items, buyer="jllegrand1", total="12.99"):
    return {
        "orderId": order_id,
        "buyer": {"username": buyer},
        "pricingSummary": {"total": {"value": total}},
        "fulfillmentStartInstructions": [{
            "shippingStep": {"shipTo": {
                "fullName": "Jane Buyer",
                "contactAddress": {
                    "addressLine1": "123 Main St",
                    "city": "Portland", "stateOrProvince": "OR",
                    "postalCode": "97201", "countryCode": "US",
                },
            }},
        }],
        "lineItems": line_items,
    }


def test_holds_order_with_unrecognized_sku(tmp_path):
    """A SKU with no matching prefix (e.g. a hand-listed 1-off) must not get a label."""
    order = make_order("03-11111-11111", [
        {"sku": "VINTAGE-CAMERA-LENS", "quantity": 1, "lineItemId": "LI1"},
    ])

    result = process_order(order, TEST_CONFIG, StubLabelProvider(), tmp_path)

    assert result is False

    order_dir = tmp_path / "03-11111-11111"
    state = json.loads((order_dir / "state.json").read_text())
    assert state["status"] == "unrecognized_sku"
    assert state["unknown_skus"] == ["VINTAGE-CAMERA-LENS"]
    assert state["label"] == ""
    assert state["packing_list"] == ""

    # Nothing was generated — no wasted label/packing list for an order
    # that needs a human to pick the right box and postage.
    assert not (order_dir / "label.pdf").exists()
    assert not (order_dir / "packing_list.pdf").exists()


def test_holds_order_with_missing_sku(tmp_path):
    """Listings sold without ever setting a SKU must also be held, not defaulted."""
    order = make_order("03-22222-22222", [
        {"quantity": 1, "lineItemId": "LI1"},  # no "sku" key at all
    ])

    result = process_order(order, TEST_CONFIG, StubLabelProvider(), tmp_path)

    assert result is False
    state = json.loads((tmp_path / "03-22222-22222" / "state.json").read_text())
    assert state["status"] == "unrecognized_sku"
    assert state["unknown_skus"] == ["(no SKU)"]


def test_holds_mixed_order_if_any_sku_unrecognized(tmp_path):
    """A recognized SKU alongside an unrecognized one still holds the whole order —
    printing a packing list for half an order isn't useful."""
    order = make_order("03-33333-33333", [
        {"sku": "NZ-4MM", "quantity": 1, "lineItemId": "LI1"},
        {"sku": "RANDOM-EBAY-ITEM", "quantity": 1, "lineItemId": "LI2"},
    ])

    result = process_order(order, TEST_CONFIG, StubLabelProvider(), tmp_path)

    assert result is False
    state = json.loads((tmp_path / "03-33333-33333" / "state.json").read_text())
    assert state["status"] == "unrecognized_sku"
    assert state["unknown_skus"] == ["RANDOM-EBAY-ITEM"]


def test_recognized_sku_still_processes_normally(tmp_path):
    """Existing behavior for known SKUs must be unaffected by the new gate."""
    order = make_order("03-44444-44444", [
        {"sku": "NZ-4MM", "quantity": 1, "lineItemId": "LI1"},
    ])

    result = process_order(order, TEST_CONFIG, StubLabelProvider(), tmp_path)

    assert result is True
    order_dir = tmp_path / "03-44444-44444"
    state = json.loads((order_dir / "state.json").read_text())
    assert state["status"] == "pending_confirmation"
    assert state["label"] != ""
    assert state["packing_list"] != ""
