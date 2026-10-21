/**
 * Browser checks. The built widgets (dist/*.html) run in headless Chrome with a fake host.
 * They cover what the render checks cannot: effects and clicks (Load More, cancel, create,
 * record payment, tabs, swipe) and both host protocols (window.openai and MCP Apps postMessage).
 *
 * Run: npm run build && PLAYWRIGHT_CORE=<path to playwright-core> CHROME_PATH=<path to Chrome> npm run test:browser
 * Without PLAYWRIGHT_CORE (or an installed playwright-core) and CHROME_PATH the checks are skipped.
 */

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { createRequire } from 'node:module';
import * as path from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const chromePath = process.env.CHROME_PATH;

let chromium = null;
try {
  chromium = createRequire(import.meta.url)(process.env.PLAYWRIGHT_CORE || 'playwright-core').chromium;
} catch {
  /* not installed */
}
const skip = !chromium || !chromePath ? 'set PLAYWRIGHT_CORE and CHROME_PATH to run the browser checks' : false;

let browser;
before(async () => {
  if (!skip) browser = await chromium.launch({ executablePath: chromePath, headless: true });
});
after(async () => {
  await browser?.close();
});

// ---------------------------------------------------------------------------
// Fixtures, in the shape of the backend serializers
// ---------------------------------------------------------------------------

const property = (over = {}) => ({
  id: 7, title: 'Sunrise Apartments', property_type: 'apartment', purpose: 'rent', status: 'available',
  city: 'Gurgaon', locality: 'Sector 54', full_address: '12 Golf Course Road', base_price: 9000000, price: 9000000,
  monthly_rent: 25000, daily_rate: 3500, bedrooms: 3, bathrooms: 2, area_sqft: 1450, is_available: true, is_managed: true,
  management_status: 'active', latitude: 28.4, longitude: 77.1, main_image_url: null, created_at: '2026-10-01T05:30:00Z',
  has_active_lease: true, tenant_name: 'Asha', ...over,
});
const ref = { id: 7, title: 'Sunrise Apartments', locality: 'Sector 54', city: 'Gurgaon', main_image_url: null };
const visit = (over = {}) => ({
  id: 11, property_id: 7, property: ref, scheduled_date: '2099-03-01T08:30:00Z', status: 'requested', notes: null,
  created_at: '2026-10-01T05:30:00Z', ...over,
});
const booking = (id) => ({
  id, booking_reference: `BK-${id}`, property_id: 7, property: property({ purpose: 'short_stay' }), status: 'confirmed',
  scheduled_date: '2099-03-01T00:00:00Z', user_id: 3, check_in_date: '2099-03-01T00:00:00Z', check_out_date: '2099-03-04T00:00:00Z',
  booking_status: 'confirmed',
});
const lease = (over = {}) => ({
  id: 5, property_id: 7, property: ref, owner_id: 2, tenant_user_id: 9, tenant: { id: 9, display_name: 'Asha Verma', avatar_url: null },
  start_date: '2026-01-01', end_date: '2026-12-31', monthly_rent: 25000, security_deposit: 50000, status: 'active',
  payment_due_day: 1, grace_period_days: 5, late_fee_amount: 500, late_fee_percentage: null, terms: null, notes: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...over,
});
const request = (over = {}) => ({
  id: 31, property_id: 7, lease_id: 5, title: 'Leaking tap', description: 'Kitchen tap leaks', category: 'plumbing', priority: 'high',
  status: 'open', request_status: 'open', work_order_status: null, estimated_cost: null, actual_cost: null, scheduled_date: null,
  completed_at: null, vendor_name: null, notes: null, created_at: '2026-10-10T05:30:00Z', updated_at: '2026-10-10T05:30:00Z', ...over,
});
const charge = (over = {}) => ({
  id: 41, lease_id: 5, property_id: 7, owner_id: 2, tenant_user_id: 9, billing_month: '2026-10-01', due_date: '2026-10-05',
  grace_end: '2026-10-10', amount_due: 25500, amount_paid: 10000, balance: 15500, late_fee: 500, status: 'partial', is_overdue: false, ...over,
});
const payment = (over = {}) => ({
  id: 51, charge_id: 41, lease_id: 5, property_id: 7, amount_paid: 10000, paid_at: '2026-10-06T00:00:00Z', payment_method: 'upi',
  status: 'settled', reference: 'UPI-123', notes: null, created_at: '2026-10-06T05:30:00Z', ...over,
});
const page = (over = {}) => ({ next_cursor: null, has_more: false, limit: 20, ...over });

