"""eBay Fulfillment API order poller.

Polls for new orders since last check and returns order details.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

from ebay_shipper.ebay_auth import EbayAuth

logger = logging.getLogger(__name__)

FULFILLMENT_API_BASE = "https://api.ebay.com/sell/fulfillment/v1"


def create_shipping_fulfillment(
    auth: EbayAuth,
    order: dict,
    tracking_number: str,
    carrier: str,
) -> bool:
    """Upload tracking number to eBay and mark order as shipped.

    WARNING: This is irreversible. Only call with real tracking numbers.
    """
    order_id = order["orderId"]
    line_items = [
        {"lineItemId": item["lineItemId"], "quantity": item.get("quantity", 1)}
        for item in order.get("lineItems", [])
    ]

    token = auth.get_access_token()
    response = requests.post(
        f"{FULFILLMENT_API_BASE}/order/{order_id}/shipping_fulfillment",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "lineItems": line_items,
            "shippingCarrierCode": carrier,
            "trackingNumber": tracking_number,
        },
    )

    if response.status_code == 201:
        logger.info("Order %s marked as shipped — tracking: %s", order_id, tracking_number)
        return True
    else:
        logger.error(
            "Failed to mark order %s as shipped: %s %s",
            order_id, response.status_code, response.text,
        )
        return False


class OrderPoller:
    def __init__(self, auth: EbayAuth, data_dir: Path):
        self.auth = auth
        self.data_dir = data_dir
        self.orders_log = data_dir / "orders.jsonl"
        self.state_file = data_dir / "poller_state.json"
        self._processed_order_ids = self._load_processed_orders()

    def _load_processed_orders(self) -> set:
        """Load already-processed order IDs from the JSONL log."""
        processed = set()
        if self.orders_log.exists():
            for line in self.orders_log.read_text().strip().splitlines():
                try:
                    entry = json.loads(line)
                    processed.add(entry["order_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        logger.info("Loaded %d previously processed orders", len(processed))
        return processed

    @staticmethod
    def _format_timestamp(dt: datetime) -> str:
        """Format a datetime as eBay-compatible ISO8601 (no microseconds, Z suffix)."""
        return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _get_last_check_time(self) -> str:
        """Get the last poll timestamp, or default to 24h ago."""
        if self.state_file.exists():
            state = json.loads(self.state_file.read_text())
            return state.get("last_check")
        # Default: look back 24 hours
        from datetime import timedelta
        return self._format_timestamp(datetime.now(timezone.utc) - timedelta(hours=24))

    def _save_last_check_time(self, timestamp: str):
        """Persist the last poll timestamp."""
        self.state_file.write_text(json.dumps({"last_check": timestamp}))

    def _log_order(self, order: dict, status: str):
        """Append an order to the JSONL log."""
        entry = {
            "order_id": order["orderId"],
            "status": status,
            "buyer": order.get("buyer", {}).get("username", "unknown"),
            "total": order.get("pricingSummary", {}).get("total", {}).get("value", "0"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "line_items": [
                {
                    "sku": item.get("sku", ""),
                    "title": item.get("title", ""),
                    "quantity": item.get("quantity", 1),
                }
                for item in order.get("lineItems", [])
            ],
        }
        with open(self.orders_log, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def poll(self) -> list[dict]:
        """Poll for new orders since last check. Returns list of new order dicts."""
        now = self._format_timestamp(datetime.now(timezone.utc))
        last_check = self._get_last_check_time()

        logger.info("Polling for orders since %s", last_check)

        token = self.auth.get_access_token()
        response = requests.get(
            f"{FULFILLMENT_API_BASE}/order",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            params={
                "filter": f"creationdate:[{last_check}..{now}]",
                "limit": "50",
            },
        )
        response.raise_for_status()
        data = response.json()

        orders = data.get("orders", [])
        logger.info("Found %d total orders in time window", len(orders))

        new_orders = []
        for order in orders:
            order_id = order["orderId"]
            if order_id in self._processed_order_ids:
                continue

            logger.info(
                "New order: %s — %s item(s), total $%s",
                order_id,
                len(order.get("lineItems", [])),
                order.get("pricingSummary", {}).get("total", {}).get("value", "?"),
            )
            self._log_order(order, "detected")
            self._processed_order_ids.add(order_id)
            new_orders.append(order)

        self._save_last_check_time(now)
        return new_orders
