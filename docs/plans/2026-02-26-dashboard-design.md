# eBay Shipper Dashboard — Design

**Date:** 2026-02-26

## Problem

The only notification of a new sale is the Rollo printing a label. If you're not in the garage, you miss it — Larry's order sat for a day because the email was deleted and there's no persistent status view.

## Solution

A lightweight web dashboard on the Linux box (port 8080) that shows order status, pickup schedule, and provides action buttons. Auto-refreshes every 30 seconds so you can leave it open like a status board.

Plus a Cowork skill for quick conversational checks ("what orders are pending?").

## Architecture

Two independent processes on the Linux box:

```
ebay-shipper          — existing poller/printer service (unchanged)
ebay-shipper dashboard — new subcommand, starts FastAPI web server on :8080
```

Both read/write the same `~/.ebay-shipper/` data directory. No database — the JSON state files are the source of truth.

## Dashboard Layout

### Header

- **LONGRACKS LABS** title
- Service status indicator (green/red based on last log entry recency)

### Attention Banner

Big, prominent banner when orders need action:

- "2 orders need packing" — orange, links to the orders
- "All caught up" — green, when nothing pending

### Orders Table

Each order from `~/.ebay-shipper/orders/*/state.json` + `order.json`:

| Column | Source |
|--------|--------|
| Order ID | state.json `order_id` |
| Buyer | order.json `buyer.username` |
| Items | order.json `lineItems[].sku` x qty |
| Total | order.json `pricingSummary.total.value` |
| Status | state.json `status` — badge: green=shipped, orange=pending, red=failed |
| Tracking | state.json `tracking_number` — clickable USPS link |
| Label Cost | state.json `rate` |

Sorted by most recent first (directory mtime).

### Actions per Order

| Button | Condition | What it does |
|--------|-----------|--------------|
| Reprint | status = pending_confirmation | Same as `ebay-shipper confirm` — reprints packing list + label |
| Retry | status = label_failed | Same as `ebay-shipper retry` — reprocesses the order |

### Pickup Section

- Current pickup status from `pickup_state.json` (date, confirmation, or "none scheduled")
- **Schedule Pickup** button — triggers pickup for most recent order's shipment

### Service Log

Last 10 lines of `service.log` — quick health check without SSH.

## Tech Stack

- **Backend:** FastAPI (already in Python ecosystem, async-friendly)
- **Frontend:** Single HTML file, Tailwind CSS via CDN, vanilla JS
- **Auto-refresh:** JS `setInterval` polling API every 30 seconds
- **No auth** — local network only (192.168.254.99)
- **No build step** — no Node, no npm

## API Endpoints

```
GET  /api/orders          — list all orders with state + order details
GET  /api/pickup          — current pickup state
GET  /api/health          — service status (last log line, uptime)
POST /api/orders/{id}/reprint  — reprint packing list + label
POST /api/orders/{id}/retry    — retry failed label
POST /api/pickup               — schedule pickup
```

## File Structure

```
ebay_shipper/
  dashboard.py        — FastAPI app, all API routes
  templates/
    index.html        — single-page dashboard
```

## Deployment

- Add `fastapi` and `uvicorn` to dependencies
- New CLI subcommand: `ebay-shipper dashboard`
- Run as background process: `nohup .venv/bin/ebay-shipper dashboard > /dev/null 2>&1 &`
- Add `DASHBOARD_PORT=8080` to .env (optional, defaults to 8080)

## Cowork Skill (Later)

A separate Cowork SOP/skill that SSHes to the Linux box and reads state files conversationally. Deferred — the dashboard is the priority.

## Non-Goals

- No authentication (local network only)
- No database (state files are the DB)
- No real-time websockets (30s polling is fine)
- No mobile app (responsive HTML works on phone browser)
- No multi-user / multi-tenant