// ---------------------------------------------------------------------------
// Hosts
// ---------------------------------------------------------------------------

/** window.openai host. `handlers` maps a tool name to (args, nth) => result. `{__throw}` rejects the call. */
async function openOpenAi(widget, { toolOutput, toolInput = {}, widgetState = null, handlers = {} }) {
  const context = await browser.newContext({ viewport: { width: 420, height: 900 }, timezoneId: 'America/Los_Angeles' });
  const tab = await context.newPage();
  tab.calls = [];
  tab.errors = [];
  tab.on('pageerror', (error) => tab.errors.push(error.message));
  await tab.exposeFunction('__callTool', async (name, args) => {
    tab.calls.push({ name, args });
    const handler = handlers[name];
    if (!handler) return { structuredContent: { error: true, message: `Unknown tool: ${name}` }, content: '' };
    const result = await handler(args, tab.calls.filter((call) => call.name === name).length);
    if (result?.__throw) throw new Error(result.__throw);
    // The host resolves with text content and no structuredContent (how a host may report an unknown tool).
    if (result?.__text) return { content: [{ type: 'text', text: result.__text }] };
    return { structuredContent: result, content: '' };
  });
  await tab.addInitScript(({ toolOutput, toolInput, widgetState }) => {
    const api = {
      toolOutput, toolInput, widgetState, theme: 'light', locale: 'en-US', displayMode: 'inline', maxHeight: 720, toolResponseMetadata: null,
      setWidgetState(next) {
        api.widgetState = next;
        window.dispatchEvent(new CustomEvent('openai:set_globals', { detail: { globals: { widgetState: next } } }));
      },
      callTool: (name, args) => window.__callTool(name, args),
      sendFollowUpMessage() {}, requestClose() {}, openExternal() {}, requestDisplayMode: async () => {},
    };
    window.openai = api;
  }, { toolOutput, toolInput, widgetState });
  await tab.goto(`file://${path.join(dist, `${widget}.html`)}`);
  await tab.waitForSelector('#root > *', { timeout: 5000 });
  return tab;
}

/** MCP Apps host: a sandboxed srcdoc iframe, the way the in-app wrapper loads a widget. */
async function openMcpApps(widget, { toolInput, toolOutput, onToolCall }) {
  const context = await browser.newContext({ viewport: { width: 420, height: 900 }, timezoneId: 'America/Los_Angeles' });
  const tab = await context.newPage();
  tab.errors = [];
  tab.on('pageerror', (error) => tab.errors.push(error.message));
  await tab.exposeFunction('__hostToolCall', (name, args) => onToolCall(name, args));
  await tab.setContent(`<!doctype html><body style="margin:0"><iframe id="w" sandbox="allow-scripts" style="width:420px;height:880px;border:0"></iframe>
<script>
window.__input = ${JSON.stringify(toolInput)}; window.__output = ${JSON.stringify(toolOutput)};
const frame = document.getElementById('w');
const post = (message) => frame.contentWindow.postMessage(message, '*');
window.addEventListener('message', async (event) => {
  const d = event.data;
  if (event.source !== frame.contentWindow || !d || d.jsonrpc !== '2.0') return;
  if (d.method === 'ui/initialize') {
    post({ jsonrpc: '2.0', id: d.id, result: { protocolVersion: '2026-01-26', hostContext: { theme: 'light' } } });
    setTimeout(() => {
      post({ jsonrpc: '2.0', method: 'ui/notifications/tool-input', params: { arguments: window.__input } });
      post({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { structuredContent: window.__output, _meta: null } });
    }, 50);
  } else if (d.method === 'tools/call') {
    const r = await window.__hostToolCall(d.params.name, d.params.arguments);
    if (r && r.rpcError) post({ jsonrpc: '2.0', id: d.id, error: { code: -32601, message: r.rpcError } });
    else post({ jsonrpc: '2.0', id: d.id, result: { content: [{ type: 'text', text: JSON.stringify(r) }], structuredContent: r } });
  } else if (d.id != null && d.method) {
    post({ jsonrpc: '2.0', id: d.id, result: {} });
  }
});
</script>`);
  // The widget HTML holds a closing script tag, so it is set from outside the page script.
  await tab.evaluate((html) => { document.getElementById('w').srcdoc = html; }, fs.readFileSync(path.join(dist, `${widget}.html`), 'utf8'));
  return tab;
}

