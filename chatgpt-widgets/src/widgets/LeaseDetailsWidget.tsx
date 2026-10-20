/**
 * LeaseDetailsWidget - Displays tenant's current lease information.
 *
 * Tool: tenant_lease_current
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { LeaseDetailsOutput } from '../api/wire';
import { useSendMessage, useTheme, useToolOutput } from '../utils/bridge';
import { daysUntilDateOnly, formatDateOnly } from '../utils/datetime';
import { formatRupees, ordinal } from '../utils/format';
import { formatLocation } from '../utils/property';
import { LEASE_STATUS, statusView, toneColor } from '../utils/status';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { LoadingNote, LoginRequired } from '../components/common/Notices';

const LONG_DATE: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric' };

function LeaseDetailsWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<LeaseDetailsOutput>();
  const sendMessage = useSendMessage();

  if (!data) {
    return <LoadingNote text="Loading lease details..." />;
  }

  // Check for auth required
  if (data.requires_auth) {
    return <LoginRequired message="Please log in to view your lease details." />;
  }

  if (data.error || !data.lease) {
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
        <div style={{ fontSize: 48, marginBottom: 16 }}>📋</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>No Active Lease</h2>
        <p style={{ color: colors.textSecondary, marginBottom: 24 }}>
          {data.message || "You don't have an active lease at the moment."}
        </p>
        <Button onClick={() => sendMessage('Help me find rental properties')}>
          Browse Rentals
        </Button>
      </div>
    );
  }

  const lease = data.lease;
  const status = statusView(LEASE_STATUS, lease.status);
  const statusColor = toneColor(status.tone, colors);
  const daysRemaining = daysUntilDateOnly(lease.end_date);
  const isExpiringSoon = daysRemaining !== null && daysRemaining <= 30 && daysRemaining > 0;
  const hasLateFee = (lease.late_fee_amount ?? 0) > 0 || (lease.late_fee_percentage ?? 0) > 0;

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>Your Lease</h2>

      {/* Status Banner */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '12px 16px',
        backgroundColor: `${statusColor}15`,
        borderRadius: 8,
        marginBottom: 16,
      }}>
        <span style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: statusColor,
        }} />
        <span style={{
          fontWeight: 500,
          color: statusColor,
        }}>
          {status.label}
        </span>
        {isExpiringSoon && (
          <span style={{
            marginLeft: 'auto',
            fontSize: 13,
            color: colors.warning,
          }}>
            Expires in {daysRemaining} days
          </span>
        )}
      </div>

      {/* Property Card */}
      {lease.property && (
        <Card padding="none" style={{ marginBottom: 16, overflow: 'hidden' }}>
          <div style={{ display: 'flex' }}>
            {lease.property.main_image_url && (
              <img
                src={lease.property.main_image_url}
                alt={lease.property.title}
                style={{
                  width: 100,
                  height: 100,
                  objectFit: 'cover',
                }}
              />
            )}
            <div style={{ padding: 12, flex: 1 }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                {lease.property.title}
              </h3>
              <p style={{ fontSize: 13, color: colors.textSecondary }}>
                {lease.property.full_address || formatLocation(lease.property)}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Lease Details */}
      <Card padding="md" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Lease Terms</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Start Date</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{formatDateOnly(lease.start_date, LONG_DATE)}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>End Date</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{formatDateOnly(lease.end_date, LONG_DATE)}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Monthly Rent</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: colors.primary }}>
              {formatRupees(lease.monthly_rent)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Security Deposit</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{formatRupees(lease.security_deposit)}</div>
          </div>
        </div>
      </Card>

      {/* Payment Info */}
      <Card padding="md" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Payment Terms</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {lease.payment_due_day != null && (
            <div>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Due Date</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{ordinal(lease.payment_due_day)} of each month</div>
            </div>
          )}
          {lease.grace_period_days != null && (
            <div>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Grace Period</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>
                {lease.grace_period_days} {lease.grace_period_days === 1 ? 'day' : 'days'}
              </div>
            </div>
          )}
          {hasLateFee && (
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Late Fee</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>
                {/* A fixed amount wins over the percentage (app/services/pm/rent_rules.py). */}
                {(lease.late_fee_amount ?? 0) > 0
                  ? formatRupees(lease.late_fee_amount)
                  : `${lease.late_fee_percentage}% of rent`}
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: 12 }}>
        <Button
          onClick={() => sendMessage('Show my rent payment history')}
          variant="secondary"
          style={{ flex: 1 }}
        >
          Payment History
        </Button>
        <Button
          onClick={() => sendMessage('Submit a maintenance request')}
          style={{ flex: 1 }}
        >
          Report Issue
        </Button>
      </div>
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<LeaseDetailsWidget />);
