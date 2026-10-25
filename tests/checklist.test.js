import test from 'node:test';
import assert from 'node:assert/strict';
import { createApiClient } from '../src/api/client.js';

test('checklist generation sends only the existing context and selected route', async () => {
  const input = { analysisId: 'a', contextToken: 'token', routeId: 'r' };
  const client = createApiClient('/local-api', async (url, options) => {
    assert.equal(url, '/local-api/voyages/checklist');
    assert.deepEqual(JSON.parse(options.body), input);
    assert.equal(options.credentials, 'omit');
    return Response.json({ id: 'checklist', actions: [] });
  });
  assert.equal((await client.createVoyageChecklist(input)).id, 'checklist');
});

test('checklist PDF preserves bytes and exposes backend validation errors', async () => {
  const client = createApiClient('/api', async () => new Response('%PDF-1.7', { headers: { 'Content-Type': 'application/pdf' } }));
  assert.equal(await (await client.exportVoyageChecklist({})).text(), '%PDF-1.7');
  const denied = createApiClient('/api', async () => Response.json({ error: { message: 'Context expired' } }, { status: 410 }));
  await assert.rejects(denied.exportVoyageChecklist({}), /Context expired/);
  const wrong = createApiClient('/api', async () => new Response('<html>Error</html>'));
  await assert.rejects(wrong.exportVoyageChecklist({}), /did not return a PDF/);
});

import { checklistExportInput, checklistItems, toggleAllChecklistItems } from '../src/data/checklist.js';

const displayed = () => ({ id: 'checklist', routeId: 'r1', generatedAt: '2026-10-25T00:00:00Z',
  voyage: { origin: 'NLRTM', destination: 'SGSIN', departureTime: '2026-10-26T00:00:00Z' },
  route: { strategy: 'fastest', eta: '2026-11-01T00:00:00Z', geometry: { huge: true } },
  actions: [{ id: 'a1', title: 'Confirm cargo documents', category: 'trade', status: 'needs_input',
    action: 'Confirm documents', evidence: [{ id: 'e1', title: 'Rule', url: 'https://www.imo.org/',
      retrievedAt: '2026-10-25T00:00:00Z', supportingPassage: 'Long raw source text', authority: 'official' }] }],
  documents: [{ id: 'd1', title: 'Cargo declaration', applicability: 'conditional', purpose: 'Declare cargo', actionIds: ['a1'] }],
  coverage: [], partial: false, researchStatus: 'completed', researchGaps: [] });

test('select all and deselect all cover actions and documents without losing partial selections', () => {
  const result = displayed(), checked = new Set(['a1']);
  assert.equal(toggleAllChecklistItems(result, checked), true);
  assert.deepEqual([...checked], ['a1', 'd1']);
  assert.equal(toggleAllChecklistItems(result, checked), false);
  assert.equal(checked.size, 0);
  assert.equal(checklistItems(null).length, 0);
});

test('PDF exports carry the displayed snapshot so expired research sessions are unnecessary', async () => {
  const result = displayed();
  const input = checklistExportInput({ analysisId: 'expired', contextToken: 'expired' }, result,
    new Set(['a1', 'd1', 'old']), { a1: 'Confirmed with agent', old: 'Stale note', d1: '' });
  assert.deepEqual(input.checkedItemIds, ['a1', 'd1']);
  assert.deepEqual(input.itemNotes, { a1: 'Confirmed with agent' });
  assert.equal(input.snapshot.actions[0].action, 'Confirm documents');
  assert.equal(input.snapshot.documents[0].title, 'Cargo declaration');
  assert.equal(input.snapshot.route.geometry, undefined);
  assert.equal(input.snapshot.actions[0].evidence[0].supportingPassage, undefined);
  const client = createApiClient('/api', async (url, options) => {
    assert.deepEqual(JSON.parse(options.body), input);
    return new Response('%PDF-snapshot', { headers: { 'Content-Type': 'application/pdf' } });
  });
  assert.equal(await (await client.exportVoyageChecklist(input)).text(), '%PDF-snapshot');
});

test('one package request downloads ZIP while keeping PDF-only export available', async () => {
  const input = checklistExportInput({ analysisId: 'expired', contextToken: 'expired' }, displayed(), new Set(), {});
  let path;
  const client = createApiClient('/api', async (url, options) => {
    path = url;
    assert.deepEqual(JSON.parse(options.body), input);
    return new Response(new Uint8Array([80, 75, 3, 4]), { headers: { 'Content-Type': 'application/zip' } });
  });
  const blob = await client.exportVoyageChecklist(input, { format: 'bundle' });
  assert.equal(path, '/api/voyages/checklist/bundle');
  assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], [80, 75, 3, 4]);
});

import { curateChecklist } from '../src/data/checklist.js';
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('document curation survives closing and reopening without duplicate requests or lost selections', async () => {
  const final = deferred(), preview = displayed(); preview.researchStatus = 'researching';
  const session = { result: null, checked: new Set(['a1']), notes: { a1: 'Assigned to operations' } };
  const calls = []; let visible = true, displayedResult;
  const fetcher = async input => { calls.push(input); return input.research === false ? preview : final.promise; };
  const update = () => { if (visible) displayedResult = session.result; };
  const pending = curateChecklist(session, { routeId: 'r1' }, fetcher, update);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(displayedResult, preview);
  visible = false; // Closing the dialog does not own/cancel this session's job.
  assert.equal(curateChecklist(session, { routeId: 'r1' }, fetcher, update), pending);
  const completed = displayed(); final.resolve(completed); await pending;
  assert.equal(session.result, completed); assert.equal(session.pending, null);
  assert.equal(calls.length, 2); assert.equal(displayedResult, preview);
  visible = true; update(); assert.equal(displayedResult, completed);
  assert.deepEqual([...session.checked], ['a1']); assert.equal(session.notes.a1, 'Assigned to operations');
});

test('background jobs keep results isolated between route sessions and can retry failed research', async () => {
  const a = { result: null }, b = { result: null }, waiting = deferred();
  const pendingA = curateChecklist(a, { routeId: 'a' }, input => input.research === false ? Promise.resolve({ routeId: 'a' }) : waiting.promise);
  await curateChecklist(b, { routeId: 'b' }, async () => ({ routeId: 'b' }));
  waiting.reject(new Error('Provider unavailable')); await pendingA;
  assert.equal(a.error, 'Provider unavailable'); assert.equal(a.pending, null);
  assert.equal(b.result.routeId, 'b'); assert.equal(b.error, null);
  await curateChecklist(a, { routeId: 'a' }, async () => ({ routeId: 'a', researchStatus: 'completed' }));
  assert.equal(a.error, null); assert.equal(a.result.researchStatus, 'completed');
});
