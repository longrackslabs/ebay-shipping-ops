"""eBay Shipper — main service loop.

Polls for new eBay orders, generates packing lists and shipping labels,
and prints them to a Rollo thermal printer.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from ebay_shipper.ebay_auth import EbayAuth
from ebay_shipper.label_provider import (
    STANDARD_PARCEL,
    EasyPostProvider,
    ShipFromAddress,
    StubLabelProvider,
    calculate_weight,
)
from ebay_shipper.order_poller import OrderPoller, create_shipping_fulfillment
from ebay_shipper.packing_list import generate_packing_list
from ebay_shipper.printer import print_file

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".ebay-shipper"
DEFAULT_POLL_INTERVAL = 300  # 5 minutes
ERROR_RETRY_INTERVAL = 300  # 5 minutes


def setup_logging():
    """Configure logging to stdout and file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / "service.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(file_handler)


def load_config() -> dict:
    """Load configuration from environment variables."""
    # Try .env in data dir, then project root
    env_file = DATA_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()

    required = ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_REFRESH_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    return {
        "ebay_client_id": os.environ["EBAY_CLIENT_ID"],
        "ebay_client_secret": os.environ["EBAY_CLIENT_SECRET"],
        "ebay_refresh_token": os.environ["EBAY_REFRESH_TOKEN"],
        "easypost_api_key": os.getenv("EASYPOST_API_KEY", ""),
        "printer_name": os.getenv("PRINTER_NAME", "Rollo"),
        "poll_interval": int(os.getenv("POLL_INTERVAL", DEFAULT_POLL_INTERVAL)),
        "from_name": os.getenv("FROM_NAME", ""),
        "from_street": os.getenv("FROM_STREET", ""),
        "from_city": os.getenv("FROM_CITY", ""),
        "from_state": os.getenv("FROM_STATE", ""),
        "from_zip": os.getenv("FROM_ZIP", ""),
        "pickup_instructions": os.getenv("PICKUP_INSTRUCTIONS", "Front porch"),
        "from_phone": os.getenv("FROM_PHONE", ""),
        "from_company": os.getenv("FROM_COMPANY", ""),
    }


def _generate_error_label(output_path: Path, order_id: str):
    """Generate a 4x6 error label PDF so the Rollo alerts you to a failure."""
    from reportlab.lib.pagesizes import inch
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(output_path), pagesize=(4 * inch, 6 * inch))
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(2 * inch, 4.5 * inch, "LABEL FAILED")
    c.setFont("Helvetica", 14)
    c.drawCentredString(2 * inch, 3.8 * inch, f"Order: {order_id}")
    c.setFont("Helvetica", 12)
    c.drawCentredString(2 * inch, 3.2 * inch, "Check EasyPost wallet balance")
    c.drawCentredString(2 * inch, 2.8 * inch, "and service.log for details")
    c.save()


def process_order(order: dict, config: dict, label_provider, output_dir: Path, auth: EbayAuth = None) -> bool:
    """Process a single order: generate packing list + label, hold for confirmation."""
    order_id = order["orderId"]
    order_dir = output_dir / order_id
    order_dir.mkdir(parents=True, exist_ok=True)

    # Save full order JSON for retry
    (order_dir / "order.json").write_text(json.dumps(order, indent=2))

    # Generate packing list
    packing_list_path = order_dir / "packing_list.pdf"
    generate_packing_list(order, packing_list_path)

    # Extract ship-to address
    fulfillment = order.get("fulfillmentStartInstructions", [{}])
    if not fulfillment:
        logger.error("Order %s has no fulfillment instructions", order_id)
        return False
    ship_to = fulfillment[0].get("shippingStep", {}).get("shipTo", {})

    # Calculate weight from line items
    weight = calculate_weight(order.get("lineItems", []))
    parcel = STANDARD_PARCEL
    parcel = type(parcel)(
        length=parcel.length,
        width=parcel.width,
        height=parcel.height,
        weight=weight,
    )

    ship_from = ShipFromAddress(
        name=config["from_name"],
        street=config["from_street"],
        city=config["from_city"],
        state=config["from_state"],
        zip_code=config["from_zip"],
    )
    label_path = order_dir / "label.pdf"
    label = None
    try:
        label = label_provider.create_label(ship_to, ship_from, parcel, label_path)
    except Exception:
        logger.exception("LABEL FAILED for order %s", order_id)

    # Save order state
    state = {
        "order_id": order_id,
        "status": "label_failed" if label is None else "pending_confirmation",
        "tracking_number": label.tracking_number if label else "",
        "rate": label.rate if label else "",
        "packing_list": str(packing_list_path),
        "label": str(label.label_path) if label else "",
    }
    (order_dir / "state.json").write_text(json.dumps(state, indent=2))

    printer_name = config["printer_name"]
    if label:
        # Print packing list + label
        if print_file(packing_list_path, printer_name):
            logger.info("Packing list printed for %s", order_id)
        else:
            logger.error("Failed to auto-print packing list for %s", order_id)

        if print_file(label.label_path, printer_name):
            logger.info("Label printed for %s", order_id)
        else:
            logger.error("Failed to auto-print label for %s", order_id)

        # Upload tracking to eBay (only for production labels)
        api_key = config.get("easypost_api_key", "")
        is_production = auth and label.carrier != "STUB" and not api_key.startswith("EZTK")
        if is_production:
            create_shipping_fulfillment(auth, order, label.tracking_number, label.carrier)

        # Schedule USPS pickup (only for production EasyPost labels)
        if is_production and isinstance(label_provider, EasyPostProvider) and label.shipment_id:
            pickup_from = ShipFromAddress(
                name=config["from_name"],
                street=config["from_street"],
                city=config["from_city"],
                state=config["from_state"],
                zip_code=config["from_zip"],
                phone=config["from_phone"],
                company=config["from_company"],
            )
            label_provider.schedule_pickup(
                label.shipment_id, pickup_from, output_dir.parent,
                instructions=config["pickup_instructions"],
            )
    else:
        # Only print error label — retry will print both when it succeeds
        error_path = order_dir / "error_label.pdf"
        _generate_error_label(error_path, order_id)
        print_file(error_path, printer_name)

    buyer = order.get("buyer", {}).get("username", "unknown")
    total = order.get("pricingSummary", {}).get("total", {}).get("value", "?")
    items = ", ".join(
        f"{i.get('sku', '?')} x{i.get('quantity', 1)}"
        for i in order.get("lineItems", [])
    )
    logger.info(
        "ORDER %s — %s | Buyer: %s | Items: %s | Total: $%s",
        "READY" if label else "FAILED (no label)",
        order_id, buyer, items, total,
    )
    return label is not None


