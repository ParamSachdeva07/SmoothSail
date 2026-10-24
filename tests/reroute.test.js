import test from 'node:test';
import assert from 'node:assert/strict';
import { reroutedShipment, toRouteRequest } from '../src/data/shipment.js';

const now = new Date('2026-10-24T22:00:00Z');
const ports = [{ id: 'NLRTM' }, { id: 'FRLEH' }, { id: 'DEHAM' }];
const report = { origin: 'NLRTM', destination: 'FRLEH', departureTime: '2026-10-26T00:00:00Z' };
const alternativePort = { portId: 'DEHAM' };

test('rerouting replaces the affected endpoint and preserves the other port and future departure', () => {
  const origin = reroutedShipment(report, { portId: 'NLRTM', alternativePort }, ports, now);
  assert.deepEqual(toRouteRequest(origin, now), {
    origin: 'DEHAM', destination: 'FRLEH', departureTime: '2026-10-26T00:00:00.000Z'
  });
  const arrival = reroutedShipment(report, { portId: 'FRLEH', alternativePort }, ports, now);
  assert.deepEqual(toRouteRequest(arrival, now), {
    origin: 'NLRTM', destination: 'DEHAM', departureTime: '2026-10-26T00:00:00.000Z'
  });
  assert.equal(report.origin, 'NLRTM');
});

test('past departure becomes depart-now and unsafe or unrelated replacements are rejected', () => {
  const next = reroutedShipment({ ...report, departureTime: '2026-10-23T10:00:00Z' },
    { portId: 'NLRTM', alternativePort }, ports, now);
  assert.deepEqual(toRouteRequest(next, now), { origin: 'DEHAM', destination: 'FRLEH' });
  for (const change of [
    { portId: 'NLRTM', alternativePort: { portId: 'FRLEH' } },
    { portId: 'NLRTM', alternativePort: { portId: 'UNKNOWN' } },
    { portId: 'USLAX', alternativePort }
  ]) assert.throws(() => reroutedShipment(report, change, ports, now));
});
