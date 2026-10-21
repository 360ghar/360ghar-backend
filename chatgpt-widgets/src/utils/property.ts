/**
 * Price and label rules per listing purpose.
 *
 * The price field depends on the purpose:
 * - rent: monthly_rent, shown per month
 * - short_stay: nightly_rate, shown per night (the MCP property rows name it daily_rate)
 * - buy: base_price
 * A purpose the backend does not define gives no price. It never falls back to base_price.
 */

import type { PropertyPurpose } from '../api/wire';
import { formatRupeesCompact } from './format';
import { PURPOSE_LABEL, parsePurpose } from './status';

export interface PurposePriceFields {
  purpose: string | null;
  base_price: number | null;
  monthly_rent: number | null;
  daily_rate: number | null;
  nightly_rate?: number | null;
}

export interface PurposePrice {
  purpose: PropertyPurpose | null;
  /** The price for the purpose. Null when the field is empty, zero or the purpose is unknown. */
  amount: number | null;
  /** The unit after the amount: "/mo", "/night" or "". */
  unit: '/mo' | '/night' | '';
}

/** The price for a listing, chosen by its purpose. */
export function priceFor(property: PurposePriceFields): PurposePrice {
  const purpose = parsePurpose(property.purpose);
  let amount: number | null = null;
  let unit: PurposePrice['unit'] = '';

  switch (purpose) {
    case 'rent':
      amount = property.monthly_rent;
      unit = '/mo';
      break;
    case 'short_stay':
      amount = property.nightly_rate ?? property.daily_rate;
      unit = '/night';
      break;
    case 'buy':
      amount = property.base_price;
      break;
    default:
      break;
  }

  return { purpose, amount: amount ? amount : null, unit };
}

/** "₹1.20 Cr", "₹25,000/mo", "₹3,500/night", or "Price on request". */
export function formatPropertyPrice(property: PurposePriceFields, longUnit = false): string {
  const { amount, unit } = priceFor(property);
  if (amount === null) return 'Price on request';
  const suffix = longUnit && unit === '/mo' ? '/month' : unit;
  return `${formatRupeesCompact(amount)}${suffix}`;
}

/** "For Sale", "For Rent", "Short Stay", or null for an unknown purpose. */
export function purposeLabel(purpose: string | null): string | null {
  const key = parsePurpose(purpose);
  return key === null ? null : PURPOSE_LABEL[key];
}

/** "Locality, City" without empty parts. */
export function formatLocation(parts: { locality?: string | null; city?: string | null; state?: string | null }): string {
  return [parts.locality, parts.city, parts.state].filter(Boolean).join(', ');
}
