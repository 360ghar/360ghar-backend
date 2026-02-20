/**
 * TenantRentWidget - View rent dues and payment history for tenants.
 *
 * Tool: tenant.rent.dues, tenant.rent.history
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';

interface RentCharge {
  id: number;
  lease_id: number;
  billing_month: string;
  due_date: string;
  amount_due: number;
  amount_paid: number;
  balance: number;
  status: string;
  late_fee?: number;
}

interface RentPayment {
  id: number;
  rent_charge_id: number;
  amount: number;
  payment_date: string;
  payment_method: string;
  transaction_id?: string;
  created_at?: string;
}

interface TenantRentOutput {
  charges?: RentCharge[];
  payments?: RentPayment[];
  total_due?: number;
  overdue_count?: number;
  total?: number;
  total_collected?: number;
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

function formatMonth(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', {
    year: 'numeric',
    month: 'long',
  });
}

function formatCurrency(amount: number): string {
  return `₹${amount.toLocaleString('en-IN')}`;
}

function getStatusColor(status: string, colors: typeof themeColors.light): string {
  switch (status) {
    case 'paid':
      return colors.success;
    case 'pending':
      return colors.warning;
    case 'partial':
      return colors.primary;
    case 'overdue':
      return colors.error;
    default:
      return colors.textSecondary;
  }
}

function isOverdue(dueDate: string): boolean {
  return new Date(dueDate) < new Date();
}

function TenantRentWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<TenantRentOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [view, setView] = React.useState<'dues' | 'history'>('dues');

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading rent information...
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
          Please log in to view your rent information.
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
        {data.message || 'Failed to load rent information'}
      </div>
    );
  }

  const charges = data.charges || [];
  const payments = data.payments || [];
  const totalDue = data.total_due || 0;
  const overdueCount = data.overdue_count || 0;

  const handleViewHistory = () => {
    setView('history');
    callTool('tenant.rent.history', {});
  };

  const handleViewDues = () => {
    setView('dues');
    callTool('tenant.rent.dues', {});
  };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>My Rent</h2>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button
          onClick={handleViewDues}
          style={{
            flex: 1,
            padding: '12px 16px',
            borderRadius: 8,
            border: 'none',
            backgroundColor: view === 'dues' ? colors.primary : colors.backgroundSecondary,
            color: view === 'dues' ? '#3D3829' : colors.text,
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          Current Dues
        </button>
        <button
          onClick={handleViewHistory}
          style={{
            flex: 1,
            padding: '12px 16px',
            borderRadius: 8,
            border: 'none',
            backgroundColor: view === 'history' ? colors.primary : colors.backgroundSecondary,
            color: view === 'history' ? '#3D3829' : colors.text,
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          Payment History
        </button>
      </div>

      {view === 'dues' ? (
        <>
          {/* Summary */}
          {totalDue > 0 ? (
            <Card padding="lg" style={{ marginBottom: 16, backgroundColor: `${colors.error}10` }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 4 }}>
                  Total Amount Due
                </div>
                <div style={{ fontSize: 32, fontWeight: 700, color: colors.error }}>
                  {formatCurrency(totalDue)}
                </div>
                {overdueCount > 0 && (
                  <div style={{
                    marginTop: 8,
                    padding: '4px 12px',
                    backgroundColor: colors.error,
                    color: '#F2EDE0',
                    borderRadius: 20,
                    fontSize: 12,
                    display: 'inline-block',
                  }}>
                    {overdueCount} payment{overdueCount > 1 ? 's' : ''} overdue!
                  </div>
                )}
              </div>
            </Card>
          ) : (
            <Card padding="lg" style={{ marginBottom: 16, backgroundColor: `${colors.success}10` }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 48, marginBottom: 8 }}>✅</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: colors.success }}>
                  You're all caught up!
                </div>
                <div style={{ fontSize: 14, color: colors.textSecondary }}>
                  No outstanding rent payments.
                </div>
              </div>
            </Card>
          )}

          {/* Charges List */}
          {charges.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {charges.map((charge) => (
                <Card key={charge.id} padding="md">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <span style={{
                        display: 'inline-block',
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 500,
                        textTransform: 'uppercase',
                        backgroundColor: `${getStatusColor(charge.status, colors)}20`,
                        color: getStatusColor(charge.status, colors),
                        marginBottom: 6,
                      }}>
                        {charge.status}
                      </span>
                      <div style={{ fontSize: 16, fontWeight: 600 }}>
                        {formatMonth(charge.billing_month)}
                      </div>
                      <div style={{ fontSize: 12, color: colors.textSecondary }}>
                        Due: {formatDate(charge.due_date)}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 20, fontWeight: 700, color: colors.error }}>
                        {formatCurrency(charge.balance)}
                      </div>
                      {charge.amount_paid > 0 && (
                        <div style={{ fontSize: 12, color: colors.success }}>
                          {formatCurrency(charge.amount_paid)} paid
                        </div>
                      )}
                      {charge.late_fee && charge.late_fee > 0 && (
                        <div style={{ fontSize: 11, color: colors.error }}>
                          +{formatCurrency(charge.late_fee)} late fee
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          {/* Pay Now CTA */}
          {totalDue > 0 && (
            <div style={{ marginTop: 20 }}>
              <Button
                size="lg"
                style={{ width: '100%' }}
                onClick={() => sendMessage('How can I pay my rent?')}
              >
                Pay Now
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          {/* Payment History */}
          {payments.length === 0 ? (
            <div style={{
              textAlign: 'center',
              padding: 40,
              color: colors.textSecondary,
              backgroundColor: colors.backgroundSecondary,
              borderRadius: 12,
            }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>📋</div>
              <p style={{ fontSize: 16 }}>No payment history</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {payments.map((payment) => (
                <Card key={payment.id} padding="md">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 600, color: colors.success }}>
                        {formatCurrency(payment.amount)}
                      </div>
                      <div style={{ fontSize: 12, color: colors.textSecondary }}>
                        {formatDate(payment.payment_date)} • {payment.payment_method}
                      </div>
                      {payment.transaction_id && (
                        <div style={{ fontSize: 11, color: colors.textSecondary }}>
                          Ref: {payment.transaction_id}
                        </div>
                      )}
                    </div>
                    <div style={{
                      padding: '4px 10px',
                      backgroundColor: `${colors.success}15`,
                      borderRadius: 20,
                      color: colors.success,
                      fontSize: 12,
                      fontWeight: 500,
                    }}>
                      Paid
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<TenantRentWidget />);
