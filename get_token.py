"""eBay OAuth2 token acquisition script.

Run this once to get a refresh token for the Fulfillment API.

Usage:
    python get_token.py

It will:
1. Print a URL — open it in your browser
2. Log in to eBay and authorize
3. You'll be redirected to a URL — paste it back here
4. Script exchanges the code for a refresh token
"""

import base64
import os
import urllib.parse

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["EBAY_CLIENT_ID"]
CLIENT_SECRET = os.environ["EBAY_CLIENT_SECRET"]

# eBay requires a redirect URI configured in your app settings
# The developer portal's default is this:
REDIRECT_URI = "George_Peden-GeorgePe-longra-bkhsghd"

SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
]

AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"


def main():
    # Step 1: Generate authorization URL
    scope_str = " ".join(SCOPES)
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scope_str,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\n=== eBay OAuth2 Token Generator ===\n")
    print("1. Open this URL in your browser:\n")
    print(url)
    print("\n2. Log in to eBay and authorize the app")
    print("3. You'll be redirected to a page (may show an error — that's OK)")
    print("4. Copy the ENTIRE URL from your browser's address bar and paste it below\n")

    redirect_url = input("Paste the redirect URL here: ").strip()

    # Step 2: Extract the authorization code
    parsed = urllib.parse.urlparse(redirect_url)
    query = urllib.parse.parse_qs(parsed.query)

    if "code" not in query:
        print(f"\nERROR: No authorization code found in URL")
        print(f"URL params: {query}")
        return

    auth_code = query["code"][0]
    print(f"\nGot authorization code: {auth_code[:20]}...")

    # Step 3: Exchange code for tokens
    credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
    )

    if response.status_code != 200:
        print(f"\nERROR: Token exchange failed ({response.status_code})")
        print(response.text)
        return

    token_data = response.json()
    refresh_token = token_data.get("refresh_token", "")
    access_token = token_data.get("access_token", "")

    print(f"\n=== SUCCESS ===\n")
    print(f"Access token (expires in {token_data.get('expires_in', '?')}s):")
    print(f"  {access_token[:50]}...\n")
    print(f"Refresh token (save this!):")
    print(f"  {refresh_token}\n")
    print(f"Put the refresh token in your .env as EBAY_REFRESH_TOKEN")


if __name__ == "__main__":
    main()
