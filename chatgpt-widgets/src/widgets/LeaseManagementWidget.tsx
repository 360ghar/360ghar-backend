/**
 * LeaseManagementWidget - Manage property leases for owners.
 *
 * Tool: owner.leases.list, owner.leases.get
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

interface TenantData {
  id: number;
  name: string;
  phone?: string;
  email?: string;
}

interface Lease {
  id: number;
  property_id: number;
  property?: PropertyData;
  tenant_user_id?: number;
  tenant?: TenantData;
  start_date: string;
  end_date: string;
  monthly_rent: number;
  security_deposit?: number;
  payment_due_day?: number;
  status: string;
  rent_paid_through?: string;
  created_at?: string;
}

interface Stats {
  active_leases: number;
  total_monthly_rent: number;
}

interface LeaseListOutput {
  leases?: Lease[];
  total?: number;
  page?: number;
  limit?: number;
  stats?: Stats;
  error?: boolean;
  message?: string;
  requires_auth?: boolean;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function formatCurrency(amount?: number): string {
  if (!amount) return '₹0';
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
  return `₹${amount.toLocaleString('en-IN')}`;
}

function getStatusColor(status: string, colors: typeof themeColors.light): string {
  switch (status) {
    case 'active':
      return colors.success;
    case 'pending':
      return colors.warning;
    case 'expired':
    case 'terminated':
      return colors.error;
    default:
      return colors.textSecondary;
  }
}

function getDaysRemaining(endDate: string): number {
  const end = new Date(endDate);
  const today = new Date();
  return Math.ceil((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function LeaseManagementWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<LeaseListOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [filter, setFilter] = React.useState<'all' | 'active' | 'expired'>('all');

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading leases...
      </div>
    );
  }

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
          Please log in to manage your leases.
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
        {data.message || 'Failed to load leases'}
      </div>
    );
  }

  const leases = data.leases || [];
  const stats = data.stats || { active_leases: 0, total_monthly_rent: 0 };

  // Filter leases
  const filteredLeases = leases.filter((lease) => {
    if (filter === 'all') return true;
    if (filter === 'active') return lease.status === 'active';
    if (filter === 'expired') return lease.status === 'expired' || lease.status === 'terminated';
    return true;
  });

  const handleViewLease = (leaseId: number) => {
    sendMessage(`Show me details for lease ${leaseId}`);
  };

  const handleTerminateLease = (leaseId: number) => {
    sendMessage(`I want to terminate lease ${leaseId}`);
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
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <Card padding="md">
          <div style={{ fontSize: 12, color: colors.textSecondary }}>Active Leases</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.success }}>{stats.active_leases}</div>
        </Card>
        <Card padding="md">
          <div style={{ fontSize: 12, color: colors.textSecondary }}>Monthly Income</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.primary }}>
            {formatCurrency(stats.total_monthly_rent)}
          </div>
        </Card>
      </div>

      {/* Filter */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['all', 'active', 'expired'] as const).map((f) => (
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
            const daysRemaining = getDaysRemaining(lease.end_date);
            const isExpiringSoon = daysRemaining <= 30 && daysRemaining > 0 && lease.status === 'active';

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
                        backgroundColor: `${getStatusColor(lease.status, colors)}20`,
                        color: getStatusColor(lease.status, colors),
                      }}>
                        {lease.status}
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

                    {/* Tenant */}
                    {lease.tenant && (
                      <p style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 8 }}>
                        Tenant: {lease.tenant.name}
                      </p>
                    )}

                    {/* Details */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ fontSize: 12, color: colors.textSecondary }}>
                        {formatDate(lease.start_date)} - {formatDate(lease.end_date)}
                      </div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: colors.primary }}>
                        {formatCurrency(lease.monthly_rent)}/mo
                      </div>
                    </div>

                    {/* Actions */}
                    {lease.status === 'active' && (
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
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<LeaseManagementWidget />);
