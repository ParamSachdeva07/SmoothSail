import test from 'node:test';
import assert from 'node:assert/strict';
import { createAnalysisPlanner } from '../src/data/route-planning.js';
import { createApiClient } from '../src/api/client.js';
import { findingsForPort, coverageSummary, formatEvidenceMarkers, categoryProgress } from '../src/data/compliance.js';

test('chat renders single and grouped evidence IDs as readable citations', () => {
  assert.equal(formatEvidenceMarkers('Rule [source:hash:a], conditions [source:hash:a, source:hash:b].',
    [{ id: 'source:hash:a' }, { id: 'source:hash:b' }]), 'Rule [1], conditions [1, 2].');
});

test('routes resolve early and specialist updates survive navigation but cancel on a new voyage', async () => {
  const calls = [];
  const planner = createAnalysisPlanner((input, options) => {
    calls.push({ input, ...options }); return new Promise(() => {});
  });
  const page = new AbortController(), report = { reportId: 'first' };
  const promise = planner.calculate({ origin: 'NLRTM', destination: 'SGSIN' }, {
    signal: page.signal, cargoText: 'Full cargo', documentReferences: [{ id: 'd1' }]
  });
  calls[0].onEvent({ type: 'route_report', report });
  assert.equal(await promise, report);
  page.abort(); assert.equal(calls[0].signal.aborted, false);
  const states = [], unsubscribe = planner.subscribe(report, state => states.push(state.findings.length));
  calls[0].onEvent({ type: 'assessment', category: 'trade', findings: [{ id: 'f1' }], status: 'needs_input' });
  assert.deepEqual(states, [0, 1]);
  assert.equal(calls[0].input.cargoText, 'Full cargo');
  const next = planner.calculate({ origin: 'USNYC', destination: 'NLRTM' });
  assert.equal(calls[0].signal.aborted, true);
  calls[1].onEvent({ type: 'route_report', report: {} }); await next;
  calls[0].onEvent({ type: 'assessment', category: 'security', findings: [{ id: 'stale' }] });
  assert.equal(planner.getState(report).findings.length, 1);
  unsubscribe();
});

test('NDJSON parser handles split Unicode and multiple results without buffering until complete', async () => {
  const bytes = new TextEncoder().encode('{"type":"route_report","report":{"name":"海"}}\n{"type":"complete"}\n');
  const body = new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
    controller.close();
  } });
  const client = createApiClient('https://api.example', async (url, init) => {
    assert.equal(url, 'https://api.example/voyages/analyse');
    assert.equal(init.credentials, 'omit');
    return new Response(body, { headers: { 'Content-Type': 'application/x-ndjson' } });
  });
  const events = []; await client.analyseVoyage({}, { onEvent: event => events.push(event) });
  assert.equal(events[0].report.name, '海'); assert.equal(events[1].type, 'complete');
});

test('port lists include scoped information gaps alongside supported alerts', () => {
  const finding = { id: 'one', status: 'estimated', severity: 'yellow', scope: { routeIds: ['r1'], portIds: ['NLRTM'] }, evidence: [{ authority: 'official' }] };
  assert.equal(findingsForPort([finding, finding], 'r1', 'NLRTM').length, 1);
  assert.equal(findingsForPort([finding], 'r2', 'NLRTM').length, 0);
  assert.equal(findingsForPort([{ ...finding, status: 'unverified', severity: 'info' }], 'r1', 'NLRTM').length, 1);
  assert.equal(findingsForPort([{ ...finding, status: 'needs_input', severity: 'info', evidence: [] }], 'r1', 'NLRTM').length, 1);
  assert.equal(findingsForPort([finding], 'r1', 'FRLEH').length, 0);
  assert.equal(findingsForPort([{ ...finding, evidence: [] }], 'r1', 'NLRTM').length, 0);
  assert.equal(findingsForPort([{ ...finding, severity: 'info' }], 'r1', 'NLRTM').length, 0);
  assert.match(coverageSummary({ checks: { sanctions: { status: 'needs_input' } }, complete: true }), /1 need data/);
});

test('category progress shows completed work separately from findings and failed checks', () => {
  assert.equal(categoryProgress({ checks: {} }, 'trade').label, 'Researching');
  const incomplete = categoryProgress({ checks: { trade: { status: 'needs_input' } } }, 'trade');
  assert.equal(incomplete.label, 'Research complete'); assert.equal(incomplete.phase, 'done');
  assert.equal(incomplete.status, 'needs_input');
  assert.equal(categoryProgress({ checks: {}, complete: true }, 'trade').label, 'Unavailable');
  assert.notEqual(categoryProgress({ checks: {}, complete: true }, 'trade').phase, 'done');
  assert.equal(categoryProgress({ checks: {}, complete: true, error: 'Disconnected' }, 'trade').label, 'Interrupted');
  const row = categoryProgress({ checks: { security: { status: 'completed', summary: 'Checked publications',
    coverageNotes: ['Intersections need verification'] } } }, 'security');
  assert.equal(row.label, 'Research complete'); assert.match(row.description, /Intersections need verification/);
});
