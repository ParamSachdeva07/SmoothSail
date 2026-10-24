import test from 'node:test';
import assert from 'node:assert/strict';
import { highSeasFeatures, highSeasAtHour, verifiedAreaNotices, activeAreaNotices } from '../src/globe/hazards.js';

const grid = values => ({ columns: 10, rows: 10, bounds: [-20, 20, 20, 50], frames: [{ hour: 0, validAt: '2026-10-24T00:00:00Z', values }] });
test('high-sea areas use actual thresholds without labels or invented hazards', () => {
  assert.equal(highSeasFeatures(grid(Array(100).fill(null)), 0).features.length, 0);
  assert.equal(highSeasFeatures(grid(Array(100).fill(2)), 0).features.length, 0);
  const values = Array.from({ length: 100 }, (_, i) => {
    const x = i % 10, y = Math.floor(i / 10); return x > 1 && x < 8 && y > 1 && y < 8 ? 7 : null;
  });
  const features = highSeasFeatures(grid(values), 0).features;
  assert.deepEqual([...new Set(features.map(f => f.properties.thresholdM))].sort(), [4, 6]);
  for (const f of features) {
    assert.equal(f.geometry.type, 'Polygon');
    assert.equal(f.properties.validAt, '2026-10-24T00:00:00Z');
    assert.match(f.properties.basis, /not a confirmed storm/);
    for (const point of f.geometry.type === 'Point' ? [f.geometry.coordinates] : f.geometry.coordinates.flat()) {
      assert.ok(point[0] >= -20 && point[0] <= 20 && point[1] >= 20 && point[1] <= 50);
    }
  }
});

test('sea contours move continuously through the interpolated field, with the selected valid time', () => {
  const data = grid(Array.from({ length: 100 }, (_, i) => i % 10));
  data.frames.push({ hour: 6, validAt: '2026-10-24T06:00:00Z', values: data.frames[0].values.map(v => v + 2) });
  const westEdge = hour => Math.min(...highSeasAtHour(data, hour).features.find(f => f.geometry.type === 'Polygon' && f.properties.thresholdM === 4).geometry.coordinates[0].map(p => p[0]));
  assert.ok(westEdge(0) > westEdge(3) && westEdge(3) > westEdge(6));
  assert.ok(Math.abs(westEdge(3) - (westEdge(0) + westEdge(6)) / 2) < 1e-8);
  assert.ok(Math.abs(westEdge(3) - westEdge(3.01)) < 0.02);
  const middle = highSeasAtHour(data, 3).features[0].properties;
  assert.equal(middle.validAt, '2026-10-24T03:00:00.000Z');
  assert.equal(middle.interpolated, true);
  assert.deepEqual(highSeasAtHour(data, 6), highSeasFeatures(data, 1));
});

test('contours neither extrapolate forecasts nor interpolate through missing samples', () => {
  const data = grid(Array(100).fill(null));
  data.frames.push({ hour: 6, validAt: '2026-10-24T06:00:00Z', values: Array(100).fill(7) });
  for (const hour of [-1, 0, 3, 5.99, 6.01]) assert.equal(highSeasAtHour(data, hour).features.length, 0);
  assert.ok(highSeasAtHour(data, 6).features.length > 0);
});

test('area notices require verification and obey exact validity boundaries', () => {
  const feature = { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[0,0],[1,0],[1,1],[0,0]]] },
    properties: { id: 'notice-1', kind: 'restriction', name: 'Example closure', verified: true, action: 'exclude', validFrom: '2026-10-24T00:00:00Z', validTo: '2026-10-25T00:00:00Z' } };
  const overlays = { features: [feature, { ...feature, properties: { ...feature.properties, verified: false } }, { ...feature, properties: { ...feature.properties, cancelled: true } }] };
  const verified = verifiedAreaNotices(overlays);
  assert.equal(verified.length, 1);
  assert.equal(activeAreaNotices(verified, '2026-10-23T23:59:59Z').features.length, 0);
  assert.match(activeAreaNotices(verified, '2026-10-24T00:00:00Z').features[0].properties.label, /Restricted/);
  assert.equal(activeAreaNotices(verified, '2026-10-25T00:00:00Z').features.length, 0);
  assert.equal(verifiedAreaNotices(null).length, 0);
});
