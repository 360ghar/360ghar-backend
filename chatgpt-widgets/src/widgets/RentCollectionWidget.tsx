/**
 * RentCollectionWidget - Track rent payments for property owners and agents.
 *
 * Tools:
 * - owner_rent_status: `charges` and `totals`
 * - agent_rent_list_due: charge rows under `items`, and `totals`
 * - owner_rent_history: payment rows under `items` (no `totals`)
 * - owner_rent_record_payment: the saved `payment`
 *
 * `amount_due`, `late_fee` and `balance` include the late fee that the daily job has not
 * assessed yet. Totals cover the full matching set, not the loaded page.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type {
  PaymentMethod,
  RentChargeRow,
  RentCollectionOutput,
  RentPaymentRow,
  RentTotals,
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
import { formatDateOnly, formatDateOnlyForApi, formatInstantDate } from '../utils/datetime';
import { formatRupees, formatRupeesCompact } from '../utils/format';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import {
  PAYMENT_METHOD_LABEL,
  PAYMENT_METHOD_ORDER,
  RENT_CHARGE_STATUS,
  enumKey,
  statusView,
  toneColor,
} from '../utils/status';
import { themeColors } from '../utils/theme';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

interface WidgetState {
  view: 'status' | 'record';
  selectedChargeId?: number;
}

type Row = RentChargeRow | RentPaymentRow;

const DATE_WITH_YEAR: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
const MONTH_ONLY: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long' };

function isChargeRow(row: Row): row is RentChargeRow {
  return 'billing_month' in row;
}

function isPaymentRow(row: Row): row is RentPaymentRow {
  return 'charge_id' in row;
}

/** `charges` (owner_rent_status), else `items` (agent_rent_list_due charges, owner_rent_history payments). */
function readCollection(payload: RentCollectionOutput): PagedView<Row> | null {
  const rows = payload.charges ?? payload.items;
  return rows ? { rows, page: readPage(payload) } : null;
}

function RentCollectionWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<RentCollectionOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  const sendMessage = useSendMessage();
  const [widgetState, setWidgetState] = useWidgetState<WidgetState>();
  const { rows, page, hasList, append, replace } = usePagedRows(data, readCollection);

  // Record payment form state
  const [amount, setAmount] = React.useState('');
  const [paymentDate, setPaymentDate] = React.useState(() => formatDateOnlyForApi(new Date()) ?? '');
  const [paymentMethod, setPaymentMethod] = React.useState<PaymentMethod>('bank_transfer');
  const [transactionId, setTransactionId] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  // The payment this widget saved, or the one a record-payment result carried.
  const [recorded, setRecorded] = React.useState<RentPaymentRow | null>(null);
  const [recordedDismissed, setRecordedDismissed] = React.useState(false);
  // The arguments of the last list call this widget made itself. Null: use the original call's.
  const [listArgs, setListArgs] = React.useState<Record<string, unknown> | null>(null);
  // Totals of the last list call this widget made itself. They cover the full set, so the newest wins.
  const [latestTotals, setLatestTotals] = React.useState<RentTotals | null>(null);

  const view = widgetState?.view || 'status';
  const selectedChargeId = widgetState?.selectedChargeId;

  if (!data) {
    return <LoadingNote text="Loading rent status..." />;
  }

  if (data.requires_auth) {
    return <LoginRequired message="Please log in to view rent collection status." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'Failed to load rent status'} />;
  }

  const charges = rows.filter(isChargeRow);
  const payments = rows.filter(isPaymentRow);
  // Only charge lists carry totals. A list of payment rows without them is the payment history.
  const isCharges = charges.length > 0 || data.charges != null || data.totals != null || listArgs !== null;
  const savedPayment = recordedDismissed ? null : recorded ?? data.payment ?? null;
  const listBaseArgs = listArgs ?? (hasList ? toolInput : {});

  const handleBackToStatus = async () => {
    setRecorded(null);
    setRecordedDismissed(true);
    setWidgetState({ view: 'status' });
    setError(null);

    const result = await callTool<RentCollectionOutput>(
      ['owner_rent_status', 'agent_rent_list_due'],
      pageArgs(listBaseArgs),
    );
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      setListArgs(pageArgs(listBaseArgs));
      setLatestTotals(result.totals ?? null);
      replace(result);
    }
  };

  const handleLoadMore = async () => {
    if (loadingMore || !page.has_more || !page.next_cursor) return;
    setLoadingMore(true);
    setError(null);

    const names = isCharges
      ? (['owner_rent_status', 'agent_rent_list_due'] as const)
      : (['owner_rent_history'] as const);
    const result = await callTool<RentCollectionOutput>(names, pageArgs(listBaseArgs, page.next_cursor));
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      if (result.totals) setLatestTotals(result.totals);
      append(result);
    }
    setLoadingMore(false);
  };

  // Success after recording payment
  if (savedPayment) {
    const methodKey = enumKey(PAYMENT_METHOD_LABEL, savedPayment.payment_method);
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
            <p style={{ color: colors.textSecondary, marginBottom: 8 }}>
              {formatRupees(savedPayment.amount_paid)} on {formatInstantDate(savedPayment.paid_at, DATE_WITH_YEAR)}
              {methodKey ? ` by ${PAYMENT_METHOD_LABEL[methodKey]}` : ''}
            </p>
            {savedPayment.reference && (
              <p style={{ color: colors.textSecondary, fontSize: 13, marginBottom: 8 }}>
                Ref: {savedPayment.reference}
              </p>
            )}
            <div style={{ marginTop: 16 }}>
              <InlineError message={error} />
              <Button onClick={handleBackToStatus}>
                Back to Rent Status
              </Button>
            </div>
          </div>
        </Card>
      </div>
    );
  }

  // Record payment form
  if (view === 'record' && selectedChargeId) {
    const selectedCharge = charges.find((c) => c.id === selectedChargeId);

    const handleSubmit = async () => {
      const value = Number.parseFloat(amount);
      if (!Number.isFinite(value) || value <= 0) {
        setError('Please enter a valid amount');
        return;
      }
      if (!paymentDate) {
        setError('Please choose the payment date');
        return;
      }

      setIsSubmitting(true);
      setError(null);

      const result = await callTool<RentCollectionOutput>('owner_rent_record_payment', {
        rent_charge_id: selectedChargeId,
        amount: Math.round(value * 100) / 100,
        payment_date: paymentDate,
        payment_method: paymentMethod,
        ...(transactionId ? { transaction_id: transactionId } : {}),
      });

      if (isToolFailure(result)) {
        setError(toolFailureMessage(result));
      } else if (result.payment) {
        setRecordedDismissed(false);
        setRecorded(result.payment);
        setWidgetState({ view: 'status' });
      } else {
        setError('The payment was not saved. Check the rent status before you try again.');
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
            onClick={() => {
              setError(null);
              setWidgetState({ view: 'status' });
            }}
            aria-label="Back to rent status"
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
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {formatDateOnly(selectedCharge.billing_month, MONTH_ONLY)}
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 12, color: colors.textSecondary }}>Balance Due</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: colors.error }}>
                  {formatRupees(selectedCharge.balance)}
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
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder={selectedCharge ? String(selectedCharge.balance) : '0'}
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
            {PAYMENT_METHOD_ORDER.map((method) => (
              <button
                key={method}
                onClick={() => setPaymentMethod(method)}
                style={{
                  padding: 10,
                  borderRadius: 8,
                  border: `1px solid ${paymentMethod === method ? colors.primary : colors.border}`,
                  backgroundColor: paymentMethod === method ? `${colors.primary}15` : colors.background,
                  color: colors.text,
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                {PAYMENT_METHOD_LABEL[method]}
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

        <InlineError message={error} />

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

  // Payment history (owner_rent_history)
  if (!isCharges) {
    return (
      <div style={{
        backgroundColor: colors.background,
        color: colors.text,
        minHeight: '100vh',
        padding: 16,
      }}>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>Payment History</h2>

        <InlineError message={error} />

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
            {payments.map((payment) => {
              const methodKey = enumKey(PAYMENT_METHOD_LABEL, payment.payment_method);
              return (
                <Card key={payment.id} padding="md">
                  <div style={{ fontSize: 15, fontWeight: 600, color: colors.success }}>
                    {formatRupees(payment.amount_paid)}
                  </div>
                  <div style={{ fontSize: 12, color: colors.textSecondary }}>
                    {formatInstantDate(payment.paid_at, DATE_WITH_YEAR)}
                    {methodKey ? ` • ${PAYMENT_METHOD_LABEL[methodKey]}` : ''}
                  </div>
                  {payment.reference && (
                    <div style={{ fontSize: 11, color: colors.textSecondary }}>
                      Ref: {payment.reference}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}

        <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loadingMore} onClick={handleLoadMore} />
      </div>
    );
  }

  // Status view
  const totals = latestTotals ?? data.totals ?? null;

  return (
    <div style={{
      backgroundColor: colors.background,
      color: colors.text,
      minHeight: '100vh',
      padding: 16,
    }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>Rent Collection</h2>

      {/* Summary Cards */}
      {totals && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 20 }}>
          <Card padding="md">
            <div style={{ fontSize: 12, color: colors.textSecondary }}>Outstanding</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: colors.error }}>
              {formatRupeesCompact(totals.total_due)}
            </div>
          </Card>
          <Card padding="md">
            <div style={{ fontSize: 12, color: colors.textSecondary }}>Collected</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: colors.success }}>
              {formatRupeesCompact(totals.total_paid)}
            </div>
          </Card>
          {(totals.overdue_count ?? 0) > 0 && (
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
      )}

      <InlineError message={error} />

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
          {charges.map((charge) => {
            const status = statusView(RENT_CHARGE_STATUS, charge.status);
            const statusColor = toneColor(status.tone, colors);
            return (
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
                      backgroundColor: `${statusColor}20`,
                      color: statusColor,
                      marginBottom: 4,
                    }}>
                      {status.label}
                    </span>
                    <div style={{ fontSize: 15, fontWeight: 600 }}>
                      {formatDateOnly(charge.billing_month, MONTH_ONLY)}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 12, color: colors.textSecondary }}>
                      Due: {formatDateOnly(charge.due_date, DATE_WITH_YEAR)}
                    </div>
                    {charge.late_fee > 0 && (
                      <div style={{ fontSize: 11, color: colors.error }}>
                        Includes {formatRupees(charge.late_fee)} late fee
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', gap: 16 }}>
                    <div>
                      <div style={{ fontSize: 11, color: colors.textSecondary }}>Amount</div>
                      <div style={{ fontSize: 14 }}>{formatRupeesCompact(charge.amount_due)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: colors.textSecondary }}>Paid</div>
                      <div style={{ fontSize: 14, color: colors.success }}>{formatRupeesCompact(charge.amount_paid)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: colors.textSecondary }}>Balance</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: colors.error }}>
                        {formatRupeesCompact(charge.balance)}
                      </div>
                    </div>
                  </div>

                  {charge.balance > 0 && (
                    <Button
                      size="sm"
                      onClick={() => {
                        setError(null);
                        setAmount(String(charge.balance));
                        setWidgetState({ view: 'record', selectedChargeId: charge.id });
                      }}
                    >
                      Record
                    </Button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <LoadMore hasMore={page.has_more && page.next_cursor !== null} loading={loadingMore} onClick={handleLoadMore} />

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

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<RentCollectionWidget />);
