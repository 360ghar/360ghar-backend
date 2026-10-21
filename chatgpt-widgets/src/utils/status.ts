/**
 * Labels and tones for the wire enums.
 *
 * Every table is `Record<EnumValue, ...>`, so the compiler fails when the backend enum
 * (openapi/openapi.json) gains or loses a value. A wire value that a table does not hold
 * maps to null: `enumKey()` returns null and `statusView()` shows a neutral "Unknown".
 * No unknown value falls back to a real value.
 */

import type {
  BookingStatus,
  FurnishingLevel,
  LeaseStatus,
  MaintenanceCategory,
  MaintenancePriorityLabel,
  MaintenanceStatusLabel,
  PaymentMethod,
  PropertyPurpose,
  RentChargeStatus,
  RentPaymentStatus,
  VisitStatus,
} from '../api/wire';
import type { WidgetThemeColors } from './theme';

/** The key of `table` that equals `raw`, else null. */
export function enumKey<K extends string>(table: Record<K, unknown>, raw: unknown): K | null {
  if (typeof raw !== 'string') return null;
  return Object.prototype.hasOwnProperty.call(table, raw) ? (raw as K) : null;
}

export type Tone = 'primary' | 'success' | 'warning' | 'error' | 'muted';

export function toneColor(tone: Tone, colors: WidgetThemeColors): string {
  switch (tone) {
    case 'primary':
      return colors.primary;
    case 'success':
      return colors.success;
    case 'warning':
      return colors.warning;
    case 'error':
      return colors.error;
    default:
      return colors.textSecondary;
  }
}

interface StatusEntry {
  label: string;
  tone: Tone;
}

export interface StatusView {
  /** The enum value, or null for a wire value the table does not hold. */
  key: string | null;
  label: string;
  tone: Tone;
}

export function statusView<K extends string>(
  table: Record<K, StatusEntry>,
  raw: unknown,
): StatusView {
  const key = enumKey(table, raw);
  if (key === null) return { key: null, label: 'Unknown', tone: 'muted' };
  return { key, label: table[key].label, tone: table[key].tone };
}

// ---------------------------------------------------------------------------
// Property
// ---------------------------------------------------------------------------

export const PURPOSE_LABEL = {
  buy: 'For Sale',
  rent: 'For Rent',
  short_stay: 'Short Stay',
} satisfies Record<PropertyPurpose, string>;

export function parsePurpose(raw: unknown): PropertyPurpose | null {
  return enumKey(PURPOSE_LABEL, raw);
}

export const FURNISHING_LABEL = {
  furnished: 'Furnished',
  semi_furnished: 'Semi-furnished',
  unfurnished: 'Unfurnished',
} satisfies Record<FurnishingLevel, string>;

// ---------------------------------------------------------------------------
// Visits and bookings
// ---------------------------------------------------------------------------

export const VISIT_STATUS = {
  requested: { label: 'Requested', tone: 'primary' },
  confirmed: { label: 'Confirmed', tone: 'primary' },
  completed: { label: 'Completed', tone: 'success' },
  cancelled: { label: 'Cancelled', tone: 'error' },
  reschedule_suggested: { label: 'Reschedule suggested', tone: 'warning' },
} satisfies Record<VisitStatus, StatusEntry>;

export const BOOKING_STATUS = {
  pending: { label: 'Pending', tone: 'warning' },
  confirmed: { label: 'Confirmed', tone: 'primary' },
  checked_in: { label: 'Checked in', tone: 'primary' },
  checked_out: { label: 'Checked out', tone: 'success' },
  cancelled: { label: 'Cancelled', tone: 'error' },
  completed: { label: 'Completed', tone: 'success' },
} satisfies Record<BookingStatus, StatusEntry>;

// ---------------------------------------------------------------------------
// Leases and rent
// ---------------------------------------------------------------------------

