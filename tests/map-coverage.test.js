import test from 'node:test';
import assert from 'node:assert/strict';
import { forecastMapBounds, minimumCoverageZoom, WORLD_BOUNDS } from '../src/globe/map-coverage.js';

const mercator = latitude => Math.asinh(Math.tan(latitude * Math.PI / 180));
const grid = frames => ({ projection: 'mercator', rowOrder: 'north_to_south', units: 'm',
  columns: 3, rows: 5, bounds: [-180, -61, 180, 71],
  frames: frames.map((values, hour) => ({ hour, values })) });

test('camera bounds trim empty polar rows in Mercator coordinates and stay stable across forecast times', () => {
  const a = [null, null, null, 0, 2, null, null, null, null, 3, null, null, null, null, null];
  const b = Array(15).fill(null); b[1] = 4;
  const bounds = forecastMapBounds(grid([a]));
  assert.equal(bounds[0][0], -180); assert.equal(bounds[1][0], 180);
  const top = mercator(71), bottom = mercator(-61);
  assert.ok(Math.abs(mercator(bounds[1][1]) - (top + (bottom - top) / 4)) < 1e-12);
  assert.ok(Math.abs(mercator(bounds[0][1]) - (top + (bottom - top) * 3 / 4)) < 1e-12);
  // A zero-metre forecast is valid. An empty interior row does not split the map.
  const combined = forecastMapBounds(grid([a, b, Array(15).fill(null)]));
  assert.ok(Math.abs(combined[1][1] - 71) < 1e-10);
  assert.equal(combined[0][1], bounds[0][1]);
});

test('zoom-out limit keeps wide, tall and resized viewports inside the forecast footprint', () => {
  for (const bounds of [[[-180, -60], [180, 70]], [[-20, 30], [40, 65]]]) {
    for (const [width, height] of [[1512, 772], [390, 844], [2560, 1440], [844, 390]]) {
      const z = minimumCoverageZoom(bounds, width, height);
      const pixels = 512 * 2 ** z;
      const xSpan = (bounds[1][0] - bounds[0][0]) / 360;
      const ySpan = (mercator(bounds[1][1]) - mercator(bounds[0][1])) / (2 * Math.PI);
      assert.ok(pixels * xSpan >= width - 1e-8);
      assert.ok(pixels * ySpan >= height - 1e-8);
      const smaller = pixels / 2 ** 0.01;
      assert.ok(smaller * xSpan < width || smaller * ySpan < height);
    }
  }
});

test('missing forecasts restore world bounds rather than leaving a previous voyage constraint', () => {
  assert.deepEqual(forecastMapBounds(null), WORLD_BOUNDS);
  assert.deepEqual(forecastMapBounds(grid([Array(15).fill(null)])), WORLD_BOUNDS);
});