const press = (tab, name) => tab.getByRole('button', { name }).first().click();
const bodyText = (tab) => tab.evaluate(() => document.body.innerText);

// ---------------------------------------------------------------------------
// window.openai host
// ---------------------------------------------------------------------------

test('PropertySearch: Load More resends the call arguments with the cursor and appends the returned rows', { skip }, async () => {
  const tab = await openOpenAi('PropertySearchWidget', {
    toolInput: { city: 'Gurgaon', purpose: 'rent', limit: 1 },
    toolOutput: { items: [property()], total: null, ...page({ next_cursor: 'c1', has_more: true, limit: 1 }), filters_applied: { city: 'Gurgaon' } },
    handlers: { discovery_search: () => ({ items: [property({ id: 8, title: 'Second Flat' })], total: null, ...page({ limit: 1 }) }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Second Flat');
  assert.deepEqual(tab.calls, [{ name: 'discovery_search', args: { city: 'Gurgaon', purpose: 'rent', limit: 1, cursor: 'c1' } }]);
  const body = await bodyText(tab);
  assert.ok(body.includes('Sunrise Apartments') && !body.includes('Load More'));
  assert.deepEqual(tab.errors, []);
});

test('PropertySearch: with no host input, Load More resends filters_applied', { skip }, async () => {
  const filters = { city: 'Gurgaon', latitude: 28.4, longitude: 77.1, radius_km: 5, amenities: ['Gym'] };
  const tab = await openOpenAi('PropertySearchWidget', {
    toolOutput: { items: [property()], total: null, ...page({ next_cursor: 'c1', has_more: true }), filters_applied: filters },
    handlers: { discovery_search: () => ({ items: [], total: null, ...page() }) },
  });
  await press(tab, 'Load More');
  await tab.waitForFunction(() => !document.body.innerText.includes('Loading...'));
  assert.deepEqual(tab.calls[0].args, { ...filters, cursor: 'c1', limit: 20 });
});

test('PropertySearch: a shortlist pages through discovery_shortlist', { skip }, async () => {
  const tab = await openOpenAi('PropertySearchWidget', {
    toolOutput: { properties: [property()], total: 3, ...page({ next_cursor: 's1', has_more: true, limit: 1 }) },
    handlers: { discovery_shortlist: () => ({ properties: [property({ id: 9, title: 'Third' })], total: 3, ...page({ limit: 1 }) }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Third');
  assert.deepEqual(tab.calls, [{ name: 'discovery_shortlist', args: { cursor: 's1', limit: 1 } }]);
});

test('PropertySearch: a failed Load More shows the message for its code', { skip }, async () => {
  const tab = await openOpenAi('PropertySearchWidget', {
    toolInput: { city: 'X' },
    toolOutput: { items: [property()], total: null, ...page({ next_cursor: 'c1', has_more: true }) },
    handlers: { discovery_search: () => ({ error: true, code: 'INVALID_CURSOR' }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=The list changed');
});

test('PropertySwipe: like and pass record the swipe, advance the deck and keep the state', { skip }, async () => {
  const tab = await openOpenAi('PropertySwipeWidget', {
    toolInput: { purpose: 'rent' },
    toolOutput: { properties: [property(), property({ id: 8, title: 'Second Home', purpose: 'buy' })], count: 2 },
    handlers: { discovery_swipe: () => ({ recorded: true }) },
  });
  await press(tab, 'Like');
  await tab.waitForSelector('text=Second Home');
  assert.deepEqual(tab.calls[0], { name: 'discovery_swipe', args: { property_id: 7, is_liked: true } });
  assert.deepEqual(await tab.evaluate(() => window.openai.widgetState), { swipedIds: [7] });
  await press(tab, 'Pass');
  await tab.waitForSelector("text=You've seen all properties!");
});

test('PropertySwipe: a refused swipe keeps the card and shows the message', { skip }, async () => {
  const tab = await openOpenAi('PropertySwipeWidget', {
    toolOutput: { properties: [property()], count: 1 },
    handlers: { discovery_swipe: () => ({ error: true, code: 'SWIPE_NOT_ALLOWED' }) },
  });
  await press(tab, 'Like');
  await tab.waitForSelector('text=This property cannot be saved.');
  assert.ok((await bodyText(tab)).includes('Sunrise Apartments'));
});

test('PropertySwipe: Load More adds only properties the user has not swiped', { skip }, async () => {
  const tab = await openOpenAi('PropertySwipeWidget', {
    toolInput: { purpose: 'rent' },
    widgetState: { swipedIds: [7] },
    toolOutput: { properties: [property()], count: 1 },
    handlers: { discovery_feed: () => ({ properties: [property(), property({ id: 9, title: 'Fresh One' })], count: 2 }) },
  });
  await press(tab, 'Load More Properties');
  await tab.waitForSelector('text=Fresh One');
  assert.deepEqual(tab.calls, [{ name: 'discovery_feed', args: { purpose: 'rent' } }]);
});

test('VisitList: Cancel Visit sends a chat message, not a tool call (visits_cancel is not widget-accessible)', { skip }, async () => {
  const tab = await openOpenAi('VisitListWidget', {
    toolInput: { status: 'requested' },
    toolOutput: { items: [visit()], ...page(), counts: { total: 1, upcoming: 1, completed: 0, cancelled: 0 } },
  });
  await tab.evaluate(() => {
    window.__messages = [];
    window.openai.sendFollowUpMessage = ({ prompt }) => window.__messages.push(prompt);
  });
  await press(tab, 'Cancel Visit');
  await tab.waitForFunction(() => window.__messages.length === 1);
  assert.deepEqual(await tab.evaluate(() => window.__messages), ['Cancel visit 11']);
  assert.deepEqual(tab.calls, []);
});

test('VisitList: Load More pages visits_list with the cursor', { skip }, async () => {
  const tab = await openOpenAi('VisitListWidget', {
    toolOutput: { items: [visit()], ...page({ next_cursor: 'v2', has_more: true, limit: 1 }), counts: { total: 2, upcoming: 2, completed: 0, cancelled: 0 } },
    handlers: { visits_list: () => ({ items: [visit({ id: 12, status: 'confirmed' })], ...page({ limit: 1 }) }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=CONFIRMED');
  assert.deepEqual(tab.calls, [{ name: 'visits_list', args: { cursor: 'v2' } }]);
});

test('VisitList: booking rows page through bookings_list, then agent_bookings_list_all when the host does not know the first', { skip }, async () => {
  const tab = await openOpenAi('VisitListWidget', {
    toolOutput: { items: [booking(1)], ...page({ next_cursor: 'b2', has_more: true, limit: 1 }) },
    handlers: {
      bookings_list: () => ({ __throw: 'Unknown tool: bookings_list' }),
      agent_bookings_list_all: () => ({ items: [booking(2)], ...page({ limit: 1 }) }),
    },
  });
  await press(tab, 'Load More');
  await tab.waitForFunction(() => document.querySelectorAll('h3').length >= 2);
  assert.deepEqual(tab.calls.map((call) => call.name), ['bookings_list', 'agent_bookings_list_all']);
});

test('LeaseManagement: a host that resolves an unknown tool as text still falls back to agent_leases_list', { skip }, async () => {
  const stats = { active_leases: 2, total_monthly_rent: 50000 };
  const tab = await openOpenAi('LeaseManagementWidget', {
    toolInput: { status: 'active' },
    toolOutput: { leases: [lease()], stats, total: null, ...page({ next_cursor: 'l2', has_more: true, limit: 1 }) },
    handlers: {
      owner_leases_list: () => ({ __text: 'Unknown tool: owner_leases_list' }),
      agent_leases_list: () => ({ leases: [lease({ id: 6, tenant: { id: 10, display_name: 'Rohan Das', avatar_url: null } })], stats, ...page({ limit: 1 }) }),
    },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Rohan Das');
  assert.deepEqual(tab.calls.map((call) => call.name), ['owner_leases_list', 'agent_leases_list']);
});

test('LeaseManagement: a resolved text error that is not an unknown tool is shown and the next name is not tried', { skip }, async () => {
  const tab = await openOpenAi('LeaseManagementWidget', {
    toolOutput: { leases: [lease()], stats: { active_leases: 1, total_monthly_rent: 25000 }, total: null, ...page({ next_cursor: 'l2', has_more: true, limit: 1 }) },
    handlers: { owner_leases_list: () => ({ __text: 'Database is busy' }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Database is busy');
  assert.deepEqual(tab.calls.map((call) => call.name), ['owner_leases_list']);
});

test('Maintenance: create reads the property id of the tenant lease', { skip }, async () => {
  const tab = await openOpenAi('MaintenanceWidget', {
    toolOutput: { items: [request()], total: null, ...page() },
    handlers: {
      tenant_lease_current: () => ({ lease: lease({ property_id: 42, property: { ...ref, id: 42, title: 'Lakeview 4B' } }) }),
      tenant_maintenance_create: (args) => ({ request: request({ id: 99, ...args, priority: 'high' }) }),
      tenant_maintenance_list: () => ({ items: [request({ id: 99, title: 'No hot water' }), request()], total: null, ...page() }),
    },
  });
  await press(tab, '+ New');
  await tab.waitForSelector('text=Lakeview 4B');
  await tab.getByRole('button', { name: /Plumbing/ }).click();
  await tab.getByPlaceholder('Brief description of the issue').fill('No hot water');
  await tab.getByPlaceholder(/Provide more details/).fill('Geyser off since Monday');
  await press(tab, 'Submit Request');
  await tab.waitForSelector('text=Request Submitted');
  const create = tab.calls.find((call) => call.name === 'tenant_maintenance_create');
  assert.deepEqual(create.args, { property_id: 42, title: 'No hot water', description: 'Geyser off since Monday', category: 'plumbing', priority: 'medium' });
  await press(tab, 'View All Requests');
  await tab.waitForFunction(() => document.body.innerText.includes('No hot water') && document.body.innerText.includes('Leaking tap'));
  assert.deepEqual(tab.errors, []);
});

test('Maintenance: with no lease the form says so and Submit stays off', { skip }, async () => {
  const tab = await openOpenAi('MaintenanceWidget', {
    toolOutput: { items: [], total: null, ...page() },
    handlers: { tenant_lease_current: () => ({ lease: null, message: 'No active lease found.' }) },
  });
  await press(tab, '+ New');
  await tab.waitForSelector('text=You need an active lease');
  assert.ok(await tab.getByRole('button', { name: 'Submit Request' }).isDisabled());
});

test('Maintenance: Load More keeps the filters of the original call', { skip }, async () => {
  const tab = await openOpenAi('MaintenanceWidget', {
    toolInput: { status: 'open' },
    toolOutput: { items: [request()], total: null, ...page({ next_cursor: 'm2', has_more: true, limit: 1 }) },
    handlers: { tenant_maintenance_list: () => ({ items: [request({ id: 32, title: 'Broken fan' })], ...page({ limit: 1 }) }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Broken fan');
  assert.deepEqual(tab.calls, [{ name: 'tenant_maintenance_list', args: { status: 'open', cursor: 'm2' } }]);
});

test('RentCollection: record payment sends the declared keys, shows the saved payment and refreshes', { skip }, async () => {
  const tab = await openOpenAi('RentCollectionWidget', {
    toolInput: { property_id: 7 },
    toolOutput: { charges: [charge()], totals: { total_due: 15500, total_paid: 10000, overdue_count: 0, charges_count: 1 }, ...page() },
    handlers: {
      owner_rent_record_payment: (args) => ({ payment: payment({ amount_paid: args.amount }) }),
      owner_rent_status: () => ({ charges: [], totals: { total_due: 0, total_paid: 25500, overdue_count: 0, charges_count: 0 }, ...page() }),
    },
  });
  await press(tab, 'Record');
  await tab.waitForSelector('text=Record Payment');
  assert.equal(await tab.locator('input[type=number]').inputValue(), '15500');
  await tab.locator('input[type=number]').fill('15500.456');
  await press(tab, 'UPI');
  await tab.getByPlaceholder('Reference number').fill('UPI-9');
  await press(tab, 'Record Payment');
  await tab.waitForSelector('text=Payment Recorded');
  const { args } = tab.calls.find((call) => call.name === 'owner_rent_record_payment');
  assert.deepEqual(Object.keys(args).sort(), ['amount', 'payment_date', 'payment_method', 'rent_charge_id', 'transaction_id']);
  assert.deepEqual({ ...args, payment_date: undefined }, { rent_charge_id: 41, amount: 15500.46, payment_date: undefined, payment_method: 'upi', transaction_id: 'UPI-9' });
  assert.match(args.payment_date, /^\d{4}-\d{2}-\d{2}$/);
  await press(tab, 'Back to Rent Status');
  await tab.waitForSelector('text=All rent is collected');
  assert.deepEqual(tab.calls.at(-1), { name: 'owner_rent_status', args: { property_id: 7 } });
});

test('RentCollection: Load More pages the charges with the cursor', { skip }, async () => {
  const totals = { total_due: 31000, total_paid: 10000, overdue_count: 1, charges_count: 2 };
  const tab = await openOpenAi('RentCollectionWidget', {
    toolOutput: { charges: [charge()], totals, ...page({ next_cursor: 'r2', has_more: true, limit: 1 }) },
    handlers: { owner_rent_status: () => ({ charges: [charge({ id: 42, billing_month: '2026-11-01' })], totals, ...page({ limit: 1 }) }) },
  });
  await press(tab, 'Load More');
  await tab.waitForSelector('text=November 2026');
  assert.deepEqual(tab.calls, [{ name: 'owner_rent_status', args: { cursor: 'r2' } }]);
});

test('RentCollection: a refused payment shows the message and keeps the form', { skip }, async () => {
  const tab = await openOpenAi('RentCollectionWidget', {
    toolOutput: { charges: [charge()], totals: { total_due: 15500, total_paid: 10000, overdue_count: 0, charges_count: 1 }, ...page() },
    handlers: { owner_rent_record_payment: () => ({ error: true, code: 'INVALID_METHOD' }) },
  });
  await press(tab, 'Record');
  await press(tab, 'Record Payment');
  await tab.waitForSelector('text=Choose a valid payment method.');
});

test('TenantRent: each tab shows the payload its own tool returned, history pages with the cursor', { skip }, async () => {
  const tab = await openOpenAi('TenantRentWidget', {
    toolOutput: { charges: [charge()], total_due: 15500, overdue_count: 0 },
    handlers: {
      tenant_rent_history: (_args, nth) => nth === 1
        ? { items: [payment()], total: null, total_collected: 20000, ...page({ next_cursor: 'h2', has_more: true, limit: 1 }) }
        : { items: [payment({ id: 52, reference: 'NEFT-77' })], total: null, total_collected: 20000, ...page({ limit: 1 }) },
    },
  });
  await press(tab, 'Payment History');
  await tab.waitForSelector('text=UPI-123');
  await press(tab, 'Load More');
  await tab.waitForSelector('text=NEFT-77');
  assert.deepEqual(tab.calls, [{ name: 'tenant_rent_history', args: {} }, { name: 'tenant_rent_history', args: { cursor: 'h2' } }]);
  await press(tab, 'Current Dues');
  assert.ok((await bodyText(tab)).includes('₹15,500'));
});

test('LeaseManagement: Load More tries owner_leases_list, then agent_leases_list; the tenant shows by display name', { skip }, async () => {
  const stats = { active_leases: 2, total_monthly_rent: 50000 };
  const tab = await openOpenAi('LeaseManagementWidget', {
    toolInput: { status: 'active' },
    toolOutput: { leases: [lease()], stats, total: null, ...page({ next_cursor: 'l2', has_more: true, limit: 1 }) },
    handlers: {
      owner_leases_list: () => ({ __throw: 'Unknown tool: owner_leases_list' }),
      agent_leases_list: () => ({ leases: [lease({ id: 6, tenant: { id: 10, display_name: 'Rohan Das', avatar_url: null } })], stats, ...page({ limit: 1 }) }),
    },
  });
  assert.ok((await bodyText(tab)).includes('Tenant: Asha Verma'));
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Rohan Das');
  assert.deepEqual(tab.calls.map((call) => call.name), ['owner_leases_list', 'agent_leases_list']);
  assert.deepEqual(tab.calls[1].args, { status: 'active', cursor: 'l2' });
});

test('OwnerDashboard: the stats cover the portfolio, Load More pages the properties', { skip }, async () => {
  const stats = { total_properties: 12, occupied: 9, vacant: 3, total_monthly_income: 450000 };
  const tab = await openOpenAi('OwnerDashboardWidget', {
    toolInput: { occupancy: 'occupied' },
    toolOutput: { items: [property()], stats, total: null, ...page({ next_cursor: 'o2', has_more: true, limit: 1 }) },
    handlers: { owner_properties_list: () => ({ items: [property({ id: 8, title: 'Beta Tower' })], stats, ...page({ limit: 1 }) }) },
  });
  const before = await bodyText(tab);
  assert.ok(before.includes('12') && before.includes('₹4.50 L'));
  await press(tab, 'Load More');
  await tab.waitForSelector('text=Beta Tower');
  assert.deepEqual(tab.calls, [{ name: 'owner_properties_list', args: { occupancy: 'occupied', cursor: 'o2' } }]);
});

test('VisitScheduler: the form sends the local time as a UTC instant and shows the returned visit', { skip }, async () => {
  const tab = await openOpenAi('VisitSchedulerWidget', {
    toolOutput: { property: ref },
    handlers: {
      visits_schedule: (args) => ({ visit: visit({ id: 70, scheduled_date: args.scheduled_date }) }),
    },
  });
  // The date and the expected instant come from the page, so they use the browser time zone (America/Los_Angeles).
  const date = await tab.evaluate(() => {
    const day = new Date();
    day.setDate(day.getDate() + 3);
    return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-');
  });
  await tab.locator('input[type=date]').fill(date);
  await press(tab, '10:00');
  await press(tab, 'Schedule Visit');
  await tab.waitForSelector('text=Visit Requested');
  const { name, args } = tab.calls[0];
  assert.equal(name, 'visits_schedule');
  assert.deepEqual(Object.keys(args).sort(), ['property_id', 'scheduled_date']);
  // 10:00 local time, as UTC with a Z suffix
  assert.equal(args.scheduled_date, await tab.evaluate((day) => new Date(`${day}T10:00`).toISOString(), date));
  assert.ok(!args.scheduled_date.startsWith(`${date}T10`), 'the instant differs from the local clock time');
  assert.match(args.scheduled_date, /Z$/);
});

// ---------------------------------------------------------------------------
// MCP Apps host (postMessage)
// ---------------------------------------------------------------------------

test('MCP Apps host: tool-input and tool-result render, Load More answers through tools/call', { skip }, async () => {
  const calls = [];
  const tab = await openMcpApps('VisitListWidget', {
    toolInput: { status: 'requested' },
    toolOutput: { ok: true, data: { items: [visit()], ...page({ next_cursor: 'v2', has_more: true, limit: 1 }), counts: { total: 2, upcoming: 2, completed: 0, cancelled: 0 } } },
    onToolCall: (name, args) => {
      calls.push({ name, args });
      return { ok: true, data: { items: [visit({ id: 12, status: 'confirmed' })], ...page({ limit: 1 }), counts: { total: 2, upcoming: 2, completed: 0, cancelled: 0 } } };
    },
  });
  const widget = tab.frameLocator('#w');
  await widget.getByText('REQUESTED').waitFor({ timeout: 5000 });
  await widget.getByRole('button', { name: 'Load More' }).click();
  await widget.getByText('CONFIRMED').waitFor({ timeout: 5000 });
  assert.deepEqual(calls, [{ name: 'visits_list', args: { status: 'requested', cursor: 'v2' } }]);
  assert.deepEqual(tab.errors, []);
});

test('MCP Apps host: an error reply to tools/call shows its message at once', { skip }, async () => {
  const tab = await openMcpApps('VisitListWidget', {
    toolInput: {},
    toolOutput: { items: [visit()], ...page({ next_cursor: 'v2', has_more: true, limit: 1 }), counts: { total: 2, upcoming: 2, completed: 0, cancelled: 0 } },
    onToolCall: () => ({ rpcError: 'This action is not available in the app. Ask the assistant instead.' }),
  });
  const widget = tab.frameLocator('#w');
  await widget.getByRole('button', { name: 'Load More' }).click();
  await widget.getByText('This action is not available in the app').waitFor({ timeout: 3000 });
});

test('MCP Apps host: {ok, data} results of the user tools are unwrapped, a failed envelope shows its message', { skip }, async () => {
  const tab = await openMcpApps('MaintenanceWidget', {
    toolInput: {},
    toolOutput: { items: [], total: null, ...page() },
    onToolCall: (name) => name === 'tenant_lease_current'
      ? { ok: true, data: { lease: lease({ property_id: 42, property: { ...ref, id: 42, title: 'Lakeview 4B' } }) } }
      : { ok: false, error: { code: 'FORBIDDEN', message: 'No active lease for this property' }, message: 'No active lease for this property' },
  });
  const widget = tab.frameLocator('#w');
  await widget.getByRole('button', { name: '+ New' }).click();
  await widget.getByText('Lakeview 4B').waitFor({ timeout: 5000 });
  await widget.getByRole('button', { name: /Plumbing/ }).click();
  await widget.getByPlaceholder('Brief description of the issue').fill('T');
  await widget.getByPlaceholder(/Provide more details/).fill('D');
  await widget.getByRole('button', { name: 'Submit Request' }).click();
  await widget.getByText('No active lease for this property').waitFor({ timeout: 3000 });
});
