/**
 * Contract checks for the widgets. Run: npm test
 *
 * 1. Every label table holds exactly the values of its enum in openapi/openapi.json.
 * 2. Price, status, date and paging helpers follow the wire rules.
 * 3. Every callTool name in src is a registered tool name (tool-names.json).
 */

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'widgets-checks-')), 'checks.mjs');

await esbuild.build({
  entryPoints: [path.join(root, 'src/checks/exports.ts')],
  bundle: true,
  platform: 'node',
  format: 'esm',
  outfile: out,
  logLevel: 'silent',
});
const m = await import(pathToFileURL(out).href);

const openapi = JSON.parse(fs.readFileSync(path.join(root, 'openapi/openapi.json'), 'utf8'));
const enumValues = (name) => {
  const schema = openapi.components.schemas[name];
  assert.ok(schema?.enum, `enum ${name} is missing from openapi.json`);
  return [...schema.enum].sort();
};
const keys = (table) => Object.keys(table).sort();

test('label tables hold exactly the backend enum values', () => {
  assert.deepEqual(keys(m.PURPOSE_LABEL), enumValues('PropertyPurpose'));
  assert.deepEqual(keys(m.FURNISHING_LABEL), enumValues('FurnishingLevel'));
  assert.deepEqual(keys(m.VISIT_STATUS), enumValues('VisitStatus'));
  assert.deepEqual(keys(m.BOOKING_STATUS), enumValues('BookingStatus'));
  assert.deepEqual(keys(m.LEASE_STATUS), enumValues('LeaseStatus'));
  assert.deepEqual(keys(m.RENT_CHARGE_STATUS), enumValues('RentChargeStatus'));
  assert.deepEqual(keys(m.RENT_PAYMENT_STATUS), enumValues('RentPaymentStatus'));
  assert.deepEqual(keys(m.PAYMENT_METHOD_LABEL), enumValues('PaymentMethod'));
  assert.deepEqual(keys(m.MAINTENANCE_CATEGORY), enumValues('MaintenanceCategory'));
});

test('price follows the purpose and never falls back', () => {
  const base = { base_price: 9000000, monthly_rent: 25000, daily_rate: 3500, nightly_rate: null };
  assert.deepEqual(m.priceFor({ ...base, purpose: 'rent' }), { purpose: 'rent', amount: 25000, unit: '/mo' });
  assert.deepEqual(m.priceFor({ ...base, purpose: 'buy' }), { purpose: 'buy', amount: 9000000, unit: '' });
  // short stay reads the nightly rate; the MCP rows name it daily_rate
  assert.deepEqual(m.priceFor({ ...base, purpose: 'short_stay' }), { purpose: 'short_stay', amount: 3500, unit: '/night' });
  assert.equal(m.priceFor({ ...base, purpose: 'short_stay', nightly_rate: 4000 }).amount, 4000);
  // a short stay with only base_price has no nightly price
  assert.equal(m.priceFor({ ...base, purpose: 'short_stay', daily_rate: null }).amount, null);
  // an unknown purpose has no price
  assert.deepEqual(m.priceFor({ ...base, purpose: 'lease' }), { purpose: null, amount: null, unit: '' });
  assert.equal(m.formatPropertyPrice({ ...base, purpose: 'short_stay' }), '₹3,500/night');
  assert.equal(m.formatPropertyPrice({ ...base, purpose: 'rent' }, true), '₹25,000/month');
  assert.equal(m.formatPropertyPrice({ ...base, purpose: 'buy' }), '₹90.00 L');
  assert.equal(m.formatPropertyPrice({ ...base, purpose: null }), 'Price on request');
  assert.equal(m.purposeLabel('short_stay'), 'Short Stay');
  assert.equal(m.purposeLabel('lease'), null);
});

test('an unknown enum value maps to null, not to a real value', () => {
  assert.equal(m.enumKey(m.VISIT_STATUS, 'scheduled'), null);
  assert.equal(m.enumKey(m.VISIT_STATUS, 'rescheduled'), null);
  assert.equal(m.enumKey(m.VISIT_STATUS, 'requested'), 'requested');
  assert.equal(m.enumKey(m.VISIT_STATUS, 'toString'), null);
  assert.equal(m.enumKey(m.VISIT_STATUS, null), null);
  assert.equal(m.parsePurpose('Rent'), null);
  assert.deepEqual(m.statusView(m.LEASE_STATUS, 'pending'), { key: null, label: 'Unknown', tone: 'muted' });
  assert.equal(m.statusView(m.LEASE_STATUS, 'pending_signature').label, 'Pending signature');
});

