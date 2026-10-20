/**
 * TenantRentWidget - View rent dues and payment history for tenants.
 *
 * Tools: tenant_rent_dues (`charges`, `total_due`, `overdue_count`),
 * tenant_rent_history (`items`, `total_collected`, cursor).
 *
 * The widget has no pay button: there is no tenant payment route. The owner or agent
 * records a payment.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import type { RentChargeRow, RentPaymentRow, TenantRentOutput } from '../api/wire';
import {
  isToolFailure,
  toolFailureMessage,
  useCallTool,
  useTheme,
  useToolInput,
  useToolOutput,
} from '../utils/bridge';
import { formatDateOnly, formatInstantDate } from '../utils/datetime';
import { formatRupees } from '../utils/format';
import { pageArgs, readPage, usePagedRows, type PagedView } from '../utils/paging';
import {
  PAYMENT_METHOD_LABEL,
  RENT_CHARGE_STATUS,
  RENT_PAYMENT_STATUS,
  enumKey,
  statusView,
  toneColor,
} from '../utils/status';
import { themeColors } from '../utils/theme';
import { Card } from '../components/common/Card';
import { FullError, InlineError, LoadMore, LoadingNote, LoginRequired } from '../components/common/Notices';

type View = 'dues' | 'history';

const DATE_WITH_YEAR: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
const MONTH_ONLY: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long' };

/** tenant_rent_dues sends `charges`. tenant_rent_history sends `items`. */
function isDues(payload: TenantRentOutput): boolean {
  return payload.charges != null;
}

function readHistory(payload: TenantRentOutput): PagedView<RentPaymentRow> | null {
  return payload.items ? { rows: payload.items, page: readPage(payload) } : null;
}

