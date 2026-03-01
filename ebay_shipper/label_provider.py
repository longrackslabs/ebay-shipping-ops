"""Shipping label provider interface.

Abstracts label generation so we can swap providers (EasyPost, Shippo, etc.)
without changing the rest of the code.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import easypost
import requests

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")


def next_pickup_date() -> str:
    """Return the next valid USPS pickup date (YYYY-MM-DD).

    Tomorrow, unless tomorrow is Sunday — then Monday.
    """
    now = datetime.now(PACIFIC)
    tomorrow = now + timedelta(days=1)
    # Sunday = 6 in weekday()
    if tomorrow.weekday() == 6:
        tomorrow += timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")


@dataclass
class ShipFromAddress:
    name: str
    street: str
    city: str
    state: str
    zip_code: str
    phone: str = ""
    company: str = ""


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
    shipment_id: str = ""  # EasyPost shipment ID, needed for pickup scheduling


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


def _pickup_state_path(data_dir: Path) -> Path:
    return data_dir / "pickup_state.json"


def _load_pickup_state(data_dir: Path) -> dict:
    path = _pickup_state_path(data_dir)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_pickup_state(data_dir: Path, state: dict):
    path = _pickup_state_path(data_dir)
    path.write_text(json.dumps(state, indent=2))


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

        # Compose label name: "Company (Person)" or just the name
        label_name = ship_from.name
        if ship_from.company:
            label_name = f"{ship_from.company} ({ship_from.name})"

        from_address = {
            "name": label_name,
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
            shipment_id=bought.id,
        )

    def schedule_pickup(
        self,
        shipment_id: str,
        ship_from: ShipFromAddress,
        data_dir: Path,
        instructions: str = "Front porch",
    ) -> str | None:
        """Schedule a USPS pickup for the next delivery day.

        Skips if a pickup is already scheduled for tomorrow. Returns the
        pickup confirmation or None if skipped/failed.
        """
        pickup_date = next_pickup_date()
        pacific = PACIFIC

        # Check if we already have a pickup scheduled for tomorrow
        state = _load_pickup_state(data_dir)
        if state.get("pickup_date") == pickup_date and state.get("status") == "scheduled":
            logger.info("Pickup already scheduled for %s (confirmation: %s)",
                        pickup_date, state.get("confirmation"))
            return state.get("confirmation")

        # Schedule pickup window: 8am-12pm Pacific (handles PST/PDT automatically)
        pickup_day = datetime.strptime(pickup_date, "%Y-%m-%d").replace(tzinfo=pacific)
        min_dt = pickup_day.replace(hour=8, minute=0, second=0, microsecond=0).isoformat()
        max_dt = pickup_day.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()

        try:
            address = {
                    "name": ship_from.name,
                    "street1": ship_from.street,
                    "city": ship_from.city,
                    "state": ship_from.state,
                    "zip": ship_from.zip_code,
                    "country": "US",
                    "phone": ship_from.phone,
                }
            if ship_from.company:
                address["company"] = ship_from.company

            pickup = self.client.pickup.create(
                shipment={"id": shipment_id},
                address=address,
                min_datetime=min_dt,
                max_datetime=max_dt,
                instructions=instructions,
                is_account_address=True,
            )

            # Buy the USPS pickup (free)
            bought = self.client.pickup.buy(
                pickup.id,
                carrier="USPS",
                service="NextDay",
            )

            confirmation = getattr(bought, "confirmation", pickup.id)
            _save_pickup_state(data_dir, {
                "pickup_date": pickup_date,
                "pickup_id": pickup.id,
                "confirmation": confirmation,
                "status": "scheduled",
                "scheduled_at": datetime.now(pacific).isoformat(),
            })

            logger.info("USPS pickup scheduled for %s (confirmation: %s)",
                        pickup_date, confirmation)
            return confirmation

        except Exception:
            logger.exception("Failed to schedule USPS pickup")
            return None

    def check_tracking(self, tracking_number: str) -> dict | None:
        """Check tracking status via EasyPost.

        Returns dict with 'status' and 'detail' (latest event message),
        or None on error.

        EasyPost statuses: pre_transit, in_transit, out_for_delivery, delivered,
        return_to_sender, failure, unknown.
        """
        try:
            tracker = self.client.tracker.create(
                tracking_code=tracking_number,
                carrier="USPS",
            )
            logger.debug("Tracking %s: %s", tracking_number, tracker.status)
            detail = None
            if tracker.tracking_details:
                latest = tracker.tracking_details[-1]
                detail = latest.message
            return {"status": tracker.status, "detail": detail}
        except Exception:
            logger.exception("Failed to check tracking for %s", tracking_number)
            return None
