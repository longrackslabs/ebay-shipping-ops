# Schedule Pickup Fix

The dashboard "Schedule" button only advances the order state without actually scheduling a USPS pickup via EasyPost. This fixes that.

## Changes

### 1. `next_pickup_date()` in label_provider.py

New function: returns tomorrow's date, or Monday if tomorrow is Sunday. Used by `schedule_pickup()` instead of hardcoded `tomorrow`. Pacific timezone.

### 2. Dashboard advance calls `schedule_pickup()`

When `advance_order()` detects the transition is `packed` → `pickup_scheduled`, it:
- Creates an `EasyPostProvider` from config
- Calls `schedule_pickup()` with the order's `shipment_id`
- On success: saves EMC confirmation to `tracking_detail` on the order, advances state
- On failure: returns error, does NOT advance state

Dashboard already receives `config` dict — it has `easypost_api_key` and `from_*` fields.

### 3. CLI saves EMC to order state

`schedule_pickup_command()` saves the EMC confirmation to the order's `tracking_detail` field in state.json, same as the dashboard path.

### 4. Tests

- Test `next_pickup_date()`: weekday → tomorrow, Saturday → Monday, Sunday → Monday (but Sunday scheduling shouldn't happen in practice)
- Test dashboard advance from packed triggers pickup (mock EasyPost)
- Test CLI pickup saves tracking_detail