export const LEASE_STATUS = {
  draft: { label: 'Draft', tone: 'muted' },
  pending_signature: { label: 'Pending signature', tone: 'warning' },
  active: { label: 'Active', tone: 'success' },
  expiring_soon: { label: 'Expiring soon', tone: 'warning' },
  expired: { label: 'Expired', tone: 'error' },
  terminated: { label: 'Terminated', tone: 'error' },
  renewed: { label: 'Renewed', tone: 'muted' },
} satisfies Record<LeaseStatus, StatusEntry>;

/** A lease that occupies the property: active, or active and ending within 30 days. */
export const OCCUPYING_LEASE: readonly LeaseStatus[] = ['active', 'expiring_soon'];
/** A lease that has ended. */
export const ENDED_LEASE: readonly LeaseStatus[] = ['expired', 'terminated', 'renewed'];

export const RENT_CHARGE_STATUS = {
  pending: { label: 'Pending', tone: 'warning' },
  partial: { label: 'Partial', tone: 'primary' },
  paid: { label: 'Paid', tone: 'success' },
  overdue: { label: 'Overdue', tone: 'error' },
  waived: { label: 'Waived', tone: 'muted' },
} satisfies Record<RentChargeStatus, StatusEntry>;

export const RENT_PAYMENT_STATUS = {
  pending: { label: 'Pending', tone: 'warning' },
  settled: { label: 'Paid', tone: 'success' },
} satisfies Record<RentPaymentStatus, StatusEntry>;

export const PAYMENT_METHOD_LABEL = {
  bank_transfer: 'Bank Transfer',
  upi: 'UPI',
  cash: 'Cash',
  cheque: 'Cheque',
  online: 'Online',
  other: 'Other',
} satisfies Record<PaymentMethod, string>;

/** Methods in the order the record-payment form lists them. */
export const PAYMENT_METHOD_ORDER: readonly PaymentMethod[] = [
  'bank_transfer',
  'upi',
  'cash',
  'cheque',
  'online',
  'other',
];

// ---------------------------------------------------------------------------
// Maintenance
// ---------------------------------------------------------------------------

export const MAINTENANCE_STATUS = {
  open: { label: 'Open', tone: 'warning' },
  in_progress: { label: 'In progress', tone: 'primary' },
  scheduled: { label: 'Scheduled', tone: 'primary' },
  completed: { label: 'Completed', tone: 'success' },
  cancelled: { label: 'Cancelled', tone: 'error' },
} satisfies Record<MaintenanceStatusLabel, StatusEntry>;

export const MAINTENANCE_PRIORITY = {
  low: { label: 'Low', color: '#9E9888' },
  medium: { label: 'Medium', color: '#D4B56A' },
  high: { label: 'High', color: '#C99898' },
  urgent: { label: 'Urgent', color: '#B87878' },
} satisfies Record<MaintenancePriorityLabel, { label: string; color: string }>;

export const MAINTENANCE_CATEGORY = {
  plumbing: { label: 'Plumbing', icon: '🔧' },
  electrical: { label: 'Electrical', icon: '⚡' },
  hvac: { label: 'HVAC/AC', icon: '❄️' },
  appliance: { label: 'Appliance', icon: '🔌' },
  structural: { label: 'Structural', icon: '🏗️' },
  pest_control: { label: 'Pest Control', icon: '🐜' },
  cleaning: { label: 'Cleaning', icon: '🧹' },
  other: { label: 'Other', icon: '📋' },
} satisfies Record<MaintenanceCategory, { label: string; icon: string }>;

/** Category values in the order the create form lists them. */
export const MAINTENANCE_CATEGORY_ORDER: readonly MaintenanceCategory[] = [
  'plumbing',
  'electrical',
  'hvac',
  'appliance',
  'structural',
  'pest_control',
  'cleaning',
  'other',
];

export const MAINTENANCE_PRIORITY_ORDER: readonly MaintenancePriorityLabel[] = [
  'low',
  'medium',
  'high',
  'urgent',
];
