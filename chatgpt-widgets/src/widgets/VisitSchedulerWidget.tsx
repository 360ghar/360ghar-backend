/**
 * VisitSchedulerWidget - Schedule a property visit, or show the visit or booking just made.
 *
 * Tools: visits_schedule (sends `visit`), bookings_get (sends `booking` and `property`)
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { BookingRow, VisitRow, VisitSchedulerOutput, VisitStatus } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useRequestClose,
  useSendMessage,
  useTheme,
  useToolOutput,
} from '../utils/bridge';
import {
  formatDateOnlyForApi,
  formatInstantDate,
  formatInstantTime,
  localInputToServerTimestamp,
} from '../utils/datetime';
import { formatLocation } from '../utils/property';
import { BOOKING_STATUS, VISIT_STATUS, enumKey, statusView, toneColor } from '../utils/status';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { InlineError, LoadingNote, LoginRequired } from '../components/common/Notices';

/** Heading of the confirmation for each visit status. */
const VISIT_TITLE = {
  requested: 'Visit Requested',
  confirmed: 'Visit Confirmed',
  completed: 'Visit Completed',
  cancelled: 'Visit Cancelled',
  reschedule_suggested: 'New Time Suggested',
} satisfies Record<VisitStatus, string>;

const LONG_DATE: Intl.DateTimeFormatOptions = {
  weekday: 'long',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
};

function isBooking(row: VisitRow | BookingRow): row is BookingRow {
  return 'booking_reference' in row;
}

function VisitSchedulerWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<VisitSchedulerOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const requestClose = useRequestClose();

  const [selectedDate, setSelectedDate] = React.useState('');
  const [selectedTime, setSelectedTime] = React.useState('');
  const [notes, setNotes] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  // The visit that visits_schedule returned for the form below.
  const [scheduled, setScheduled] = React.useState<VisitRow | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Set minimum date to tomorrow
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const minDate = formatDateOnlyForApi(tomorrow) ?? '';

  // Available time slots
  const timeSlots = [
    '09:00', '10:00', '11:00', '12:00',
    '14:00', '15:00', '16:00', '17:00', '18:00',
  ];

  if (!data) {
    return <LoadingNote text="Loading..." />;
  }

  // Check for auth required
  if (data.requires_auth) {
    return <LoginRequired message="Please log in to schedule a property visit." />;
  }

  // The visit or booking to show: the one the form just saved, else the one the tool sent.
  const detail: VisitRow | BookingRow | null = scheduled ?? data.visit ?? data.booking ?? null;
  // A visit nests its property. bookings_get sends it next to the booking.
  const propertyInfo = detail?.property ?? data.property ?? null;

  // Show error
  if (data.error && !detail) {
    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
      }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>❌</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8, color: colors.error }}>
          {data.code === 'NOT_FOUND' ? 'Property Not Found' : 'Error'}
        </h2>
        <p style={{ color: colors.textSecondary }}>
          {data.message ?? toolFailureMessage({ error: true, code: data.code })}
        </p>
      </div>
    );
  }

  // Detail view: a visit or booking exists.
  if (detail) {
    const booking = isBooking(detail) ? detail : null;
    const status = booking
      ? statusView(BOOKING_STATUS, detail.status)
      : statusView(VISIT_STATUS, detail.status);
    const visitKey = booking ? null : enumKey(VISIT_STATUS, detail.status);

    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        padding: 24,
      }}>
        <Card padding="lg">
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>{booking ? '🎫' : '✅'}</div>
            <h2 style={{ fontSize: 22, fontWeight: 600, marginBottom: 4 }}>
              {booking ? 'Booking Details' : visitKey ? VISIT_TITLE[visitKey] : 'Visit Details'}
            </h2>
            <span style={{
              display: 'inline-block',
              padding: '2px 8px',
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 500,
              textTransform: 'uppercase',
              backgroundColor: `${toneColor(status.tone, colors)}20`,
              color: toneColor(status.tone, colors),
            }}>
              {status.label}
            </span>
          </div>

          <div style={{
            backgroundColor: colors.backgroundSecondary,
            borderRadius: 12,
            padding: 16,
            marginBottom: 20,
          }}>
            {propertyInfo && (
              <div style={{ marginBottom: 16 }}>
                <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                  {propertyInfo.title}
                </h3>
                <p style={{ fontSize: 14, color: colors.textSecondary }}>
                  {formatLocation(propertyInfo)}
                </p>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {booking ? (
                <>
                  <div>
                    <div style={{ fontSize: 12, color: colors.textSecondary }}>Check-in</div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>
                      {formatInstantDate(booking.check_in_date, LONG_DATE)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: colors.textSecondary }}>Check-out</div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>
                      {formatInstantDate(booking.check_out_date, LONG_DATE)}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <div style={{ fontSize: 12, color: colors.textSecondary }}>Date</div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>
                      {formatInstantDate(detail.scheduled_date, LONG_DATE)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: colors.textSecondary }}>Time</div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>
                      {formatInstantTime(detail.scheduled_date)}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 12 }}>
            <Button
              variant="secondary"
              onClick={() => sendMessage('Show me my upcoming visits')}
              style={{ flex: 1 }}
            >
              View All Visits
            </Button>
            <Button
              onClick={requestClose}
              style={{ flex: 1 }}
            >
              Done
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // No visit yet: the form needs a property.
  const property = data.property ?? null;

  if (!property) {
    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        padding: 24,
        textAlign: 'center',
      }}>
        <p style={{ color: colors.textSecondary, marginBottom: 16 }}>
          Choose a property first, then schedule a visit.
        </p>
        <Button onClick={() => sendMessage('Find properties near me')}>
          Browse Properties
        </Button>
      </div>
    );
  }

  const handleSubmit = async () => {
    if (!selectedDate || !selectedTime) {
      setError('Please select a date and time');
      return;
    }

    const scheduledDate = localInputToServerTimestamp(`${selectedDate}T${selectedTime}`);
    if (!scheduledDate) {
      setError('Please select a valid date and time');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const result = await callTool<VisitSchedulerOutput>('visits_schedule', {
      property_id: property.id,
      scheduled_date: scheduledDate,
      ...(notes ? { notes } : {}),
    });

    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else if (result.visit) {
      setScheduled(result.visit);
    } else {
      setError('The visit was not confirmed. Try again.');
    }
    setIsSubmitting(false);
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>Schedule a Visit</h2>

      {/* Property Preview */}
      <Card padding="md" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12 }}>
          {property.main_image_url && (
            <img
              src={property.main_image_url}
              alt={property.title}
              style={{
                width: 80,
                height: 80,
                borderRadius: 8,
                objectFit: 'cover',
              }}
            />
          )}
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>{property.title}</h3>
            <p style={{ fontSize: 14, color: colors.textSecondary }}>
              {formatLocation(property)}
            </p>
          </div>
        </div>
      </Card>

      {/* Date Selection */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
          Select Date
        </label>
        <input
          type="date"
          value={selectedDate}
          min={minDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          style={{
            width: '100%',
            padding: '12px 16px',
            fontSize: 16,
            borderRadius: 8,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.background,
            color: colors.text,
          }}
        />
      </div>

      {/* Time Selection */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
          Select Time
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {timeSlots.map((time) => (
            <button
              key={time}
              onClick={() => setSelectedTime(time)}
              style={{
                padding: '12px 8px',
                fontSize: 14,
                borderRadius: 8,
                border: `1px solid ${selectedTime === time ? colors.primary : colors.border}`,
                backgroundColor: selectedTime === time ? colors.primary : colors.background,
                color: selectedTime === time ? '#3D3829' : colors.text,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {time}
            </button>
          ))}
        </div>
      </div>

      {/* Notes */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
          Notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Any special requests or notes for the visit..."
          style={{
            width: '100%',
            padding: '12px 16px',
            fontSize: 14,
            borderRadius: 8,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.background,
            color: colors.text,
            resize: 'vertical',
            minHeight: 80,
          }}
        />
      </div>

      <InlineError message={error} />

      {/* Submit Button */}
      <Button
        onClick={handleSubmit}
        loading={isSubmitting}
        disabled={!selectedDate || !selectedTime}
        size="lg"
        style={{ width: '100%' }}
      >
        Schedule Visit
      </Button>
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<VisitSchedulerWidget />);
