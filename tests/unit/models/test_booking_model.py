"""
Tests for app.models.bookings module — Booking model.
"""


from app.models.bookings import Booking


class TestBookingModel:
    """Tests for Booking model field defaults and constraints."""

    def test_tablename(self):
        assert Booking.__tablename__ == "bookings"

    def test_booking_reference_is_unique(self):
        col = Booking.__table__.columns.booking_reference
        assert col.unique

    def test_booking_reference_is_indexed(self):
        col = Booking.__table__.columns.booking_reference
        assert col.index

    def test_has_required_columns(self):
        columns = {c.name for c in Booking.__table__.columns}
        required = {
            "id", "user_id", "property_id", "booking_reference",
            "check_in_date", "check_out_date", "nights", "guests",
            "base_amount", "taxes_amount", "service_charges",
            "discount_amount", "total_amount",
            "booking_status", "payment_status",
            "primary_guest_name", "primary_guest_phone", "primary_guest_email",
        }
        assert required.issubset(columns)

    def test_has_review_columns(self):
        columns = {c.name for c in Booking.__table__.columns}
        review_cols = {"guest_rating", "guest_review", "host_rating", "host_review"}
        assert review_cols.issubset(columns)

    def test_has_cancellation_columns(self):
        columns = {c.name for c in Booking.__table__.columns}
        cancel_cols = {"cancellation_date", "cancellation_reason", "refund_amount"}
        assert cancel_cols.issubset(columns)

    def test_has_payment_columns(self):
        columns = {c.name for c in Booking.__table__.columns}
        payment_cols = {"payment_method", "transaction_id", "payment_date"}
        assert payment_cols.issubset(columns)

    def test_default_early_check_in(self):
        assert Booking.early_check_in.default.arg is False

    def test_default_late_check_out(self):
        assert Booking.late_check_out.default.arg is False
