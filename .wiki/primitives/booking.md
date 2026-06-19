# Booking

Bookings power 360 Stays, the short-stay module. A booking reserves a property for a date range with a guest count and a priced breakdown. Bookings are distinct from visits (which are walk-throughs, not overnight stays) and from leases (which are long-term tenancy contracts).

Active contributors: Saksham, Ravi

## Model

File: `app/models/bookings.py`

The `Booking` table captures the full lifecycle of a short-stay reservation. Key columns:

- `booking_reference` - human-readable unique identifier shown to guests and hosts
- `user_id`, `property_id` - foreign keys with `ON DELETE CASCADE`
- `check_in_date`, `check_out_date`, `nights`, `guests` - the stay window
- Price breakdown: `base_amount`, `taxes_amount`, `service_charges`, `discount_amount`, `total_amount` - all `Numeric(10, 2)` for currency precision
- `booking_status` - `BookingStatus` enum (`pending`, `confirmed`, `checked_in`, `checked_out`, `cancelled`, `completed`)
- `payment_status` - `PaymentStatus` enum (`pending`, `partial`, `paid`, `refunded`, `failed`)
- `primary_guest_name`, `primary_guest_phone`, `primary_guest_email` - denormalized guest contact, since a booking may be made by a user on behalf of someone else
- `guest_details` - JSON blob for additional guests
- `actual_check_in`, `actual_check_out` - timestamps set when the guest physically arrives and leaves
- `early_check_in`, `late_check_out` - boolean flags for flexibility requests
- `cancellation_date`, `cancellation_reason`, `refund_amount` - cancellation audit trail
- `guest_rating`, `guest_review`, `host_rating`, `host_review` - two-way review system

## The overlapping bookings rule

This is a deliberate business rule and a common source of confusion. The same property can be booked by multiple people for the same or overlapping dates. There are no double-booking guards, no date-overlap conflict checks, and no DB exclusion constraints on bookings.

`check_availability` in `app/services/booking.py` only validates that the property exists and that the guest count fits `max_occupancy`. It does not check for conflicting bookings. This matches the platform's model: hosts manually confirm or decline each `pending` booking, and overlapping requests are treated as competing leads rather than conflicts.

See [background/pitfalls.md](../background/pitfalls.md) for why this matters and what not to "fix".

## Lifecycle

A booking moves through `pending` -> `confirmed` -> `checked_in` -> `checked_out` -> `completed`, with `cancelled` reachable from any pre-check-in state. Payment status evolves independently: a booking can be `confirmed` while `payment_status` is still `partial`. Refunds set `payment_status = refunded` and populate `refund_amount`.

## REST and MCP surfaces

The `/api/v1/bookings` router covers create, list, get, cancel, check availability, and pricing. The user MCP server exposes `bookings_create`, `bookings_list`, `bookings_get`, `bookings_cancel`, `bookings_check_availability`, and `bookings_get_pricing` tools.
