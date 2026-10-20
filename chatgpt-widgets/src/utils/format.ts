/**
 * Number and text formatting. Money is a JSON number (rupees). A missing value shows a dash.
 */

const PLACEHOLDER = '-';

/** Whole rupees or paise, for example "₹1,500.30". Not compact. */
export function formatRupees(amount: number | null | undefined): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return PLACEHOLDER;
  return `₹${amount.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

/** Rupees with lakh and crore units for large sums, for example "₹1.20 Cr". */
export function formatRupeesCompact(amount: number | null | undefined): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return PLACEHOLDER;
  if (amount >= 10_000_000) return `₹${(amount / 10_000_000).toFixed(2)} Cr`;
  if (amount >= 100_000) return `₹${(amount / 100_000).toFixed(2)} L`;
  return `₹${amount.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

/** 1 -> "1st", 2 -> "2nd", 11 -> "11th". */
export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

/** A filter value for display: a list joins with commas. */
export function formatFilterValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => String(v)).join(', ');
  return String(value);
}
