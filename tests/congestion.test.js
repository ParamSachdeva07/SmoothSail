import test from 'node:test';
import assert from 'node:assert/strict';
import { createCongestionLookup, issueLevel } from '../src/data/congestion.js';
import { createApiClient } from '../src/api/client.js';

const now = Date.parse('2026-10-24T18:00:00Z');
const assessment = { portId: 'NLRTM', level: 'high', researchStatus: 'completed',
  evidenceAsOf: '2026-10-24T16:00:00Z', refreshAfter: '2026-10-24T18:30:00Z',
  display: { showBadge: true, color: 'red' }, sources: [{ url: 'https://example.test/' }] };

test('only fresh, supported mild/high results produce an issue badge', () => {
  assert.equal(issueLevel(assessment, now), 'high');
  assert.equal(issueLevel({ ...assessment, level: 'mild' }, now), 'mild');
  for (const patch of [
    { level: 'unknown' }, { level: 'low' }, { sources: [] }, { researchStatus: 'timeout' },
    { display: { showBadge: false } }, { evidenceAsOf: '2026-10-20T00:00:00Z' },
    { evidenceAsOf: '2026-10-25T00:00:00Z' }, { refreshAfter: '2026-10-24T17:00:00Z' }
  ]) assert.equal(issueLevel({ ...assessment, ...patch }, now), null);
  assert.equal(issueLevel(null, now), null);
});

test('explicit demo congestion displays without pretending to have current sources', () => {
  const demo = { ...assessment, demo: true, sources: [], evidenceAsOf: null };
  assert.equal(issueLevel(demo, now), 'high');
  assert.equal(issueLevel({ ...demo, demo: false }, now), null);
});

test('concurrent map visits share a request; results cache per voyage port pair until expiry', async () => {
  let calls = 0, clock = now;
  const lookup = createCongestionLookup(async ids => {
    calls++;
    return { assessments: ids.map(portId => ({ ...assessment, portId })) };
  }, () => clock);
  await Promise.all([lookup(['NLRTM', 'SGSIN']), lookup(['NLRTM', 'SGSIN'])]);
  assert.equal(calls, 1);
  await lookup(['NLRTM', 'SGSIN']);
  assert.equal(calls, 1);
  // A new endpoint pair has different eligible alternatives, even if it shares a port.
  await lookup(['NLRTM', 'FRLEH']);
  assert.equal(calls, 2);
  clock += 31 * 60_000;
  await lookup(['NLRTM', 'SGSIN']);
  assert.equal(calls, 3);
});

test('failed research returns unknown and does not retry on every map visit', async () => {
  let calls = 0;
  const lookup = createCongestionLookup(async () => { calls++; throw new Error('Unavailable'); }, () => now);
  const [result] = await lookup(['NLRTM']);
  assert.equal(result.level, 'unknown');
  assert.equal(issueLevel(result, now), null);
  await lookup(['NLRTM']);
  assert.equal(calls, 1);
  assert.deepEqual(await lookup(['malformed']), []);
});

test('congestion HTTP request contains ports only, never provider credentials', async () => {
  const client = createApiClient('/local-api', async (url, init) => {
    assert.equal(url, '/local-api/port-congestion');
    assert.deepEqual(JSON.parse(init.body), { portIds: ['NLRTM', 'SGSIN'] });
    assert.equal(init.credentials, 'omit');
    return Response.json({ assessments: [] });
  });
  await client.getPortCongestion(['NLRTM', 'SGSIN']);
});

test('the browser keeps research pending beyond its old cutoff and accepts the eventual result', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let finish, researchSignal;
  const client = createApiClient('/local-api', (url, { signal }) => {
    researchSignal = signal;
    return new Promise((resolve, reject) => {
      finish = resolve;
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
  });
  const pending = client.getPortCongestion(['NLRTM']);
  t.mock.timers.tick(5 * 60_000);
  assert.equal(researchSignal.aborted, false);
  finish(Response.json({ assessments: [assessment] }));
  assert.deepEqual((await pending).assessments, [assessment]);
});

test('research without a deadline still respects explicit caller cancellation', async () => {
  const controller = new AbortController();
  const client = createApiClient('/local-api', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  }));
  const pending = client.getPortCongestion(['NLRTM'], { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
});

 test('recent weekly pressure respects the declared seven-day window and reversed transfers use separate cache entries', async () => {
  assert.equal(issueLevel({ ...assessment, evidenceAsOf: '2026-10-20T18:00:00Z', evidenceWindowHours: 168 }, now), 'high');
  assert.equal(issueLevel({ ...assessment, evidenceAsOf: '2026-10-16T18:00:00Z', evidenceWindowHours: 999 }, now), null);
  const orders = [];
  const lookup = createCongestionLookup(async ids => { orders.push(ids); return { assessments: ids.map(portId => ({ ...assessment, portId })) }; }, () => now);
  await lookup(['NLRTM', 'FRLEH']); await lookup(['FRLEH', 'NLRTM']);
  assert.deepEqual(orders, [['NLRTM', 'FRLEH'], ['FRLEH', 'NLRTM']]);
});
