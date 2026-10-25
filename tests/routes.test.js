import test from 'node:test';
import assert from 'node:assert/strict';
import { toRouteRequest, formatEta } from '../src/data/shipment.js';
import { validateReport, setReport, getReport, getRoutes, findRoute, formatDuration, formatUsd, coverageLabel, escapeHtml, reportPort } from '../src/data/routes.js';
import { routeFeature, routeBounds } from '../src/globe/geometry.js';
import { createApiClient } from '../src/api/client.js';

const geometry = { type: 'MultiLineString', coordinates: [[[139.9, 34.8], [180, 40]], [[-180, 40], [-118.179, 33.62825]]] };
const route = { id: 'fastest-api-id', strategy: 'fastest', geometry, durationHours: 47.9, distanceNm: 4800,
  eta: '2026-10-27T06:30:00Z', cost: { totalUsd: 123456, fuelTonnes: 300 }, emissions: { co2Tonnes: 934.2 }, forecastCoveragePercent: null };
const now = new Date('2026-10-24T12:00:00Z');

test('simple request uses LOCODEs, today uses server time and future dates are UTC', () => {
  assert.deepEqual(toRouteRequest({ originId: 'NLRTM', destinationId: 'SGSIN', departure: '2026-10-24' }, now), { origin: 'NLRTM', destination: 'SGSIN' });
  assert.equal(toRouteRequest({ originId: 'NLRTM', destinationId: 'SGSIN', departure: '2026-10-26' }, now).departureTime, '2026-10-26T00:00:00.000Z');
  for (const departure of ['', '2026-02-30', '2026-10-23']) assert.throws(() => toRouteRequest({ originId: 'NLRTM', destinationId: 'SGSIN', departure }, now));
  assert.throws(() => toRouteRequest({ originId: 'NLRTM', destinationId: 'NLRTM', departure: '2026-10-24' }, now), /different/);
  assert.throws(() => toRouteRequest({ originId: null, destinationId: 'SGSIN', departure: '2026-10-24' }, now), /suggestions/);
});

test('preserves API metrics, full evidence and distinct objectives on identical geometry', () => {
  const report = { origin: 'JPTYO', destination: 'USLAX', metadata: { evidence: 'retained' }, routes: [route,
    { ...route, id: 'economical-api-id', strategy: 'economical' }, { ...route, id: 'eco-api-id', strategy: 'lowest_emissions' }] };
  setReport(report);
  assert.equal(getReport(), report);
  assert.deepEqual(getRoutes().map((r) => r.label), ['Fastest', 'Cheapest', 'Lowest CO₂']);
  assert.equal(findRoute('eco-api-id').cost.totalUsd, 123456);
  assert.equal(findRoute('economical-api-id').eta, route.eta);
  assert.equal(findRoute('missing'), null);
  assert.deepEqual(reportPort(report, 'destination').coordinates, [-118.179, 33.62825]);
});

test('date-line geometry remains split without a spurious line across the map', () => {
  assert.equal(routeFeature(route).geometry, geometry);
  assert.equal(routeFeature(route).geometry.coordinates.length, 2);
  assert.deepEqual(routeBounds(geometry), [[-180, 33.62825], [180, 40]]);
});

test('empty, duplicate-ID and malformed geometry responses fail clearly', () => {
  assert.throws(() => validateReport({ routes: [] }), /No routes/);
  assert.throws(() => validateReport({ routes: [route, route] }), /invalid/);
  assert.throws(() => validateReport({ routes: [{ ...route, geometry: { type: 'Point', coordinates: [1, 2] } }] }), /invalid/);
  assert.throws(() => validateReport({ routes: [{ ...route, geometry: { type: 'LineString', coordinates: [[0, 0], [NaN, 0]] } }] }), /invalid/);
  assert.doesNotThrow(() => validateReport({ routes: [route] }));
});

test('formatting preserves unknowns, UTC ETA and whole-voyage units', () => {
  assert.equal(formatDuration(47.9), '2d 0h');
  assert.equal(formatUsd(null), 'Unavailable');
  assert.equal(formatUsd(5000, { compact: true }), '$5,000');
  assert.equal(coverageLabel(route), 'Weather coverage unavailable');
  assert.equal(coverageLabel({ forecastCoveragePercent: 0 }), '0% weather coverage');
  assert.equal(formatEta(route.eta), '27 Oct 2026 · 06:30 UTC');
  assert.equal(escapeHtml('<img onerror="boom">'), '&lt;img onerror=&quot;boom&quot;&gt;');
});

test('HTTP client sends one JSON route request without cookies and respects catalogue limit', async () => {
  const calls = [];
  const client = createApiClient('https://example.test/', async (url, init) => {
    calls.push({ url, init }); return new Response(JSON.stringify({ routes: [route] }), { status: 200 });
  });
  const input = { origin: 'NLRTM', destination: 'SGSIN' };
  await client.getPorts(); await client.getPorts({ query: 'Port Said', limit: 10 }); await client.planRoutes(input);
  assert.equal(calls[0].url, 'https://example.test/ports?limit=20&q=');
  assert.equal(calls[1].url, 'https://example.test/ports?limit=10&q=Port%20Said');
  assert.equal(calls[2].url, 'https://example.test/routes');
  assert.equal(calls[2].init.credentials, 'omit');
  assert.deepEqual(JSON.parse(calls[2].init.body), input);
});

test('structured backend errors, startup failures and network errors stay actionable', async () => {
  for (const [fetcher, match] of [
    [async () => new Response(JSON.stringify({ error: { message: 'No connected sea route' } }), { status: 422 }), /No connected sea route/],
    [async () => new Response('upstream', { status: 503 }), /starting/],
    [async () => { throw new TypeError('Failed to fetch'); }, /connection/],
    [async () => new Response('not JSON'), /unreadable/]
  ]) await assert.rejects(() => createApiClient('https://example.test', fetcher).planRoutes({}), match);
});

test('cancel and timeout do not leave pending requests or masquerade as success', async () => {
  const fetcher = (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  });
  const client = createApiClient('https://example.test', fetcher);
  const controller = new AbortController();
  const pending = client.planRoutes({}, { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  await assert.rejects(() => client.planRoutes({}, { timeoutMs: 5 }), /timed out/);
});
