/**
 * Render checks. Each widget renders payloads shaped like the real tool results
 * (app/mcp/utils.py serializers, app/mcp/tool_ops, app/mcp/chatgpt tools) and the page shows
 * the values. Effects do not run in this renderer, so it covers the first render only.
 * Run: npm test
 */

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'widgets-render-'));

// ---------------------------------------------------------------------------
// Fixtures, in the shape of the backend serializers
// ---------------------------------------------------------------------------

const property = (over = {}) => ({
  id: 7, title: 'Sunrise Apartments', property_type: 'apartment', purpose: 'rent', status: 'available',
  city: 'Gurgaon', locality: 'Sector 54', full_address: '12 Golf Course Road',
  base_price: 9000000, price: 9000000, monthly_rent: 25000, daily_rate: 3500,
  bedrooms: 3, bathrooms: 2, area_sqft: 1450, is_available: true, is_managed: true, management_status: 'active',
  latitude: 28.4, longitude: 77.1, main_image_url: 'https://res.cloudinary.com/x/a.jpg', created_at: '2026-10-01T05:30:00Z',
  ...over,
});

const detail = (over = {}) => property({
  owner_phone: '+911234567890', owner_name: 'Owner', furnished_status: 'semi_furnished', age_years: 4,
  description: 'Bright flat', sub_locality: null, landmark: null, pincode: '122002', state: 'Haryana', country: 'India',
  price_per_sqft: 17.2, security_deposit: 50000, maintenance_charges: 2000, balconies: 2, parking_spaces: 1,
  floor_number: 5, total_floors: 12, max_occupancy: null, available_from: '2026-11-01', minimum_stay_days: 1,
  view_count: 4, like_count: 1, images: [{ url: 'https://res.cloudinary.com/x/a.jpg', caption: null }],
  amenities: [{ id: 1, name: 'Swimming Pool', icon: null, category: 'leisure' }], updated_at: '2026-10-02T05:30:00Z',
  ...over,
});

const propertyRef = { id: 7, title: 'Sunrise Apartments', locality: 'Sector 54', city: 'Gurgaon', main_image_url: null };

const visit = (over = {}) => ({
  id: 11, property_id: 7, property: propertyRef, scheduled_date: '2099-03-01T08:30:00Z', status: 'requested', notes: null,
  created_at: '2026-10-01T05:30:00Z', ...over,
});

const booking = (over = {}) => ({
  id: 21, booking_reference: 'BK-21', property_id: 7, property: property({ purpose: 'short_stay' }), status: 'confirmed',
  scheduled_date: '2099-03-01T00:00:00Z', user_id: 3, check_in_date: '2099-03-01T00:00:00Z', check_out_date: '2099-03-04T00:00:00Z',
  guests: 2, nights: 3, base_amount: 10500, taxes_amount: 0, service_charges: 0, discount_amount: 0, total_amount: 10500,
  booking_status: 'confirmed', payment_status: 'pending', payment_method: null, special_requests: null,
  cancellation_reason: null, cancellation_date: null, created_at: '2026-10-01T05:30:00Z', ...over,
});

const lease = (over = {}) => ({
  id: 5, property_id: 7, property: { ...propertyRef, full_address: '12 Golf Course Road' }, owner_id: 2, tenant_user_id: 9,
  tenant: { id: 9, display_name: 'Asha Verma', avatar_url: null }, start_date: '2026-01-01', end_date: '2026-12-31',
  monthly_rent: 25000, security_deposit: 50000, status: 'active', payment_due_day: 1, grace_period_days: 5,
  late_fee_amount: 500, late_fee_percentage: null, terms: null, notes: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...over,
});

const request = (over = {}) => ({
  id: 31, property_id: 7, lease_id: 5, reported_by_user_id: 9, tenant_user_id: 9, title: 'Leaking tap',
  description: 'Kitchen tap leaks', category: 'plumbing', priority: 'high', status: 'scheduled', request_status: 'work_order_created',
  work_order_status: 'assigned', estimated_cost: null, actual_cost: null, scheduled_date: '2026-10-20T04:30:00Z',
  completed_at: null, vendor_name: 'Ravi Plumbing', notes: null, created_at: '2026-10-10T05:30:00Z', updated_at: '2026-10-10T05:30:00Z',
  ...over,
});