def confirm_order(order_id: str, config: dict):
    """Confirm and print a pending order."""
    order_dir = DATA_DIR / "orders" / order_id
    state_file = order_dir / "state.json"

    if not state_file.exists():
        logger.error("Order %s not found or not pending", order_id)
        return False

    state = json.loads(state_file.read_text())
    if state["status"] != "pending_confirmation":
        logger.error("Order %s status is '%s', not pending_confirmation", order_id, state["status"])
        return False

    printer_name = config["printer_name"]

    # Print packing list first (on top of stack)
    packing_ok = print_file(Path(state["packing_list"]), printer_name)
    if not packing_ok:
        logger.error("Failed to print packing list for %s", order_id)
        return False

    # Print shipping label
    label_ok = print_file(Path(state["label"]), printer_name)
    if not label_ok:
        logger.error("Failed to print label for %s", order_id)
        return False

    # Update state
    state["status"] = "shipped"
    state_file.write_text(json.dumps(state, indent=2))
    logger.info("Order %s confirmed and printed", order_id)
    return True


def main():
    """Main entry point."""
    setup_logging()
    logger.info("ebay-shipper starting")

    config = load_config()

    # Handle CLI subcommands
    if len(sys.argv) >= 3 and sys.argv[1] == "confirm":
        order_id = sys.argv[2]
        success = confirm_order(order_id, config)
        sys.exit(0 if success else 1)

    if len(sys.argv) >= 3 and sys.argv[1] == "retry":
        order_id = sys.argv[2]
        order_dir = DATA_DIR / "orders" / order_id
        order_file = order_dir / "order.json"
        state_file = order_dir / "state.json"
        if not order_file.exists():
            logger.error("Order %s not found (no order.json)", order_id)
            sys.exit(1)
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        if state.get("status") != "label_failed":
            logger.error("Order %s status is '%s', not label_failed", order_id, state.get("status"))
            sys.exit(1)
        order = json.loads(order_file.read_text())
        auth = EbayAuth(
            client_id=config["ebay_client_id"],
            client_secret=config["ebay_client_secret"],
            refresh_token=config["ebay_refresh_token"],
        )
        label_provider = EasyPostProvider(config["easypost_api_key"])
        success = process_order(order, config, label_provider, DATA_DIR / "orders", auth=auth)
        sys.exit(0 if success else 1)

    # Service mode: poll for orders
    auth = EbayAuth(
        client_id=config["ebay_client_id"],
        client_secret=config["ebay_client_secret"],
        refresh_token=config["ebay_refresh_token"],
    )
    poller = OrderPoller(auth, DATA_DIR)
    if config["easypost_api_key"]:
        label_provider = EasyPostProvider(config["easypost_api_key"])
    else:
        label_provider = StubLabelProvider()
    output_dir = DATA_DIR / "orders"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Polling every %ds (printer: %s, label provider: %s)",
        config["poll_interval"],
        config["printer_name"],
        type(label_provider).__name__,
    )

    while True:
        try:
            new_orders = poller.poll()
            for order in new_orders:
                process_order(order, config, label_provider, output_dir, auth=auth)
            if not new_orders:
                logger.debug("No new orders")
        except Exception:
            logger.exception("Error during poll cycle, retrying in %ds", ERROR_RETRY_INTERVAL)
            time.sleep(ERROR_RETRY_INTERVAL)
            continue

        time.sleep(config["poll_interval"])


if __name__ == "__main__":
    main()