test('instants parse as UTC and date-only fields do not shift', () => {
  // The script runs with TZ=America/Los_Angeles, so a shift would show.
  assert.equal(m.parseServerTimestamp('2026-10-15T10:00:00').toISOString(), '2026-10-15T10:00:00.000Z');
  assert.equal(m.parseServerTimestamp('2026-10-15T10:00:00+05:30').toISOString(), '2026-10-15T04:30:00.000Z');
  assert.equal(m.parseServerTimestamp('not a date'), null);
  assert.equal(m.formatDateOnly('2026-05-01', { day: 'numeric', month: 'short', year: 'numeric' }), '1 May 2026');
  assert.equal(m.parseDateOnly('2026-05-01T00:00:00Z'), null);
  const now = new Date(2026, 4, 1, 23, 30);
  assert.equal(m.daysUntilDateOnly('2026-05-31', now), 30);
  assert.equal(m.daysUntilDateOnly('2026-04-30', now), -1);
});

test('money and ordinals format', () => {
  assert.equal(m.formatRupees(1500.3), '₹1,500.3');
  assert.equal(m.formatRupees(null), '-');
  assert.equal(m.formatRupees('1500.00'), '-');
  assert.equal(m.formatRupeesCompact(12000000), '₹1.20 Cr');
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22].map(m.ordinal), ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd']);
});

test('paging merges the returned page and keeps the filters of the first call', () => {
  assert.deepEqual(m.readPage({ next_cursor: 'abc', has_more: true }), { next_cursor: 'abc', has_more: true });
  assert.deepEqual(m.readPage({ next_cursor: null, has_more: true }), { next_cursor: null, has_more: false });
  assert.deepEqual(m.readPage({}), { next_cursor: null, has_more: false });
  const merged = m.mergeRows([{ id: 1, v: 'a' }, { id: 2, v: 'b' }], [{ id: 2, v: 'B' }, { id: 3, v: 'c' }]);
  assert.deepEqual(merged, [{ id: 1, v: 'a' }, { id: 2, v: 'B' }, { id: 3, v: 'c' }]);
  assert.deepEqual(m.pageArgs({ status: 'confirmed', cursor: 'old', limit: 10 }, 'next'), { status: 'confirmed', limit: 10, cursor: 'next' });
  assert.deepEqual(m.pageArgs({ status: 'confirmed', cursor: 'old' }), { status: 'confirmed' });
});

test('tool failures read from both backend error shapes', () => {
  assert.equal(m.isToolFailure({ error: true, code: 'PAST_DATE' }), true);
  assert.equal(m.isToolFailure({ ok: false, error: { code: 'NOT_FOUND', message: 'Lease 5 not found' }, message: 'Lease 5 not found' }), true);
  assert.equal(m.isToolFailure({ requires_auth: true }), true);
  assert.equal(m.isToolFailure({ items: [], has_more: false }), false);
  assert.equal(m.toolFailureMessage({ error: true, code: 'PAST_DATE' }), 'Choose a date and time in the future.');
  assert.equal(m.toolFailureMessage({ ok: false, error: { code: 'NOT_FOUND', message: 'Lease 5 not found' } }), 'Lease 5 not found');
  assert.equal(m.toolFailureMessage({ error: true, requires_auth: true }), 'Sign in to 360Ghar to continue.');
});

test('every callTool name in src is a registered underscore tool name', () => {
  const registered = new Set(JSON.parse(fs.readFileSync(path.join(root, 'src/generated/tool-names.json'), 'utf8')));
  assert.deepEqual([...m.TOOL_NAMES].sort(), [...registered].sort(), 'tool-names.ts is stale: run npm run api:types');

  const names = new Set();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== 'generated' && entry.name !== 'checks') walk(full);
      } else if (/\.tsx?$/.test(entry.name)) {
        const source = fs.readFileSync(full, 'utf8');
        // callTool('name') and callTool<T>('name')
        for (const hit of source.matchAll(/callTool(?:<[^>\n]*>)?\(\s*['"]([^'"]+)['"]/g)) names.add(hit[1]);
        // callTool(['a_b', 'c_d'], ...) with the list inline
        for (const hit of source.matchAll(/callTool(?:<[^>\n]*>)?\(\s*\[([^\]]*)\]/g)) {
          for (const name of hit[1].matchAll(/'([^']+)'/g)) names.add(name[1]);
        }
        // (['a_b', 'c_d'] as const) kept in a variable. Tool names always hold an underscore.
        for (const hit of source.matchAll(/\[((?:\s*'[a-z_]+'\s*,?)+)\s*\]\s*as const/g)) {
          const list = [...hit[1].matchAll(/'([a-z_]+)'/g)].map((x) => x[1]);
          if (list.every((name) => name.includes('_'))) list.forEach((name) => names.add(name));
        }
      }
    }
  };
  walk(path.join(root, 'src'));

  assert.ok(names.size > 0, 'no callTool names found');
  const unknown = [...names].filter((name) => !registered.has(name));
  assert.deepEqual(unknown, [], `callTool names the server does not register: ${unknown.join(', ')}`);
});
