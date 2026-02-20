"""Shipping label provider interface.

Abstracts label generation so we can swap providers (EasyPost, Shippo, etc.)
without changing the rest of the code.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

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
