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
        """Generate a stub label PDF for testing."""
        from reportlab.lib.pagesizes import inch
        from reportlab.pdfgen import canvas

        logger.warning("Using STUB label provider — no real label generated")
        contact = ship_to.get("contactAddress", {})
        c = canvas.Canvas(str(output_path), pagesize=(4 * inch, 6 * inch))
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(2 * inch, 5.3 * inch, "STUB SHIPPING LABEL")
        c.setFont("Helvetica", 12)
        y = 4.8 * inch
        lines = [
            f"To: {ship_to.get('fullName', 'N/A')}",
            f"    {contact.get('addressLine1', '')}",
            f"    {contact.get('city', '')}, {contact.get('stateOrProvince', '')} {contact.get('postalCode', '')}",
            "",
            f"From: {ship_from.name}",
            f"Weight: {parcel.weight}oz",
            f"Tracking: STUB-0000000000",
        ]
        for line in lines:
            c.drawString(0.5 * inch, y, line)
            y -= 0.3 * inch
        c.save()
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

        # Create shipment with PNG label — PDF comes back letter-size, PNG is true 4x6
        shipment = self.client.shipment.create(
            to_address=to_address,
            from_address=from_address,
            parcel=parcel_data,
            options={"label_format": "PNG", "label_size": "4x6"},
        )

        # Buy cheapest USPS rate
        rate = shipment.lowest_rate(carriers=["USPS"])
        bought = self.client.shipment.buy(shipment.id, rate=rate)

        # Download PNG label
        label_url = bought.postage_label.label_url
        resp = requests.get(label_url, timeout=30)
        resp.raise_for_status()

        output_path = output_path.with_suffix(".png")
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
