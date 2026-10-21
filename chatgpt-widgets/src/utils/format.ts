/**
 * Number and text formatting. Money is a JSON number (rupees). A missing value shows a dash.
 */

const PLACEHOLDER = '-';

/** Whole rupees or paise, for example "₹1,500.30". Not compact. */
export function formatRupees(amount: number | null | undefined): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return PLACEHOLDER;
  return `₹${amount.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

/** 12345 -> "123.45". */
function hundredths(n: number): string {
  return `${Math.floor(n / 100)}.${String(n % 100).padStart(2, '0')}`;
}

/** Rupees with lakh and crore units for large sums, for example "₹1.20 Cr". */
export function formatRupeesCompact(amount: number | null | undefined): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return PLACEHOLDER;
  if (amount >= 100_000) {
    // Integer paise and integer division, so toFixed on a binary quotient cannot round a
    // value down (100500 is 1.01 L, not 1.00 L). Round half up to hundredths of a lakh.
    const paise = Math.round(amount * 100);
    const lakhHundredths = Math.floor((paise + 50_000) / 100_000);
    // 100.00 L is shown as 1.00 Cr, so the unit changes where the rounded lakh reaches 100.
    if (lakhHundredths >= 10_000) {
      return `₹${hundredths(Math.floor((paise + 5_000_000) / 10_000_000))} Cr`;
    }
    return `₹${hundredths(lakhHundredths)} L`;
  }
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
