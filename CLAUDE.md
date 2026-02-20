# eBay Shipper

Detects eBay sales via Fulfillment API, generates packing list PDF, creates shipping label via EasyPost, prints both to Rollo thermal printer.

## Architecture

- **Service mode**: Polls eBay Fulfillment API every 300s for new orders
- **Confirm mode**: `ebay-shipper confirm <order_id>` prints packing list + label
- Data dir: `~/.ebay-shipper/` (logs, orders, labels)
- Runs on Linux box: 192.168.254.99, user gpeden, repo at ~/src/ebay-shipper
- Mac dev at ~/src/ebay-shipper

## Key Files

| File | What |
|------|------|
| `ebay_shipper/main.py` | Service loop, CLI entry point, order processing |
| `ebay_shipper/label_provider.py` | EasyPost + stub label providers, weight calc |
| `ebay_shipper/printer.py` | CUPS/lpr printing to Rollo |
| `ebay_shipper/packing_list.py` | 4x6 packing list PDF via reportlab |
| `ebay_shipper/order_poller.py` | eBay Fulfillment API polling |
| `ebay_shipper/ebay_auth.py` | OAuth2 token refresh for eBay |
| `get_token.py` | One-time OAuth2 authorization code flow |

## Environment

- Python 3.12 on Linux, 3.14 on Mac
- `.env` file has all secrets — MUST be copied to Linux box after changes: `scp .env gpeden@192.168.254.99:~/src/ebay-shipper/.env`
- `.env` is NOT in git (gitignored)

### Required .env vars

```
EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_REFRESH_TOKEN
EASYPOST_API_KEY          # test keys start with EZTK
FROM_NAME="Longracks Labs (George Peden)"
FROM_STREET="1994 NW 129th Pl"
FROM_CITY="Portland"
FROM_STATE="OR"
FROM_ZIP="97229"
PRINTER_NAME=Label_Printer
POLL_INTERVAL=300
```

## Printing — Hard-Won Knowledge

These are not suggestions. These are facts learned by wasting labels.

- **EasyPost USPS PDF labels are LETTER SIZE (8.5x11)** with the label in the upper corner. `label_size: "4x6"` does NOT change this. Do NOT use PDF format.
- **EasyPost USPS ZPL labels do NOT print on the Rollo X1040.** Don't try.
- **EasyPost PNG format with `label_size: "4x6"` works.** Returns 1200x1800px at 300 DPI = true 4x6.
- **CUPS print options for Rollo**: `lpr -P Label_Printer -o media=w288h432 -o fit-to-page`
  - `w288h432` = 4x6 inches in points (288pt x 432pt), native Rollo driver size
  - `fit-to-page` scales content to fill the label
  - Rollo CUPS printer name is `Label_Printer`, NOT `Rollo`
  - Rollo native resolution: 203 DPI
- **Packing lists** are generated as 4x6 PDFs via reportlab — these print fine as PDF because they ARE 4x6.

## eBay API

- Reuses `longracks_msp` eBay app with SEPARATE OAuth refresh token from ebay-mcp
- RuName: `George_Peden-GeorgePe-longra-bkhsghd`
- eBay date filter format: no microseconds, Z suffix (`2026-02-19T00:00:00Z`)
- OAuth token acquired via `get_token.py` (authorization code flow) — NOT the eBay portal "User Tokens" page, those don't work with refresh flow

## Test Data

Use real values in test fixtures, not placeholder garbage:
- From name: `Longracks Labs (George Peden)` — NOT "George Peden", NOT "Long Racks Labs"
- From address: `1994 NW 129th Pl, Portland, OR 97229`
- When writing ad-hoc test scripts, read FROM_NAME from .env — don't hardcode

## Development

```bash
source .venv/bin/activate
python -m pytest tests/ -q       # run tests
scp .env gpeden@192.168.254.99:~/src/ebay-shipper/.env  # sync secrets
ssh gpeden@192.168.254.99 "cd ~/src/ebay-shipper && git pull"  # deploy
```

## Standing Orders

- **Do NOT claim "done" without printing a label on the actual Rollo.** Unit tests passing is not done.
- **Do NOT use placeholder test data.** Use the real from-address and business name.
- **Verify every change on the Linux box.** The Mac is for dev, the Linux box is production.
- **When testing EasyPost, always load .env values** — don't hardcode addresses in test scripts.
