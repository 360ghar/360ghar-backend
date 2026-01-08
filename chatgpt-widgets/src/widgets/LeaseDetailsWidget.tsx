/**
 * LeaseDetailsWidget - Displays tenant's current lease information.
 *
 * Tool: tenant.lease.current
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useSendMessage } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { ImageWithFallback } from '../components/common/ImageWithFallback';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

interface PropertyData {
  id: number;
  title: string;
  locality?: string;
  city?: string;
  full_address?: string;
  main_image_url?: string;
}

interface LeaseData {
  id: number;
  property_id: number;
  property?: PropertyData;
  start_date: string;
  end_date: string;
  monthly_rent: number;
  security_deposit?: number;
  status: string;
  payment_due_day?: number;
  rent_paid_through?: string;
  balance_due?: number;
  created_at?: string;
}

interface LeaseOutput {
  lease?: LeaseData;
  error?: boolean;
  code?: string;
  message?: string;
  requires_auth?: boolean;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function formatCurrency(amount?: number): string {
  if (!amount) return '₹0';
  return `₹${amount.toLocaleString('en-IN')}`;
}

function getDaysRemaining(endDate: string): number {
  const end = new Date(endDate);
  const today = new Date();
  const diff = end.getTime() - today.getTime();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
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

function LeaseDetailsWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<LeaseOutput>();
  const sendMessage = useSendMessage();

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading lease details...
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
          Please log in to view your lease details.
        </p>
        <Button onClick={() => sendMessage('Help me log in to 360Ghar')}>
          Log In
        </Button>
      </div>
    );
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
  const daysRemaining = getDaysRemaining(lease.end_date);
  const isExpiringSoon = daysRemaining <= 30 && daysRemaining > 0;

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
        backgroundColor: `${getStatusColor(lease.status, colors)}15`,
        borderRadius: 8,
        marginBottom: 16,
      }}>
        <span style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: getStatusColor(lease.status, colors),
        }} />
        <span style={{
          fontWeight: 500,
          textTransform: 'capitalize',
          color: getStatusColor(lease.status, colors),
        }}>
          {lease.status}
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
            <ImageWithFallback
              src={lease.property.main_image_url}
              alt={lease.property.title}
              style={{
                width: 100,
                height: 100,
                objectFit: 'cover',
              }}
            />
            <div style={{ padding: 12, flex: 1 }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                {lease.property.title}
              </h3>
              <p style={{ fontSize: 13, color: colors.textSecondary }}>
                {lease.property.full_address || [lease.property.locality, lease.property.city].filter(Boolean).join(', ')}
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
            <div style={{ fontSize: 14, fontWeight: 500 }}>{formatDate(lease.start_date)}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>End Date</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{formatDate(lease.end_date)}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Monthly Rent</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: colors.primary }}>
              {formatCurrency(lease.monthly_rent)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Security Deposit</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{formatCurrency(lease.security_deposit)}</div>
          </div>
        </div>
      </Card>

      {/* Payment Info */}
      <Card padding="md" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Payment Status</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {lease.payment_due_day && (
            <div>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Due Date</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{lease.payment_due_day}th of each month</div>
            </div>
          )}
          {lease.rent_paid_through && (
            <div>
              <div style={{ fontSize: 12, color: colors.textSecondary, marginBottom: 4 }}>Paid Through</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{formatDate(lease.rent_paid_through)}</div>
            </div>
          )}
          {lease.balance_due !== undefined && lease.balance_due > 0 && (
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 12, color: colors.error, marginBottom: 4 }}>Balance Due</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: colors.error }}>
                {formatCurrency(lease.balance_due)}
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

// Mount the widget with ErrorBoundary
const root = createRoot(document.getElementById('root')!);
root.render(
  <ErrorBoundary>
    <LeaseDetailsWidget />
  </ErrorBoundary>
);