function TenantRentWidget() {
  const theme = useTheme();
  const colors = themeColors[theme];
  const data = useToolOutput<TenantRentOutput>();
  const toolInput = useToolInput();
  const callTool = useCallTool();
  // The tab the user chose. Null: the tab of the tool that produced the widget.
  const [chosenView, setChosenView] = React.useState<View | null>(null);
  const [fetchedDues, setFetchedDues] = React.useState<TenantRentOutput | null>(null);
  const [fetchedHistory, setFetchedHistory] = React.useState<TenantRentOutput | null>(null);
  const [loadingView, setLoadingView] = React.useState<View | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const dues = fetchedDues ?? (data && isDues(data) ? data : null);
  const historyOutput = fetchedHistory ?? (data && readHistory(data) ? data : null);
  const history = usePagedRows(historyOutput, readHistory);

  if (!data) {
    return <LoadingNote text="Loading rent information..." />;
  }

  if (data.requires_auth) {
    return <LoginRequired message="Please log in to view your rent information." />;
  }

  if (data.error) {
    return <FullError message={data.message || 'Failed to load rent information'} />;
  }

  const view: View = chosenView ?? (isDues(data) ? 'dues' : 'history');

  const showView = async (next: View) => {
    setChosenView(next);
    setError(null);
    const loaded = next === 'dues' ? dues : historyOutput;
    if (loaded) return;

    setLoadingView(next);
    const result = await callTool<TenantRentOutput>(
      next === 'dues' ? 'tenant_rent_dues' : 'tenant_rent_history',
      {},
    );
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else if (next === 'dues') {
      setFetchedDues(result);
    } else {
      setFetchedHistory(result);
    }
    setLoadingView(null);
  };

  const handleLoadMore = async () => {
    if (loadingMore || !history.page.has_more || !history.page.next_cursor) return;
    setLoadingMore(true);
    setError(null);

    // The original call's arguments apply only when tenant_rent_history made this widget.
    const baseArgs = !fetchedHistory && readHistory(data) ? toolInput : {};
    const result = await callTool<TenantRentOutput>(
      'tenant_rent_history',
      pageArgs(baseArgs, history.page.next_cursor),
    );
    if (isToolFailure(result)) {
      setError(toolFailureMessage(result));
    } else {
      history.append(result);
    }
    setLoadingMore(false);
  };

  const charges: RentChargeRow[] = dues?.charges ?? [];
  const totalDue = dues?.total_due ?? 0;
  const overdueCount = dues?.overdue_count ?? 0;
  const payments = history.rows;
  const totalCollected = (fetchedHistory ?? historyOutput)?.total_collected;

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
          onClick={() => showView('dues')}
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
          onClick={() => showView('history')}
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

      <InlineError message={error} />

      {loadingView === view ? (
        <LoadingNote text="Loading..." />
      ) : view === 'dues' ? (
        <>
          {/* Summary */}
          {totalDue > 0 ? (
            <Card padding="lg" style={{ marginBottom: 16, backgroundColor: `${colors.error}10` }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 14, color: colors.textSecondary, marginBottom: 4 }}>
                  Total Amount Due
                </div>
                <div style={{ fontSize: 32, fontWeight: 700, color: colors.error }}>
                  {formatRupees(totalDue)}
                </div>
                {overdueCount > 0 && (
                  <div style={{
                    marginTop: 8,
                    padding: '4px 12px',
                    backgroundColor: colors.error,
                    color: '#3D3829',
                    borderRadius: 20,
                    fontSize: 12,
                    fontWeight: 600,
                    display: 'inline-block',
                  }}>
                    {overdueCount} payment{overdueCount > 1 ? 's' : ''} overdue
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
              {charges.map((charge) => {
                const status = statusView(RENT_CHARGE_STATUS, charge.status);
                const statusColor = toneColor(status.tone, colors);
                return (
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
                          backgroundColor: `${statusColor}20`,
                          color: statusColor,
                          marginBottom: 6,
                        }}>
                          {status.label}
                        </span>
                        <div style={{ fontSize: 16, fontWeight: 600 }}>
                          {formatDateOnly(charge.billing_month, MONTH_ONLY)}
                        </div>
                        <div style={{ fontSize: 12, color: colors.textSecondary }}>
                          Due: {formatDateOnly(charge.due_date, DATE_WITH_YEAR)}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: 20, fontWeight: 700, color: colors.error }}>
                          {formatRupees(charge.balance)}
                        </div>
                        {charge.amount_paid > 0 && (
                          <div style={{ fontSize: 12, color: colors.success }}>
                            {formatRupees(charge.amount_paid)} paid
                          </div>
                        )}
                        {charge.late_fee > 0 && (
                          <div style={{ fontSize: 11, color: colors.error }}>
                            Includes {formatRupees(charge.late_fee)} late fee
                          </div>
                        )}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </>
      ) : (
        <>
          {/* Payment History */}
          {typeof totalCollected === 'number' && payments.length > 0 && (
            <div style={{ marginBottom: 12, fontSize: 14, color: colors.textSecondary }}>
              Total paid: <span style={{ fontWeight: 600, color: colors.success }}>{formatRupees(totalCollected)}</span>
            </div>
          )}
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
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {payments.map((payment) => {
                  const status = statusView(RENT_PAYMENT_STATUS, payment.status);
                  const statusColor = toneColor(status.tone, colors);
                  const methodKey = enumKey(PAYMENT_METHOD_LABEL, payment.payment_method);
                  return (
                    <Card key={payment.id} padding="md">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
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
                        </div>
                        <div style={{
                          padding: '4px 10px',
                          backgroundColor: `${statusColor}15`,
                          borderRadius: 20,
                          color: statusColor,
                          fontSize: 12,
                          fontWeight: 500,
                        }}>
                          {status.label}
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
              <LoadMore
                hasMore={history.page.has_more && history.page.next_cursor !== null}
                loading={loadingMore}
                onClick={handleLoadMore}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}

// Mount the widget
const root = createRoot(document.getElementById('root')!);
root.render(<TenantRentWidget />);
