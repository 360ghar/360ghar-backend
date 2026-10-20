/**
 * LeaseManagementWidget - Manage property leases for owners and agents.
 *
 * Tools: owner_leases_list and agent_leases_list (`leases` and `stats`), owner_leases_get (one `lease`).
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { LeaseManagementOutput, LeaseRow } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useSendMessage,
  useTheme,
  useToolInput,
  useToolOutput,
} from '../utils/bridge';
import { daysUntilDateOnly, formatDateOnly } from '../utils/datetime';
import { formatRupeesCompact } from '../utils/format';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import { ENDED_LEASE, LEASE_STATUS, OCCUPYING_LEASE, enumKey, statusView, toneColor } from '../utils/status';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

type Filter = 'all' | 'active' | 'ended';

/** `leases` from the list tools. owner_leases_get sends one `lease`. */
function readLeases(payload: LeaseManagementOutput): PagedView<LeaseRow> | null {
  if (payload.leases) return { rows: payload.leases, page: readPage(payload) };
  if (payload.lease) return { rows: [payload.lease], page: readPage({}) };
  return null;
}

function LeaseManagementWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<LeaseManagementOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [filter, setFilter] = React.useState<Filter>('all');
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { rows: leases, page, append } = usePagedRows(data, readLeases);

  if (!data) {
    return <LoadingNote text="Loading leases..." />;
  }

  if (data.requires_auth) {
    return <LoginRequired message="Please log in to manage your leases." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'Failed to load leases'} />;
  }

  // Portfolio stats come with the list tools. A single lease has none.
  const stats = data.stats ?? null;

  // Filter leases
  const filteredLeases = leases.filter((lease) => {
    if (filter === 'all') return true;
    const key = enumKey(LEASE_STATUS, lease.status);
    if (key === null) return false;
    return filter === 'active' ? OCCUPYING_LEASE.includes(key) : ENDED_LEASE.includes(key);
  });

  const handleViewLease = (leaseId: number) => {
    sendMessage(`Show me details for lease ${leaseId}`);
  };

  const handleTerminateLease = (leaseId: number) => {
    sendMessage(`I want to terminate lease ${leaseId}`);
  };

  const handleLoadMore = async () => {
    if (loadingMore || !page.has_more || !page.next_cursor) return;
    setLoadingMore(true);
    setError(null);

    const result = await callTool<LeaseManagementOutput>(
      ['owner_leases_list', 'agent_leases_list'],
      pageArgs(toolInput, page.next_cursor),
    );
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      append(result);
    }
    setLoadingMore(false);
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>Lease Management</h2>

      {/* Stats */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
          <Card padding="md">
            <div style={{ fontSize: 12, color: colors.textSecondary }}>Active Leases</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: colors.success }}>{stats.active_leases}</div>
          </Card>
          <Card padding="md">
            <div style={{ fontSize: 12, color: colors.textSecondary }}>Monthly Income</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: colors.primary }}>
              {formatRupeesCompact(stats.total_monthly_rent)}
            </div>
          </Card>
        </div>
      )}

      {/* Filter */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['all', 'active', 'ended'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '8px 16px',
              borderRadius: 20,
              border: 'none',
              backgroundColor: filter === f ? colors.primary : colors.backgroundSecondary,
              color: filter === f ? '#3D3829' : colors.text,
              fontSize: 13,
              fontWeight: 500,
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            {f}
          </button>
        ))}
      </div>

      <InlineError message={error} />

      {/* Lease List */}
      {filteredLeases.length === 0 ? (
        <div style={{
          textAlign: 'center',
          padding: 40,
          color: colors.textSecondary,
          backgroundColor: colors.backgroundSecondary,
          borderRadius: 12,
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📋</div>
          <p style={{ fontSize: 16 }}>No leases found</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filteredLeases.map((lease) => {
            const status = statusView(LEASE_STATUS, lease.status);
            const statusColor = toneColor(status.tone, colors);
            const daysRemaining = daysUntilDateOnly(lease.end_date);
            const isOccupying = status.key !== null && OCCUPYING_LEASE.some((k) => k === status.key);
            const isExpiringSoon = isOccupying && daysRemaining !== null && daysRemaining <= 30 && daysRemaining > 0;

            return (
              <Card key={lease.id} padding="none" style={{ overflow: 'hidden' }}>
                <div style={{ display: 'flex' }}>
                  {/* Property Image */}
                  {lease.property?.main_image_url && (
                    <img
                      src={lease.property.main_image_url}
                      alt={lease.property.title}
                      style={{
                        width: 100,
                        height: 120,
                        objectFit: 'cover',
                      }}
                    />
                  )}

                  {/* Content */}
                  <div style={{ flex: 1, padding: 12 }}>
                    {/* Status */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 500,
                        textTransform: 'uppercase',
                        backgroundColor: `${statusColor}20`,
                        color: statusColor,
                      }}>
                        {status.label}
                      </span>
                      {isExpiringSoon && (
                        <span style={{
                          fontSize: 11,
                          color: colors.warning,
                        }}>
                          Expires in {daysRemaining} days
                        </span>
                      )}
                    </div>

                    {/* Property */}
                    {lease.property && (
                      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>
                        {lease.property.title}
                      </h3>
                    )}

                    {/* Tenant: name only. Contact data reaches the owner, admins and the tenant. */}
                    {lease.tenant?.display_name && (
                      <p style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 8 }}>
                        Tenant: {lease.tenant.display_name}
                      </p>
                    )}

                    {/* Details */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ fontSize: 12, color: colors.textSecondary }}>
                        {formatDateOnly(lease.start_date)} - {formatDateOnly(lease.end_date)}
                      </div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: colors.primary }}>
                        {formatRupeesCompact(lease.monthly_rent)}/mo
                      </div>
                    </div>

                    {/* Actions */}
                    {isOccupying && (
                      <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleViewLease(lease.id)}
                        >
                          Details
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleTerminateLease(lease.id)}
                          style={{ color: colors.error }}
                        >
                          Terminate
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loadingMore} onClick={handleLoadMore} />
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<LeaseManagementWidget />);
