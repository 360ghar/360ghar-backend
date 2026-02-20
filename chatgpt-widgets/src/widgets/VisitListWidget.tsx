/**
 * VisitListWidget - Displays user's scheduled property visits.
 *
 * Tool: visits.list
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage } from '../utils/bridge';
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

interface Visit {
  id: number;
  property_id: number;
  property?: PropertyData;
  scheduled_date: string;
  status: string;
  notes?: string;
  created_at?: string;
}

interface Counts {
  total: number;
  upcoming: number;
  completed: number;
  cancelled: number;
}

interface VisitListOutput {
  visits?: Visit[];
  total?: number;
  page?: number;
  limit?: number;
  total_pages?: number;
  counts?: Counts;
  error?: boolean;
  message?: string;
  requires_auth?: boolean;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-IN', {
    weekday: 'short',
    month: 'short',
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

function getStatusColor(status: string, colors: typeof themeColors.light): string {
  switch (status) {
    case 'scheduled':
    case 'confirmed':
      return colors.primary;
    case 'completed':
      return colors.success;
    case 'cancelled':
      return colors.error;
    case 'rescheduled':
      return colors.warning;
    default:
      return colors.textSecondary;
  }
}

function isUpcoming(dateStr: string): boolean {
  return new Date(dateStr) > new Date();
}

function VisitListWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<VisitListOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [filter, setFilter] = React.useState<'all' | 'upcoming' | 'completed' | 'cancelled'>('all');
  const [cancelling, setCancelling] = React.useState<number | null>(null);

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading visits...
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
          Please log in to view your property visits.
        </p>
        <Button onClick={() => sendMessage('Help me log in to 360Ghar')}>
          Log In
        </Button>
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.error }}>
        {data.message || 'Failed to load visits'}
      </div>
    );
  }

  const visits = data.visits || [];
  const counts = data.counts || { total: 0, upcoming: 0, completed: 0, cancelled: 0 };

  // Filter visits
  const filteredVisits = visits.filter((visit) => {
    if (filter === 'all') return true;
    if (filter === 'upcoming') return isUpcoming(visit.scheduled_date) && visit.status !== 'cancelled';
    if (filter === 'completed') return visit.status === 'completed';
    if (filter === 'cancelled') return visit.status === 'cancelled';
    return true;
  });

  const handleCancelVisit = async (visitId: number) => {
    setCancelling(visitId);
    try {
      await callTool('visits.cancel', { visit_id: visitId });
      // Refresh the list
      await callTool('visits.list', {});
    } finally {
      setCancelling(null);
    }
  };

  const handleViewProperty = (propertyId: number) => {
    sendMessage(`Show me details for property ${propertyId}`);
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      {/* Header */}
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>My Property Visits</h2>

      {/* Stats */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 8,
        marginBottom: 16,
      }}>
        {[
          { label: 'Total', value: counts.total, key: 'all' },
          { label: 'Upcoming', value: counts.upcoming, key: 'upcoming' },
          { label: 'Done', value: counts.completed, key: 'completed' },
          { label: 'Cancelled', value: counts.cancelled, key: 'cancelled' },
        ].map((stat) => (
          <button
            key={stat.key}
            onClick={() => setFilter(stat.key as any)}
            style={{
              padding: '12px 8px',
              backgroundColor: filter === stat.key ? colors.primary : colors.backgroundSecondary,
              color: filter === stat.key ? '#3D3829' : colors.text,
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 600 }}>{stat.value}</div>
            <div style={{ fontSize: 11 }}>{stat.label}</div>
          </button>
        ))}
      </div>

      {/* Visit List */}
      {filteredVisits.length === 0 ? (
        <div style={{
          textAlign: 'center',
          padding: 40,
          color: colors.textSecondary,
          backgroundColor: colors.backgroundSecondary,
          borderRadius: 12,
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📅</div>
          <p style={{ fontSize: 16, marginBottom: 8 }}>No visits found</p>
          <p style={{ fontSize: 14 }}>
            {filter === 'all'
              ? "You haven't scheduled any property visits yet."
              : `No ${filter} visits.`}
          </p>
          {filter === 'all' && (
            <Button
              onClick={() => sendMessage('Find properties near me')}
              style={{ marginTop: 16 }}
            >
              Browse Properties
            </Button>
          )}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filteredVisits.map((visit) => (
            <Card key={visit.id} padding="none" style={{ overflow: 'hidden' }}>
              <div style={{ display: 'flex' }}>
                {/* Property Image */}
                {visit.property?.main_image_url && (
                  <div
                    onClick={() => visit.property && handleViewProperty(visit.property.id)}
                    style={{
                      width: 100,
                      minHeight: 100,
                      backgroundColor: colors.backgroundSecondary,
                      cursor: 'pointer',
                    }}
                  >
                    <img
                      src={visit.property.main_image_url}
                      alt={visit.property.title}
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                      }}
                    />
                  </div>
                )}

                {/* Content */}
                <div style={{ flex: 1, padding: 12 }}>
                  {/* Status Badge */}
                  <span style={{
                    display: 'inline-block',
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 500,
                    textTransform: 'uppercase',
                    backgroundColor: `${getStatusColor(visit.status, colors)}20`,
                    color: getStatusColor(visit.status, colors),
                    marginBottom: 8,
                  }}>
                    {visit.status}
                  </span>

                  {/* Property Title */}
                  {visit.property && (
                    <h3
                      onClick={() => handleViewProperty(visit.property!.id)}
                      style={{
                        fontSize: 14,
                        fontWeight: 600,
                        marginBottom: 4,
                        cursor: 'pointer',
                      }}
                    >
                      {visit.property.title}
                    </h3>
                  )}

                  {/* Location */}
                  {visit.property && (
                    <p style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 8 }}>
                      {[visit.property.locality, visit.property.city].filter(Boolean).join(', ')}
                    </p>
                  )}

                  {/* Date/Time */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                    <span style={{ fontWeight: 500 }}>{formatDate(visit.scheduled_date)}</span>
                    <span style={{ color: colors.textSecondary }}>at</span>
                    <span style={{ fontWeight: 500 }}>{formatTime(visit.scheduled_date)}</span>
                  </div>

                  {/* Actions */}
                  {isUpcoming(visit.scheduled_date) && visit.status !== 'cancelled' && (
                    <div style={{ marginTop: 12 }}>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleCancelVisit(visit.id)}
                        loading={cancelling === visit.id}
                        style={{ color: colors.error }}
                      >
                        Cancel Visit
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {data.total_pages && data.total_pages > 1 && data.page && (
        <div style={{
          marginTop: 20,
          display: 'flex',
          justifyContent: 'center',
          gap: 8,
        }}>
          {data.page > 1 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => callTool('visits.list', { page: data.page! - 1 })}
            >
              Previous
            </Button>
          )}
          <span style={{ padding: '8px 12px', color: colors.textSecondary }}>
            Page {data.page} of {data.total_pages}
          </span>
          {data.page < data.total_pages && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => callTool('visits.list', { page: data.page! + 1 })}
            >
              Next
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<VisitListWidget />);
