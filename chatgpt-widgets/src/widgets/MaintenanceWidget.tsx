/**
 * MaintenanceWidget - Submit and manage maintenance requests.
 *
 * Tools: tenant_maintenance_list, tenant_maintenance_create, agent_maintenance_list.
 * The create form reads the tenant's lease (tenant_lease_current) for the property id.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type {
  LeaseDetailsOutput,
  MaintenanceCategory,
  MaintenanceOutput,
  MaintenancePriorityLabel,
  MaintenanceRow,
} from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useSendMessage,
  useTheme,
  useToolInput,
  useToolOutput,
  useWidgetState,
} from '../utils/bridge';
import { formatInstantDate } from '../utils/datetime';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import {
  MAINTENANCE_CATEGORY,
  MAINTENANCE_CATEGORY_ORDER,
  MAINTENANCE_PRIORITY,
  MAINTENANCE_PRIORITY_ORDER,
  MAINTENANCE_STATUS,
  enumKey,
  statusView,
  toneColor,
} from '../utils/status';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

interface WidgetState {
  view: 'list' | 'create';
  createdRequest?: MaintenanceRow;
}

/** The tenant's active lease, as far as the create form needs it. */
type LeaseState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'ready'; propertyId: number; title: string | null }
  | { status: 'error'; message: string };

const DATE_WITH_YEAR: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' };

function readMaintenance(payload: MaintenanceOutput): PagedView<MaintenanceRow> | null {
  return payload.items ? { rows: payload.items, page: readPage(payload) } : null;
}

function priorityColor(priority: string | null): string {
  const key = enumKey(MAINTENANCE_PRIORITY, priority);
  return key ? MAINTENANCE_PRIORITY[key].color : '#9E9888';
}

function MaintenanceWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<MaintenanceOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [widgetState, setWidgetState] = useWidgetState<WidgetState>();
  const { rows: requests, page, hasList, append, replace } = usePagedRows(data, readMaintenance);

  // Form state
  const [category, setCategory] = React.useState<MaintenanceCategory | ''>('');
  const [priority, setPriority] = React.useState<MaintenancePriorityLabel>('medium');
  const [title, setTitle] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [lease, setLease] = React.useState<LeaseState>({ status: 'idle' });
  const [createdDismissed, setCreatedDismissed] = React.useState(false);
  // The arguments of the last list call this widget made itself. Null: use the original call's.
  const [listArgs, setListArgs] = React.useState<Record<string, unknown> | null>(null);

  const view = widgetState?.view || 'list';
  // A create result without a list is the request just made. The host state holds it after a create here.
  const createdRequest = createdDismissed
    ? undefined
    : widgetState?.createdRequest ?? (data && !data.items ? data.request ?? undefined : undefined);

  const loadLease = React.useCallback(async () => {
    setLease({ status: 'loading' });
    const result = await callTool<LeaseDetailsOutput>('tenant_lease_current', {});
    if (isToolFailure(result)) {
      setLease({ status: 'error', message: toolFailureMessage(result) });
    } else if (result.lease?.property_id) {
      setLease({
        status: 'ready',
        propertyId: result.lease.property_id,
        title: result.lease.property?.title ?? null,
      });
    } else {
      setLease({ status: 'none' });
    }
  }, [callTool]);

  // The property id of a request comes from the tenant's lease, so read it when the form opens.
  React.useEffect(() => {
    if (view === 'create' && lease.status === 'idle') {
      void loadLease();
    }
  }, [view, lease.status, loadLease]);

  if (!data) {
    return <LoadingNote text="Loading..." />;
  }

  // Check for auth required
  if (data.requires_auth) {
    return <LoginRequired message="Please log in to manage maintenance requests." />;
  }

  // A failed list or create call: show its message, unless a created request or a list is on screen.
  if (data.error && !createdRequest && !hasList) {
    return <FullError message={data.message || 'Failed to load maintenance requests'} />;
  }

  /** Fetch the first page of the tenant's list and show it. */
  const showAllRequests = async () => {
    setError(null);
    setCreatedDismissed(true);
    setWidgetState({ view: 'list' });
    const result = await callTool<MaintenanceOutput>('tenant_maintenance_list', {});
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      setListArgs({});
      replace(result);
    }
  };

  // Show success after creation
  if (createdRequest) {
    const priorityKey = enumKey(MAINTENANCE_PRIORITY, createdRequest.priority);
    const categoryKey = enumKey(MAINTENANCE_CATEGORY, createdRequest.category);
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
            <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Request Submitted</h2>
            <p style={{ color: colors.textSecondary }}>
              Your maintenance request has been received.
            </p>
          </div>

          <div style={{
            backgroundColor: colors.backgroundSecondary,
            borderRadius: 12,
            padding: 16,
            marginBottom: 20,
          }}>
            <div style={{ marginBottom: 12 }}>
              {priorityKey && (
                <span style={{
                  display: 'inline-block',
                  padding: '4px 8px',
                  borderRadius: 4,
                  fontSize: 12,
                  backgroundColor: `${priorityColor(createdRequest.priority)}20`,
                  color: priorityColor(createdRequest.priority),
                  textTransform: 'uppercase',
                  fontWeight: 500,
                  marginRight: 8,
                }}>
                  {MAINTENANCE_PRIORITY[priorityKey].label}
                </span>
              )}
              {categoryKey && (
                <span style={{
                  display: 'inline-block',
                  padding: '4px 8px',
                  borderRadius: 4,
                  fontSize: 12,
                  backgroundColor: colors.backgroundSecondary,
                }}>
                  {MAINTENANCE_CATEGORY[categoryKey].label}
                </span>
              )}
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
              {createdRequest.title}
            </h3>
            <p style={{ fontSize: 14, color: colors.textSecondary }}>
              {createdRequest.description}
            </p>
          </div>

          <InlineError message={error} />
          <Button onClick={showAllRequests} style={{ width: '100%' }}>
            View All Requests
          </Button>
        </Card>
      </div>
    );
  }

  // Create form view
  if (view === 'create') {
    const handleSubmit = async () => {
      if (lease.status !== 'ready') {
        setError('You need an active lease to submit a request.');
        return;
      }
      if (!category || !title || !description) {
        setError('Please fill in all required fields');
        return;
      }

      setIsSubmitting(true);
      setError(null);

      const result = await callTool<MaintenanceOutput>('tenant_maintenance_create', {
        property_id: lease.propertyId,
        title,
        description,
        category,
        priority,
      });

      if (isToolFailure(result)) {
        setError(toolFailureMessage(result));
      } else if (result.request) {
        setCreatedDismissed(false);
        setWidgetState({ view: 'list', createdRequest: result.request });
      } else {
        setError('The request was not saved. Try again.');
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
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
          <button
            onClick={() => setWidgetState({ view: 'list' })}
            aria-label="Back to requests"
            style={{
              backgroundColor: 'transparent',
              border: 'none',
              fontSize: 20,
              cursor: 'pointer',
              color: colors.text,
              marginRight: 12,
            }}
          >
            ←
          </button>
          <h2 style={{ fontSize: 20, fontWeight: 600 }}>New Maintenance Request</h2>
        </div>

        {/* Property of the active lease */}
        <div style={{ marginBottom: 20, fontSize: 14 }}>
          {lease.status === 'loading' || lease.status === 'idle' ? (
            <span style={{ color: colors.textSecondary }}>Checking your lease...</span>
          ) : lease.status === 'ready' ? (
            <span>
              <span style={{ color: colors.textSecondary }}>Property: </span>
              <span style={{ fontWeight: 500 }}>{lease.title ?? `#${lease.propertyId}`}</span>
            </span>
          ) : lease.status === 'none' ? (
            <span style={{ color: colors.error }}>
              You need an active lease to submit a maintenance request.
            </span>
          ) : (
            <span style={{ color: colors.error }}>
              {lease.message}{' '}
              <button
                onClick={() => void loadLease()}
                style={{
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: colors.primary,
                  cursor: 'pointer',
                  fontSize: 14,
                  textDecoration: 'underline',
                }}
              >
                Try again
              </button>
            </span>
          )}
        </div>

        {/* Category Selection */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Category *
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {MAINTENANCE_CATEGORY_ORDER.map((value) => (
              <button
                key={value}
                onClick={() => setCategory(value)}
                style={{
                  padding: 12,
                  borderRadius: 8,
                  border: `1px solid ${category === value ? colors.primary : colors.border}`,
                  backgroundColor: category === value ? `${colors.primary}15` : colors.background,
                  color: colors.text,
                  cursor: 'pointer',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: 20, marginBottom: 4 }}>{MAINTENANCE_CATEGORY[value].icon}</div>
                <div style={{ fontSize: 11 }}>{MAINTENANCE_CATEGORY[value].label}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Priority Selection */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Priority
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            {MAINTENANCE_PRIORITY_ORDER.map((value) => {
              const { label, color } = MAINTENANCE_PRIORITY[value];
              return (
                <button
                  key={value}
                  onClick={() => setPriority(value)}
                  style={{
                    flex: 1,
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: `1px solid ${priority === value ? color : colors.border}`,
                    backgroundColor: priority === value ? `${color}15` : colors.background,
                    color: priority === value ? color : colors.text,
                    cursor: 'pointer',
                    fontSize: 13,
                    fontWeight: 500,
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Title */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Title *
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Brief description of the issue"
            style={{
              width: '100%',
              padding: '12px 16px',
              fontSize: 14,
              borderRadius: 8,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.background,
              color: colors.text,
            }}
          />
        </div>

        {/* Description */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Description *
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Provide more details about the issue, when it started, etc."
            style={{
              width: '100%',
              padding: '12px 16px',
              fontSize: 14,
              borderRadius: 8,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.background,
              color: colors.text,
              resize: 'vertical',
              minHeight: 100,
            }}
          />
        </div>

        <InlineError message={error} />

        {/* Submit Button */}
        <Button
          onClick={handleSubmit}
          loading={isSubmitting}
          disabled={!category || !title || !description || lease.status !== 'ready'}
          size="lg"
          style={{ width: '100%' }}
        >
          Submit Request
        </Button>
      </div>
    );
  }

  // List view. Rows come from state, so Load More appends the page the call returned.
  const handleLoadMore = async () => {
    if (loadingMore || !page.has_more || !page.next_cursor) return;
    setLoadingMore(true);
    setError(null);

    const baseArgs = listArgs ?? (data.items ? toolInput : {});
    const result = await callTool<MaintenanceOutput>(
      ['tenant_maintenance_list', 'agent_maintenance_list'],
      pageArgs(baseArgs, page.next_cursor),
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 600 }}>Maintenance Requests</h2>
        <Button
          size="sm"
          onClick={() => {
            setError(null);
            setWidgetState({ view: 'create' });
          }}
        >
          + New
        </Button>
      </div>

      <InlineError message={error} />

      {!hasList && (
        <div style={{ marginBottom: 16 }}>
          <Button variant="secondary" onClick={showAllRequests}>
            Show My Requests
          </Button>
        </div>
      )}

      {hasList && requests.length === 0 ? (
        <div style={{
          textAlign: 'center',
          padding: 40,
          color: colors.textSecondary,
          backgroundColor: colors.backgroundSecondary,
          borderRadius: 12,
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🔧</div>
          <p style={{ fontSize: 16, marginBottom: 8 }}>No maintenance requests</p>
          <p style={{ fontSize: 14, marginBottom: 20 }}>
            Submit a request when you need something fixed.
          </p>
          <Button onClick={() => setWidgetState({ view: 'create' })}>
            Submit Request
          </Button>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {requests.map((request) => {
              const status = statusView(MAINTENANCE_STATUS, request.status);
              const statusColor = toneColor(status.tone, colors);
              const priorityKey = enumKey(MAINTENANCE_PRIORITY, request.priority);
              const categoryKey = enumKey(MAINTENANCE_CATEGORY, request.category);

              return (
                <Card key={request.id} padding="md">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                    <div style={{ display: 'flex', gap: 8 }}>
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
                      {priorityKey && (
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontSize: 11,
                          backgroundColor: `${priorityColor(request.priority)}20`,
                          color: priorityColor(request.priority),
                        }}>
                          {MAINTENANCE_PRIORITY[priorityKey].label}
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 12, color: colors.textSecondary }}>
                      {formatInstantDate(request.created_at, DATE_WITH_YEAR)}
                    </span>
                  </div>

                  <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                    {categoryKey ? `${MAINTENANCE_CATEGORY[categoryKey].icon} ` : ''}{request.title}
                  </h3>
                  <p style={{
                    fontSize: 13,
                    color: colors.textSecondary,
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}>
                    {request.description}
                  </p>

                  {request.scheduled_date && (
                    <div style={{
                      marginTop: 12,
                      padding: 8,
                      backgroundColor: colors.backgroundSecondary,
                      borderRadius: 6,
                      fontSize: 13,
                    }}>
                      <span style={{ color: colors.textSecondary }}>Scheduled: </span>
                      <span style={{ fontWeight: 500 }}>{formatInstantDate(request.scheduled_date, DATE_WITH_YEAR)}</span>
                      {request.vendor_name && (
                        <span style={{ color: colors.textSecondary }}> with {request.vendor_name}</span>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>

          {/* Pagination */}
          <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loadingMore} onClick={handleLoadMore} />
        </>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<MaintenanceWidget />);
