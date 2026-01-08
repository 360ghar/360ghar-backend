/**
 * RentCollectionWidget - Track rent payments for property owners.
 *
 * Tool: owner.rent.status, owner.rent.record_payment, owner.rent.history
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import { useToolOutput, useTheme, useCallTool, useSendMessage, useWidgetState } from '../utils/bridge';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

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

interface Totals {
  total_due: number;
  total_paid: number;
  overdue_count: number;
  charges_count: number;
}

interface RentStatusOutput {
  charges?: RentCharge[];
  totals?: Totals;
  page?: number;
  limit?: number;
  error?: boolean;
  message?: string;
  requires_auth?: boolean;
}

interface WidgetState {
  view: 'status' | 'record';
  selectedChargeId?: number;
}

const PAYMENT_METHODS = [
  { value: 'bank_transfer', label: 'Bank Transfer' },
  { value: 'upi', label: 'UPI' },
  { value: 'cash', label: 'Cash' },
  { value: 'cheque', label: 'Cheque' },
  { value: 'online', label: 'Online' },
];

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
  if (amount >= 100000) return `₹${(amount / 100000).toFixed(1)}L`;
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

function RentCollectionWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<RentStatusOutput>();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [widgetState, setWidgetState] = useWidgetState<WidgetState>();

  // Record payment form state
  const [amount, setAmount] = React.useState('');
  const [paymentDate, setPaymentDate] = React.useState(new Date().toISOString().split('T')[0]);
  const [paymentMethod, setPaymentMethod] = React.useState('bank_transfer');
  const [transactionId, setTransactionId] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState(false);

  const view = widgetState?.view || 'status';
  const selectedChargeId = widgetState?.selectedChargeId;

  if (!data) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: colors.textSecondary }}>
        Loading rent status...
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
          Please log in to view rent collection status.
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
        {data.message || 'Failed to load rent status'}
      </div>
    );
  }

  // Success after recording payment
  if (success) {
    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        padding: 24,
      }}>
        <Card padding="lg">
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
            <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Payment Recorded</h2>
            <p style={{ color: colors.textSecondary, marginBottom: 24 }}>
              The payment has been recorded successfully.
            </p>
            <Button
              onClick={() => {
                setSuccess(false);
                setWidgetState({ view: 'status' });
                callTool('owner.rent.status', {});
              }}
            >
              Back to Rent Status
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // Record payment form
  if (view === 'record' && selectedChargeId) {
    const selectedCharge = data.charges?.find((c) => c.id === selectedChargeId);

    const handleSubmit = async () => {
      if (!amount || parseFloat(amount) <= 0) {
        setError('Please enter a valid amount');
        return;
      }

      setIsSubmitting(true);
      setError(null);

      try {
        const result = await callTool('owner.rent.record_payment', {
          rent_charge_id: selectedChargeId,
          amount: parseFloat(amount),
          payment_date: paymentDate,
          payment_method: paymentMethod,
          transaction_id: transactionId || undefined,
        });

        if (result && !result.error) {
          setSuccess(true);
        } else {
          setError(result?.message || 'Failed to record payment');
        }
      } catch (err) {
        setError('An error occurred while recording the payment');
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
            onClick={() => setWidgetState({ view: 'status' })}
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
          <h2 style={{ fontSize: 20, fontWeight: 600 }}>Record Payment</h2>
        </div>

        {/* Charge Info */}
        {selectedCharge && (
          <Card padding="md" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Billing Month</div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{formatMonth(selectedCharge.billing_month)}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Balance Due</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: colors.error }}>
                  {formatCurrency(selectedCharge.balance)}
                </div>
              </div>
            </div>
          </Card>
        )}

        {/* Amount */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Amount (₹) *
          </label>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder={selectedCharge ? selectedCharge.balance.toString() : '0'}
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

        {/* Payment Date */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Payment Date *
          </label>
          <input
            type="date"
            value={paymentDate}
            onChange={(e) => setPaymentDate(e.target.value)}
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

        {/* Payment Method */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Payment Method *
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {PAYMENT_METHODS.map((method) => (
              <button
                key={method.value}
                onClick={() => setPaymentMethod(method.value)}
                style={{
                  padding: 10,
                  borderRadius: 8,
                  border: `1px solid ${paymentMethod === method.value ? colors.primary : colors.border}`,
                  backgroundColor: paymentMethod === method.value ? `${colors.primary}15` : colors.background,
                  color: colors.text,
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                {method.label}
              </button>
            ))}
          </div>
        </div>

        {/* Transaction ID */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            Transaction ID (optional)
          </label>
          <input
            type="text"
            value={transactionId}
            onChange={(e) => setTransactionId(e.target.value)}
            placeholder="Reference number"
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

        {/* Error */}
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

        {/* Submit */}
        <Button
          onClick={handleSubmit}
          loading={isSubmitting}
          disabled={!amount}
          size="lg"
          style={{ width: '100%' }}
        >
          Record Payment
        </Button>
      </div>
    );
  }

  // Status view
  const charges = data.charges || [];
  const totals = data.totals || { total_due: 0, total_paid: 0, overdue_count: 0, charges_count: 0 };

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>Rent Collection</h2>

      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 20 }}>
        <Card padding="md">
          <div style={{ fontSize: 12, color: colors.textSecondary }}>Outstanding</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.error }}>
            {formatCurrency(totals.total_due)}
          </div>
        </Card>
        <Card padding="md">
          <div style={{ fontSize: 12, color: colors.textSecondary }}>Collected</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: colors.success }}>
            {formatCurrency(totals.total_paid)}
          </div>
        </Card>
        {totals.overdue_count > 0 && (
          <Card padding="md" style={{ gridColumn: '1 / -1', backgroundColor: `${colors.error}10` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 20 }}>⚠️</span>
              <span style={{ color: colors.error, fontWeight: 500 }}>
                {totals.overdue_count} overdue payment(s) require attention
              </span>
            </div>
          </Card>
        )}
      </div>

      {/* Rent Charges */}
      {charges.length === 0 ? (
        <div style={{
          textAlign: 'center',
          padding: 40,
          color: colors.textSecondary,
          backgroundColor: colors.backgroundSecondary,
          borderRadius: 12,
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>✅</div>
          <p style={{ fontSize: 16 }}>All rent is collected!</p>
          <p style={{ fontSize: 14 }}>No outstanding charges.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {charges.map((charge) => (
            <Card key={charge.id} padding="md">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
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
                    marginBottom: 4,
                  }}>
                    {charge.status}
                  </span>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>
                    {formatMonth(charge.billing_month)}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 12, color: colors.textSecondary }}>Due: {formatDate(charge.due_date)}</div>
                  {charge.late_fee && charge.late_fee > 0 && (
                    <div style={{ fontSize: 11, color: colors.error }}>+₹{charge.late_fee} late fee</div>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: colors.textSecondary }}>Amount</div>
                    <div style={{ fontSize: 14 }}>{formatCurrency(charge.amount_due)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: colors.textSecondary }}>Paid</div>
                    <div style={{ fontSize: 14, color: colors.success }}>{formatCurrency(charge.amount_paid)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: colors.textSecondary }}>Balance</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: colors.error }}>
                      {formatCurrency(charge.balance)}
                    </div>
                  </div>
                </div>

                {charge.balance > 0 && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setAmount(charge.balance.toString());
                      setWidgetState({ view: 'record', selectedChargeId: charge.id });
                    }}
                  >
                    Record
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* View History */}
      <div style={{ marginTop: 20, textAlign: 'center' }}>
        <Button
          variant="secondary"
          onClick={() => sendMessage('Show my rent payment history')}
        >
          View Payment History
        </Button>
      </div>
    </div>
  );
}

// Mount the widget with ErrorBoundary
const root = createRoot(document.getElementById('root')!);
root.render(
  <ErrorBoundary>
    <RentCollectionWidget />
  </ErrorBoundary>
);
