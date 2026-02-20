/**
 * MaintenanceWidget - Submit and manage maintenance requests.
 *
 * Tool: tenant.maintenance.create, tenant.maintenance.list
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage, useWidgetState } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';

interface MaintenanceRequest {
  id: number;
  property_id: number;
  title: string;
  description: string;
  category: string;
  priority: string;
  status: string;
  scheduled_date?: string;
  vendor_name?: string;
  estimated_cost?: number;
  actual_cost?: number;
  created_at: string;
  completed_at?: string;
}

interface MaintenanceListOutput {
  items?: MaintenanceRequest[];
  total?: number;
  page?: number;
  limit?: number;
  total_pages?: number;
  error?: boolean;
  message?: string;
  requires_auth?: boolean;
}

interface MaintenanceCreateOutput {
  request?: MaintenanceRequest;
  error?: boolean;
  message?: string;
  requires_auth?: boolean;
}

interface WidgetState {
  view: 'list' | 'create';
  createdRequest?: MaintenanceRequest;
}

const CATEGORIES = [
  { value: 'plumbing', label: 'Plumbing', icon: '🔧' },
  { value: 'electrical', label: 'Electrical', icon: '⚡' },
  { value: 'hvac', label: 'HVAC/AC', icon: '❄️' },
  { value: 'appliance', label: 'Appliance', icon: '🔌' },
  { value: 'structural', label: 'Structural', icon: '🏗️' },
  { value: 'pest_control', label: 'Pest Control', icon: '🐜' },
  { value: 'cleaning', label: 'Cleaning', icon: '🧹' },
  { value: 'other', label: 'Other', icon: '📋' },
];

const PRIORITIES = [
  { value: 'low', label: 'Low', color: '#9E9888' },
  { value: 'medium', label: 'Medium', color: '#D4B56A' },
  { value: 'high', label: 'High', color: '#C99898' },
  { value: 'urgent', label: 'Urgent', color: '#B87878' },
];

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function getStatusColor(status: string, colors: typeof themeColors.light): string {
  switch (status) {
    case 'open':
      return colors.warning;
    case 'in_progress':
    case 'scheduled':
      return colors.primary;
    case 'completed':
      return colors.success;
    case 'cancelled':
      return colors.error;
    default:
      return colors.textSecondary;
  }
}

function getPriorityColor(priority: string): string {
  const p = PRIORITIES.find((pr) => pr.value === priority);
  return p?.color || '#9E9888';
}

function MaintenanceWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<MaintenanceListOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [widgetState, setWidgetState] = useWidgetState<WidgetState>();

  // Form state
  const [category, setCategory] = React.useState('');
  const [priority, setPriority] = React.useState('medium');
  const [title, setTitle] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const view = widgetState?.view || 'list';
  const createdRequest = widgetState?.createdRequest;

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
          Please log in to manage maintenance requests.
        </p>
        <Button onClick={() => sendMessage('Help me log in to 360Ghar')}>
          Log In
        </Button>
      </div>
    );
  }

  // Show success after creation
  if (createdRequest) {
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
              <span style={{
                display: 'inline-block',
                padding: '4px 8px',
                borderRadius: 4,
                fontSize: 12,
                backgroundColor: `${getPriorityColor(createdRequest.priority)}20`,
                color: getPriorityColor(createdRequest.priority),
                textTransform: 'uppercase',
                fontWeight: 500,
              }}>
                {createdRequest.priority}
              </span>
              <span style={{
                display: 'inline-block',
                padding: '4px 8px',
                borderRadius: 4,
                fontSize: 12,
                backgroundColor: colors.backgroundSecondary,
                marginLeft: 8,
              }}>
                {CATEGORIES.find((c) => c.value === createdRequest.category)?.label || createdRequest.category}
              </span>
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
              {createdRequest.title}
            </h3>
            <p style={{ fontSize: 14, color: colors.textSecondary }}>
              {createdRequest.description}
            </p>
          </div>

          <Button
            onClick={() => {
              setWidgetState({ view: 'list' });
              callTool('tenant.maintenance.list', {});
            }}
            style={{ width: '100%' }}
          >
            View All Requests
          </Button>
        </Card>
      </div>
    );
  }

  // Create form view
  if (view === 'create') {
    const handleSubmit = async () => {
      if (!category || !title || !description) {
        setError('Please fill in all required fields');
        return;
      }

      setIsSubmitting(true);
      setError(null);

      try {
        // We need to get property_id from the user's lease
        const result = await callTool('tenant.maintenance.create', {
          property_id: 1, // This would come from context
          title,
          description,
          category,
          priority,
        }) as MaintenanceCreateOutput;

        if (result && result.request) {
          setWidgetState({ view: 'list', createdRequest: result.request });
        } else {
          setError(result?.message || 'Failed to submit request');
        }
      } catch (err) {
        setError('An error occurred while submitting the request');
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
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
          <button
            onClick={() => setWidgetState({ view: 'list' })}
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

        {/* Category Selection */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Category *
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {CATEGORIES.map((cat) => (
              <button
                key={cat.value}
                onClick={() => setCategory(cat.value)}
                style={{
                  padding: 12,
                  borderRadius: 8,
                  border: `1px solid ${category === cat.value ? colors.primary : colors.border}`,
                  backgroundColor: category === cat.value ? `${colors.primary}15` : colors.background,
                  color: colors.text,
                  cursor: 'pointer',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: 20, marginBottom: 4 }}>{cat.icon}</div>
                <div style={{ fontSize: 11 }}>{cat.label}</div>
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
            {PRIORITIES.map((p) => (
              <button
                key={p.value}
                onClick={() => setPriority(p.value)}
                style={{
                  flex: 1,
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: `1px solid ${priority === p.value ? p.color : colors.border}`,
                  backgroundColor: priority === p.value ? `${p.color}15` : colors.background,
                  color: priority === p.value ? p.color : colors.text,
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {p.label}
              </button>
            ))}
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
          disabled={!category || !title || !description}
          size="lg"
          style={{ width: '100%' }}
        >
          Submit Request
        </Button>
      </div>
    );
  }

  // List view
  const requests = data.items || [];

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
          onClick={() => setWidgetState({ view: 'create' })}
        >
          + New
        </Button>
      </div>

      {requests.length === 0 ? (
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {requests.map((request) => (
            <Card key={request.id} padding="md">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 500,
                    textTransform: 'uppercase',
                    backgroundColor: `${getStatusColor(request.status, colors)}20`,
                    color: getStatusColor(request.status, colors),
                  }}>
                    {request.status.replace('_', ' ')}
                  </span>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    backgroundColor: `${getPriorityColor(request.priority)}20`,
                    color: getPriorityColor(request.priority),
                  }}>
                    {request.priority}
                  </span>
                </div>
                <span style={{ fontSize: 12, color: colors.textSecondary }}>
                  {formatDate(request.created_at)}
                </span>
              </div>

              <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                {CATEGORIES.find((c) => c.value === request.category)?.icon} {request.title}
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
                  <span style={{ fontWeight: 500 }}>{formatDate(request.scheduled_date)}</span>
                  {request.vendor_name && (
                    <span style={{ color: colors.textSecondary }}> with {request.vendor_name}</span>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<MaintenanceWidget />);
