/**
 * VisitSchedulerWidget - Schedule a property visit with date/time selection.
 *
 * Tool: visits.schedule
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage, useRequestClose } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';

interface PropertyData {
  id: number;
  title: string;
  locality?: string;
  city?: string;
  main_image_url?: string;
}

interface VisitData {
  id: number;
  property_id: number;
  property?: PropertyData;
  scheduled_date: string;
  status: string;
  notes?: string;
}

interface SchedulerOutput {
  visit?: VisitData;
  property?: PropertyData;
  error?: boolean;
  code?: string;
  message?: string;
  requires_auth?: boolean;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-IN', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function VisitSchedulerWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<SchedulerOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const requestClose = useRequestClose();

  const [selectedDate, setSelectedDate] = React.useState('');
  const [selectedTime, setSelectedTime] = React.useState('');
  const [notes, setNotes] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [success, setSuccess] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Set minimum date to tomorrow
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const minDate = tomorrow.toISOString().split('T')[0];

  // Available time slots
  const timeSlots = [
    '09:00', '10:00', '11:00', '12:00',
    '14:00', '15:00', '16:00', '17:00', '18:00',
  ];

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading...
      </div>
    );
  }

  // Check for auth required
  if (data.requires_auth) {
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
        <div style={{ fontSize: 48, marginBottom: 16 }}>🔐</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>Login Required</h2>
        <p style={{ color: colors.textSecondary, marginBottom: 24 }}>
          Please log in to schedule a property visit.
        </p>
        <Button onClick={() => sendMessage('Help me log in to 360Ghar')}>
          Log In
        </Button>
      </div>
    );
  }

  // Show error
  if (data.error && !success) {
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
        <p style={{ color: colors.textSecondary }}>{data.message}</p>
      </div>
    );
  }

  // Show success confirmation
  if (success && data.visit) {
    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        padding: 24,
      }}>
        <Card padding="lg">
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
            <h2 style={{ fontSize: 22, fontWeight: 600, marginBottom: 4 }}>Visit Scheduled!</h2>
            <p style={{ color: colors.textSecondary }}>Your property visit has been confirmed.</p>
          </div>

          <div style={{
            backgroundColor: colors.backgroundSecondary,
            borderRadius: 12,
            padding: 16,
            marginBottom: 20,
          }}>
            {data.visit.property && (
              <div style={{ marginBottom: 16 }}>
                <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                  {data.visit.property.title}
                </h3>
                <p style={{ fontSize: 14, color: colors.textSecondary }}>
                  {[data.visit.property.locality, data.visit.property.city].filter(Boolean).join(', ')}
                </p>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Date</div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {formatDate(data.visit.scheduled_date)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Time</div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {formatTime(data.visit.scheduled_date)}
                </div>
              </div>
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

  // Get property info from context if available
  const property = data.property;

  const handleSubmit = async () => {
    if (!selectedDate || !selectedTime || !property) {
      setError('Please select a date and time');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const scheduledDate = `${selectedDate}T${selectedTime}:00`;
      const result = await callTool('visits.schedule', {
        property_id: property.id,
        scheduled_date: scheduledDate,
        notes: notes || undefined,
      });

      if (result && !result.error) {
        setSuccess(true);
      } else {
        setError(result?.message || 'Failed to schedule visit');
      }
    } catch (err) {
      setError('An error occurred while scheduling the visit');
    } finally {
      setIsSubmitting(false);
    }
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
      {property && (
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
                {[property.locality, property.city].filter(Boolean).join(', ')}
              </p>
            </div>
          </div>
        </Card>
      )}

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

      {/* Error Message */}
      {error && (
        <div style={{
          padding: 12,
          backgroundColor: `${colors.error}20`,
          borderRadius: 8,
          marginBottom: 20,
          color: colors.error,
          fontSize: 14,
        }}>
          {error}
        </div>
      )}

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
