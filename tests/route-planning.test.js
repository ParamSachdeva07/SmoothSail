import test from 'node:test';
import assert from 'node:assert/strict';
import { createRoutePlanner } from '../src/data/route-planning.js';

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

const input = { origin: 'NLRTM', destination: 'SGSIN' };

test('submission starts both requests; routes do not wait for research and map visits reuse it', async () => {
  const routes = deferred(), research = deferred(), calls = [];
  const planner = createRoutePlanner(
    request => { calls.push(['routes', request]); return routes.promise; },
    ports => { calls.push(['research', ports]); return research.promise; }
  );
  const pending = planner.calculate(input);
  await Promise.resolve();
  assert.deepEqual(calls, [['routes', input], ['research', ['NLRTM', 'SGSIN']]]);
  const report = { routes: [] };
  routes.resolve(report);
  assert.equal(await pending, report);
  const onMap = planner.getCongestion(report);
  assert.equal(planner.getCongestion(report), onMap);
  const findings = [{ portId: 'NLRTM', level: 'mild' }];
  research.resolve(findings);
  assert.equal(await onMap, findings);
  assert.equal(await planner.getCongestion(report), findings);
  assert.equal(calls.length, 2);
});

test('research failure does not fail route planning', async () => {
  const report = {};
  const planner = createRoutePlanner(async () => report, () => { throw new Error('Research unavailable'); });
  assert.equal(await planner.calculate(input), report);
  assert.deepEqual(await planner.getCongestion(report), []);
});

test('late research stays associated with its own report when another journey starts', async () => {
  const first = deferred(), second = deferred();
  const planner = createRoutePlanner(async request => ({ ...request }),
    ports => ports[0] === 'NLRTM' ? first.promise : second.promise);
  const reportA = await planner.calculate(input);
  const reportB = await planner.calculate({ origin: 'USLAX', destination: 'JPTYO' });
  const findingsB = [{ portId: 'USLAX', level: 'mild' }];
  second.resolve(findingsB);
  assert.equal(await planner.getCongestion(reportB), findingsB);
  first.resolve([{ portId: 'NLRTM', level: 'high' }]);
  await planner.getCongestion(reportA);
  assert.equal(await planner.getCongestion(reportB), findingsB);
  assert.deepEqual(await planner.getCongestion({}), []);
});

test('cancelled submissions cannot attach results even if a route response arrives late', async () => {
  const routes = deferred(), report = {}, controller = new AbortController();
  let researchCalls = 0;
  const planner = createRoutePlanner(() => routes.promise, async () => { researchCalls++; return []; });
  const pending = planner.calculate(input, { signal: controller.signal });
  await Promise.resolve();
  controller.abort();
  routes.resolve(report);
  await assert.rejects(pending, { name: 'AbortError' });
  assert.deepEqual(await planner.getCongestion(report), []);
  await assert.rejects(planner.calculate(input, { signal: controller.signal }), { name: 'AbortError' });
  assert.equal(researchCalls, 1);
});