const charge = (over = {}) => ({
  id: 41, lease_id: 5, property_id: 7, owner_id: 2, tenant_user_id: 9, billing_month: '2026-10-01', due_date: '2026-10-05',
  grace_end: '2026-10-10', amount_due: 25500, amount_paid: 10000, balance: 15500, late_fee: 500, status: 'partial', is_overdue: false,
  ...over,
});

const payment = (over = {}) => ({
  id: 51, charge_id: 41, lease_id: 5, property_id: 7, amount_paid: 10000, paid_at: '2026-10-06T00:00:00Z',
  payment_method: 'upi', status: 'settled', reference: 'UPI-123', notes: null, created_at: '2026-10-06T05:30:00Z', ...over,
});

const portfolio = { total_properties: 12, occupied: 9, vacant: 3, occupancy_rate: 75, total_monthly_income: 450000, monthly_rent_expected: 450000, open_maintenance_requests: 4 };

// widget -> [name, toolOutput, [text the page shows], [text it must not show]]
const CASES = {
  PropertySearchWidget: [
    ['search', { items: [property()], total: null, next_cursor: 'c1', has_more: true, limit: 20, filters_applied: { city: 'Gurgaon', property_type: ['apartment', 'house'] } },
      ['Sunrise Apartments', '₹25,000/mo', 'For Rent', 'city: Gurgaon', 'apartment, house', 'Load More', '1 Property Shown']],
    ['search with total', { items: [property()], total: 40, next_cursor: null, has_more: false, limit: 20, filters_applied: {} }, ['40 Properties Found'], ['Load More']],
    ['shortlist', { properties: [property({ purpose: 'short_stay' })], total: 1, next_cursor: null, has_more: false, limit: 20 }, ['Short Stay', '₹3,500/night']],
    ['empty', { items: [], total: 0, next_cursor: null, has_more: false, limit: 20, filters_applied: {} }, ['No properties found']],
    ['error', { error: true, message: 'Invalid purpose' }, ['Invalid purpose']],
    ['auth', { requires_auth: true, action: 'shortlist' }, ['Login Required']],
  ],
  PropertySwipeWidget: [
    ['feed', { properties: [property(), property({ id: 8, title: 'Second Home', purpose: 'buy' })], count: 2, is_personalized: false }, ['Sunrise Apartments', '1 / 2', '₹25,000/mo']],
    ['empty feed', { properties: [], count: 0, is_personalized: false }, ['No properties to show right now']],
  ],
  PropertyDetailsWidget: [
    ['detail', { property: detail() }, ['Sunrise Apartments', 'Semi-furnished', '4 years', 'Swimming Pool', '+911234567890', '₹25,000/month', 'For Rent'], ['Facing']],
    ['unknown furnishing', { property: detail({ furnished_status: 'luxury', purpose: 'lease' }) }, ['Price on request'], ['Luxury']],
    ['not found', { error: true, code: 'NOT_FOUND', property_id: 99 }, ['Property Not Found']],
  ],
  VisitSchedulerWidget: [
    ['visit', { visit: visit() }, ['Visit Requested', 'Requested', 'Sunrise Apartments']],
    ['booking', { booking: booking(), property: property({ title: 'Lake Villa' }) }, ['Booking Details', 'Check-in', 'Confirmed']],
    ['form', { property: propertyRef }, ['Schedule a Visit', 'Select Date']],
    ['error', { error: true, code: 'PAST_DATE' }, ['Choose a date and time in the future.']],
    ['nothing', { error: false }, ['Choose a property first']],
  ],
  VisitListWidget: [
    ['visits', { items: [visit(), visit({ id: 12, status: 'reschedule_suggested' })], next_cursor: 'v2', has_more: true, limit: 20,
      counts: { total: 5, upcoming: 3, completed: 1, cancelled: 1, requested: 1, confirmed: 1, reschedule_suggested: 1 } },
      ['Requested', 'Reschedule suggested', 'Cancel Visit', 'Load More']],
    ['bookings', { items: [booking()], total: null, limit: 20, next_cursor: null, has_more: false, counts: { total: 2, upcoming: 1, completed: 0, cancelled: 1 } },
      ['Confirmed', 'Cancel Booking'], ['Cancel Visit']],
    ['agent bookings, no counts', { items: [booking({ status: 'cancelled', booking_status: 'cancelled' })], total: null, limit: 20, next_cursor: null, has_more: false }, ['Cancelled']],
    ['one visit', { visit: visit({ status: 'confirmed' }) }, ['Confirmed', 'Cancel Visit']],
    ['unknown status', { items: [visit({ status: 'scheduled' })], next_cursor: null, has_more: false, limit: 20, counts: { total: 1, upcoming: 1, completed: 0, cancelled: 0 } }, ['Unknown'], ['Cancel Visit']],
  ],
  LeaseDetailsWidget: [
    ['lease', { lease: lease() }, ['Active', '₹25,000', '1st of each month', '5 days', '₹500', '1 January 2026', '31 December 2026'], ['Balance Due', 'Paid Through']],
    ['none', { lease: null, message: 'No active lease found.' }, ['No Active Lease', 'No active lease found.']],
  ],
  MaintenanceWidget: [
    ['list', { items: [request()], total: null, next_cursor: 'm2', has_more: true, limit: 20 }, ['Leaking tap', 'Scheduled', 'High', 'Ravi Plumbing', 'Load More']],
    ['created', { request: request({ status: 'open' }), message: 'Maintenance request created successfully' }, ['Request Submitted', 'Plumbing', 'High']],
    ['empty', { items: [], total: 0, next_cursor: null, has_more: false, limit: 20 }, ['No maintenance requests']],
    ['unknown category', { request: request({ status: 'open', category: 'garden' }) }, ['Request Submitted', 'Leaking tap'], ['Other', 'garden']],
    ['error', { error: true, message: 'Maintenance service is down' }, ['Maintenance service is down'], ['Show My Requests']],
    ['error envelope', { ok: false, error: { code: 'FORBIDDEN', message: 'No access' }, message: 'No access' }, ['No access'], ['Show My Requests']],
    ['error without message', { error: true }, ['Failed to load maintenance requests'], ['Show My Requests']],
  ],
  OwnerDashboardWidget: [
    ['list', { items: [property({ has_active_lease: true, tenant_name: 'Asha Verma' }), property({ id: 8, purpose: 'buy', has_active_lease: false })], total: null, next_cursor: 'p2', has_more: true, limit: 20, stats: portfolio },
      ['12', '₹4.50 L', 'Open Maintenance', 'Asha Verma', '₹25,000/mo', '₹90.00 L', 'Load More']],
    ['dashboard', { dashboard: { total_properties: 5, occupied_properties: 3, vacant_properties: 2, under_maintenance_properties: 1, monthly_revenue_current: 120000, monthly_revenue_previous: 100000, outstanding_rent_total: 30000, upcoming_expenses_total: 1000 } },
      ['Collected This Month', '₹1.20 L', 'Outstanding Rent', 'Show My Properties'], ['No properties listed']],
    ['agent metrics', { metrics: { total_properties: 8, active_leases: 6, occupancy_rate: 75, open_maintenance_requests: 2, upcoming_bookings: 1, monthly_rent_expected: 300000 }, user_role: 'agent', scope: 'agent' }, ['₹3.00 L', 'Vacant']],
    ['agent stats', { stats: portfolio }, ['Open Maintenance']],
  ],
  LeaseManagementWidget: [
    ['list', { leases: [lease(), lease({ id: 6, status: 'expired', tenant: { id: 10, display_name: 'Ravi', avatar_url: null } })], count: 2, next_cursor: null, has_more: false, limit: 20, stats: { active_leases: 4, total_monthly_rent: 100000 } },
      ['Tenant: Asha Verma', 'Expired', '₹1.00 L', 'Terminate']],
    ['one lease', { lease: lease({ status: 'expiring_soon', end_date: '2099-01-01' }) }, ['Expiring soon', 'Tenant: Asha Verma'], ['Active Leases']],
  ],
  RentCollectionWidget: [
    ['owner status', { charges: [charge()], totals: { total_due: 15500, total_paid: 10000, overdue_count: 1, charges_count: 1 }, next_cursor: 'r2', has_more: true, limit: 20 },
      ['Outstanding', '₹15,500', '1 overdue payment(s)', 'Partial', 'Includes ₹500 late fee', 'Record', 'Load More']],
    ['agent due', { items: [charge({ status: 'overdue', is_overdue: true })], totals: { total_due: 15500, total_paid: 0, overdue_count: 1, charges_count: 1 }, next_cursor: null, has_more: false, limit: 20 }, ['Overdue', 'Record']],
    ['history', { items: [payment()], total: null, limit: 20, next_cursor: null, has_more: false }, ['Payment History', '₹10,000', 'UPI', 'Ref: UPI-123'], ['Rent Collection']],
    ['recorded', { payment: payment() }, ['Payment Recorded', '₹10,000', 'UPI']],
    ['all paid', { charges: [], totals: { total_due: 0, total_paid: 0, overdue_count: 0, charges_count: 0 }, next_cursor: null, has_more: false, limit: 20 }, ['All rent is collected!']],
  ],
  TenantRentWidget: [
    ['dues', { charges: [charge({ status: 'overdue' })], total_due: 15500, overdue_count: 1 }, ['₹15,500', '1 payment overdue', 'Overdue', 'Includes ₹500 late fee'], ['Pay Now']],
    ['caught up', { charges: [], total_due: 0 }, ['all caught up']],
    ['history', { items: [payment()], total: null, total_collected: 10000, next_cursor: 'h2', has_more: true, limit: 20 }, ['Total paid', '₹10,000', 'UPI', 'Ref: UPI-123', 'Paid', 'Load More']],
  ],
};

