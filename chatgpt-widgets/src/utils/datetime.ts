/**
 * Date helpers.
 *
 * Wire rules: instants are UTC ISO strings with a Z suffix. Date-only fields are YYYY-MM-DD.
 * Parse an instant as UTC and convert to local time only to display it. Show a date-only
 * field as the calendar date it names, with no time zone shift.
 */

const OFFSET_OR_Z_SUFFIX = /([zZ]|[+-]\d{2}:\d{2})$/;
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

const padDatePart = (value: number): string => String(value).padStart(2, '0');

function normalizeServerTimestamp(value: string): string {
  const trimmed = value.trim();
  if (trimmed.includes('T') && !OFFSET_OR_Z_SUFFIX.test(trimmed)) {
    return `${trimmed}Z`;
  }
  return trimmed;
}

/** Parse an instant. A string without a UTC offset reads as UTC. Bad input gives null. */
export function parseServerTimestamp(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const parsed = new Date(normalizeServerTimestamp(value));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function localInputToServerTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;

  return parsed.toISOString();
}

export function formatDateOnlyForApi(value: string | Date | null | undefined): string | null {
  if (!value) return null;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (DATE_ONLY.test(trimmed)) {
      return trimmed;
    }
  }

  const parsed = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;

  return [
    parsed.getFullYear(),
    padDatePart(parsed.getMonth() + 1),
    padDatePart(parsed.getDate()),
  ].join('-');
}

/** Parse YYYY-MM-DD to the UTC midnight of that calendar date. Other input gives null. */
export function parseDateOnly(value: string | null | undefined): Date | null {
  if (!value) return null;
  const match = DATE_ONLY.exec(value.trim());
  if (!match) return null;
  const [, year, month, day] = match;
  // Date.UTC maps the years 0 to 99 to 1900 to 1999, so the year is set separately.
  const parsed = new Date(Date.UTC(2000, Number(month) - 1, Number(day)));
  parsed.setUTCFullYear(Number(year), Number(month) - 1, Number(day));
  if (Number.isNaN(parsed.getTime())) return null;
  // Date.UTC rolls 2026-02-31 into March. Reject a date that did not survive the round trip.
  if (
    parsed.getUTCFullYear() !== Number(year) ||
    parsed.getUTCMonth() !== Number(month) - 1 ||
    parsed.getUTCDate() !== Number(day)
  ) {
    return null;
  }
  return parsed;
}

const PLACEHOLDER = '-';

/** Show an instant as a local date, for example "Mon, 5 Oct". */
export function formatInstantDate(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' },
): string {
  const date = parseServerTimestamp(value);
  return date ? date.toLocaleDateString('en-IN', options) : PLACEHOLDER;
}

/** Show an instant as a local time, for example "02:30 pm". */
export function formatInstantTime(value: string | null | undefined): string {
  const date = parseServerTimestamp(value);
  return date ? date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : PLACEHOLDER;
}

/** Show a date-only field as its calendar date. No time zone shift. */
export function formatDateOnly(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' },
): string {
  const date = parseDateOnly(value);
  return date ? date.toLocaleDateString('en-IN', { ...options, timeZone: 'UTC' }) : PLACEHOLDER;
}

/** Whole days from today (local calendar date) to a date-only field. Negative when past. */
export function daysUntilDateOnly(value: string | null | undefined, now: Date = new Date()): number | null {
  const target = parseDateOnly(value);
  if (!target) return null;
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today) / 86_400_000);
}

/** True when an instant is later than now. Bad input gives false. */
export function isFutureInstant(value: string | null | undefined, now: Date = new Date()): boolean {
  const date = parseServerTimestamp(value);
  return date !== null && date.getTime() > now.getTime();
}
