/**
 * VisitListWidget - Displays the user's property visits or bookings.
 *
 * Tools: visits_list, bookings_list, agent_bookings_list_all (all send `items` and, for the
 * first two, `counts`), visits_get (sends one `visit`). Cancel sends a chat message: visits_cancel
 * is not widget-accessible on the OpenAI host.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { BookingRow, VisitCounts, VisitListOutput, VisitListRow } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useSendMessage,
  useTheme,
  useToolInput,
  useToolOutput,
} from '../utils/bridge';
import { formatInstantDate, formatInstantTime, isFutureInstant } from '../utils/datetime';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import { formatLocation } from '../utils/property';
import { BOOKING_STATUS, VISIT_STATUS, statusView, toneColor } from '../utils/status';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

type Filter = 'all' | 'upcoming' | 'completed' | 'cancelled';

function isBooking(row: VisitListRow): row is BookingRow {
  return 'booking_reference' in row;
}

/** Rows and page of a list result, or of the single visit that visits_get sends. */
function readVisits(payload: VisitListOutput): PagedView<VisitListRow> | null {
  if (payload.items) return { rows: payload.items, page: readPage(payload) };
  if (payload.visit) return { rows: [payload.visit], page: readPage({}) };
  return null;
}

/** Counts of the loaded rows. Used only when the tool sent no `counts` (agent_bookings_list_all). */
function countRows(rows: VisitListRow[]): Required<Pick<VisitCounts, 'total' | 'upcoming' | 'completed' | 'cancelled'>> {
  let upcoming = 0;
  let completed = 0;
  let cancelledCount = 0;
  for (const row of rows) {
    const status = row.status;
    if (status === 'completed' || status === 'checked_out') completed += 1;
    else if (status === 'cancelled') cancelledCount += 1;
    else if (isFutureInstant(row.scheduled_date)) upcoming += 1;
  }
  return { total: rows.length, upcoming, completed, cancelled: cancelledCount };
}

function VisitListWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<VisitListOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [filter, setFilter] = React.useState<Filter>('all');
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { rows: visits, page, append } = usePagedRows(data, readVisits);

  if (!data) {
    return <LoadingNote text="Loading visits..." />;
  }

  // Check for auth required
  if (data.requires_auth) {
    return <LoginRequired message="Please log in to view your property visits." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'Failed to load visits'} />;
  }

  const counts = data.counts ?? countRows(visits);

  // Filter visits
  const filteredVisits = visits.filter((visit) => {
    const status = visit.status;
    if (filter === 'all') return true;
    if (filter === 'upcoming') {
      return isFutureInstant(visit.scheduled_date) && status !== 'cancelled' && status !== 'completed';
    }
    if (filter === 'completed') return status === 'completed' || status === 'checked_out';
    return status === 'cancelled';
  });

  // visits_cancel is not widget-accessible on the OpenAI host (no openai/widgetAccessible in its
  // _meta), so a widget call would fail there. Ask the model to cancel, as booking rows do.
  // Restore callTool('visits_cancel') when the backend opts the tool in (handoff, Open item 1).
  const handleCancelVisit = (visitId: number) => {
    sendMessage(`Cancel visit ${visitId}`);
  };

  const handleLoadMore = async () => {
    if (loadingMore || !page.has_more || !page.next_cursor) return;
    setLoadingMore(true);
    setError(null);

    // Booking rows come from bookings_list (/mcp) or agent_bookings_list_all (/mcp-admin).
    const names = visits.some(isBooking)
      ? (['bookings_list', 'agent_bookings_list_all'] as const)
      : (['visits_list'] as const);
    const result = await callTool<VisitListOutput>(names, pageArgs(toolInput, page.next_cursor));
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      append(result);
    }
    setLoadingMore(false);
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
        {([
          { label: 'Total', value: counts.total ?? 0, key: 'all' },
          { label: 'Upcoming', value: counts.upcoming ?? 0, key: 'upcoming' },
          { label: 'Done', value: counts.completed ?? 0, key: 'completed' },
          { label: 'Cancelled', value: counts.cancelled ?? 0, key: 'cancelled' },
        ] as const).map((stat) => (
          <button
            key={stat.key}
            onClick={() => setFilter(stat.key)}
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

      <InlineError message={error} />

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
          {filteredVisits.map((visit) => {
            const booking = isBooking(visit) ? visit : null;
            const rawStatus = visit.status;
            const status = booking
              ? statusView(BOOKING_STATUS, rawStatus)
              : statusView(VISIT_STATUS, rawStatus);
            const statusColor = toneColor(status.tone, colors);
            const property = visit.property;
            const canCancel =
              isFutureInstant(visit.scheduled_date) &&
              (booking
                ? status.key === 'pending' || status.key === 'confirmed'
                : status.key === 'requested' || status.key === 'confirmed' || status.key === 'reschedule_suggested');

            return (
              <Card key={`${booking ? 'booking' : 'visit'}-${visit.id}`} padding="none" style={{ overflow: 'hidden' }}>
                <div style={{ display: 'flex' }}>
                  {/* Property Image */}
                  {property?.main_image_url && (
                    <div
                      onClick={() => handleViewProperty(property.id)}
                      style={{
                        width: 100,
                        minHeight: 100,
                        backgroundColor: colors.backgroundSecondary,
                        cursor: 'pointer',
                      }}
                    >
                      <img
                        src={property.main_image_url}
                        alt={property.title}
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
                      backgroundColor: `${statusColor}20`,
                      color: statusColor,
                      marginBottom: 8,
                    }}>
                      {status.label}
                    </span>

                    {/* Property Title */}
                    {property && (
                      <h3
                        onClick={() => handleViewProperty(property.id)}
                        style={{
                          fontSize: 14,
                          fontWeight: 600,
                          marginBottom: 4,
                          cursor: 'pointer',
                        }}
                      >
                        {property.title}
                      </h3>
                    )}

                    {/* Location */}
                    {property && (
                      <p style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 8 }}>
                        {formatLocation(property)}
                      </p>
                    )}

                    {/* Date/Time */}
                    {booking ? (
                      <div style={{ fontSize: 13 }}>
                        <span style={{ fontWeight: 500 }}>{formatInstantDate(booking.check_in_date)}</span>
                        <span style={{ color: colors.textSecondary }}> to </span>
                        <span style={{ fontWeight: 500 }}>{formatInstantDate(booking.check_out_date)}</span>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                        <span style={{ fontWeight: 500 }}>{formatInstantDate(visit.scheduled_date)}</span>
                        <span style={{ color: colors.textSecondary }}>at</span>
                        <span style={{ fontWeight: 500 }}>{formatInstantTime(visit.scheduled_date)}</span>
                      </div>
                    )}

                    {/* Actions */}
                    {canCancel && (
                      <div style={{ marginTop: 12 }}>
                        {booking ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => sendMessage(`Cancel booking ${booking.id}`)}
                            style={{ color: colors.error }}
                          >
                            Cancel Booking
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleCancelVisit(visit.id)}
                            style={{ color: colors.error }}
                          >
                            Cancel Visit
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loadingMore} onClick={handleLoadMore} />
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<VisitListWidget />);