// ---------------------------------------------------------------------------
// Bundle each widget once, then render its cases
// ---------------------------------------------------------------------------

globalThis.document = { getElementById: () => ({}) };
globalThis.window = {
  openai: {},
  parent: null,
  matchMedia: () => ({ matches: false }),
  addEventListener() {},
  removeEventListener() {},
};
globalThis.window.parent = globalThis.window;

for (const [name, cases] of Object.entries(CASES)) {
  const outfile = path.join(tmp, `${name}.cjs`);
  await esbuild.build({
    entryPoints: [path.join(root, 'src/widgets', `${name}.tsx`)],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    outfile,
    jsx: 'automatic',
    alias: { 'react-dom/client': path.join(root, 'scripts/shims/react-dom-client.mjs') },
    define: { 'process.env.NODE_ENV': '"production"' },
    logLevel: 'silent',
  });
  await import(pathToFileURL(outfile).href);
  const render = globalThis.__renderWidget;

  for (const [label, output, mustShow, mustNotShow = []] of cases) {
    test(`${name}: ${label}`, () => {
      globalThis.window.openai = { toolOutput: output, toolInput: {}, toolResponseMetadata: null, widgetState: null, theme: 'light' };
      const html = render().replace(/<!-- -->/g, '');
      for (const text of mustShow) assert.ok(html.includes(text), `"${text}" is missing from ${name} (${label})`);
      for (const text of mustNotShow) assert.ok(!html.includes(text), `"${text}" must not show in ${name} (${label})`);
      assert.ok(!html.includes('NaN') && !html.includes('undefined') && !html.includes('[object Object]'), `${name} (${label}) shows an unformatted value`);
    });
  }
}
