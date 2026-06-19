-- Track the Razorpay order created for a booking so that payment verification
-- can confirm the order belongs to the booking being marked paid.
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS razorpay_order_id varchar;

CREATE INDEX IF NOT EXISTS idx_bookings_razorpay_order_id
  ON public.bookings (razorpay_order_id)
  WHERE razorpay_order_id IS NOT NULL;
