"""Shipping label provider interface.

Abstracts label generation so we can swap providers (EasyPost, Shippo, etc.)
without changing the rest of the code.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import easypost
import requests

logger = logging.getLogger(__name__)


@dataclass
class ShipFromAddress:
    name: str
    street: str
    city: str
    state: str
    zip_code: str


@dataclass
class Parcel:
    length: float  # inches
    width: float   # inches
    height: float  # inches
    weight: float  # ounces


@dataclass
class ShippingLabel:
    tracking_number: str
    label_path: Path
    rate: str  # e.g. "3.50"
    carrier: str  # e.g. "USPS"
    service: str  # e.g. "ParcelSelect"


# Standard parcel for all nozzle shipments
STANDARD_PARCEL = Parcel(length=9, width=6, height=1, weight=0)  # weight set per order

# Weight per SKU pattern (ounces)
SKU_WEIGHTS = {
    "NZ-BNDL": 9,  # bundle
    "NZ-": 3,       # single nozzle (fallback)
}


def calculate_weight(line_items: list[dict]) -> float:
    """Calculate total package weight from order line items."""
    total_oz = 0
    for item in line_items:
        sku = item.get("sku", "")
        qty = item.get("quantity", 1)
        weight = 3  # default
        for prefix, oz in SKU_WEIGHTS.items():
            if sku.startswith(prefix):
                weight = oz
                break
        total_oz += weight * qty
    return total_oz


class StubLabelProvider:
    """Stub provider that generates a placeholder label for testing.

    Replace with EasyPostProvider or ShippoProvider when API access is ready.
    """

    def create_label(
        self,
        ship_to: dict,
        ship_from: ShipFromAddress,
        parcel: Parcel,
        output_path: Path,
    ) -> ShippingLabel:
        """Generate a stub label file for testing."""
        logger.warning("Using STUB label provider — no real label generated")
        output_path.write_text(
            f"STUB SHIPPING LABEL\n"
            f"To: {ship_to.get('fullName', 'N/A')}\n"
            f"    {ship_to.get('contactAddress', {}).get('addressLine1', '')}\n"
            f"    {ship_to.get('contactAddress', {}).get('city', '')}, "
            f"{ship_to.get('contactAddress', {}).get('stateOrProvince', '')} "
            f"{ship_to.get('contactAddress', {}).get('postalCode', '')}\n"
            f"From: {ship_from.name}\n"
            f"Weight: {parcel.weight}oz\n"
            f"Tracking: STUB-0000000000\n"
        )
        return ShippingLabel(
            tracking_number="STUB-0000000000",
            label_path=output_path,
            rate="0.00",
            carrier="STUB",
            service="StubService",
        )


class EasyPostProvider:
    """Real shipping label provider using EasyPost API."""

    def __init__(self, api_key: str):
        self.client = easypost.EasyPostClient(api_key)

    def create_label(
        self,
        ship_to: dict,
        ship_from: ShipFromAddress,
        parcel: Parcel,
        output_path: Path,
    ) -> ShippingLabel:
        """Create a real USPS shipping label via EasyPost."""
        # Map eBay address format to EasyPost format
        contact = ship_to.get("contactAddress", {})
        to_address = {
            "name": ship_to.get("fullName", ""),
            "street1": contact.get("addressLine1", ""),
            "street2": contact.get("addressLine2", ""),
            "city": contact.get("city", ""),
            "state": contact.get("stateOrProvince", ""),
            "zip": contact.get("postalCode", ""),
            "country": contact.get("countryCode", "US"),
        }

        from_address = {
            "name": ship_from.name,
            "street1": ship_from.street,
            "city": ship_from.city,
            "state": ship_from.state,
            "zip": ship_from.zip_code,
            "country": "US",
        }

        parcel_data = {
            "length": parcel.length,
            "width": parcel.width,
            "height": parcel.height,
            "weight": parcel.weight,
        }

        # Create shipment with ZPL label format for Rollo thermal printer
        shipment = self.client.shipment.create(
            to_address=to_address,
            from_address=from_address,
            parcel=parcel_data,
            options={"label_format": "ZPL", "label_size": "4x6"},
        )

        # Buy cheapest USPS rate
        rate = shipment.lowest_rate(carriers=["USPS"])
        bought = self.client.shipment.buy(shipment.id, rate=rate)

        # Download ZPL label
        label_url = bought.postage_label.label_url
        resp = requests.get(label_url, timeout=30)
        resp.raise_for_status()

        output_path = output_path.with_suffix(".zpl")
        output_path.write_bytes(resp.content)

        logger.info(
            "Label created: %s via %s %s — $%s",
            bought.tracking_code,
            rate.carrier,
            rate.service,
            rate.rate,
        )

        return ShippingLabel(
            tracking_number=bought.tracking_code,
            label_path=output_path,
            rate=rate.rate,
            carrier=rate.carrier,
            service=rate.service,
        )
