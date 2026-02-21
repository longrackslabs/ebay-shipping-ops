"""eBay OAuth2 token management.

Handles refresh token -> access token exchange for the Fulfillment API.
Reuses the longracks_msp eBay app with a separate refresh token.
"""

import base64
import logging
import time

import requests

logger = logging.getLogger(__name__)

EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"


class EbayAuth:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token = None
        self._token_expiry = 0

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        logger.info("Refreshing eBay access token")
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        response = requests.post(
            EBAY_TOKEN_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
            },
        )
        response.raise_for_status()
        token_data = response.json()

        self._access_token = token_data["access_token"]
        self._token_expiry = time.time() + token_data.get("expires_in", 7200)
        logger.info("eBay access token refreshed, expires in %ds", token_data.get("expires_in", 7200))
        return self._access_token
