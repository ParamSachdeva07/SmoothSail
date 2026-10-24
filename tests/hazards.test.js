import test from 'node:test';
import assert from 'node:assert/strict';
import { highSeasFeatures, verifiedAreaNotices, activeAreaNotices } from '../src/globe/hazards.js';

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
