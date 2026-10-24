import test from 'node:test';
import assert from 'node:assert/strict';
import { createVoyageTrack } from '../src/globe/voyage.js';
import { bilinear, framePair, waveAt, renderWavePair, validWaveGrid } from '../src/globe/waves.js';

const departure = '2026-10-24T00:00:00Z';
const date = (hour) => new Date(Date.parse(departure) + hour * 3_600_000).toISOString();
const line = (coordinates) => ({ type: 'LineString', coordinates });
const segment = (start, end, coordinates, kind = 'sailing') => ({ entryTime: date(start), exitTime: date(end), kind, geometry: line(coordinates) });
const near = (value, expected, tolerance = 1e-6) => assert.ok(Math.abs(value - expected) < tolerance, `${value} should be close to ${expected}`);
function grid(size = 10) {
  return { projection: 'mercator', rowOrder: 'north_to_south', units: 'm', bounds: [-20, -20, 20, 20], columns: size, rows: size,
    frames: [{ hour: 0, values: Array(size * size).fill(2) }, { hour: 6, values: Array(size * size).fill(4) }] };
}

test('ship follows every polyline leg and remains stationary during a timed canal wait', () => {
  const track = createVoyageTrack({ durationHours: 14, geometry: line([[0, 0], [5, 0], [5, 5], [10, 5]]), segments: [
    segment(0, 10, [[0, 0], [5, 0], [5, 5]]), segment(10, 12, [[5, 5], [5, 5]], 'canal_wait'), segment(12, 14, [[5, 5], [10, 5]], 'canal_transit')
  ] }, departure);
  near(track.at(2.5).coordinates[0], 2.5); near(track.at(2.5).coordinates[1], 0);
  near(track.at(7.5).coordinates[0], 5); near(track.at(7.5).coordinates[1], 2.5);
  assert.deepEqual(track.at(11), { coordinates: [5, 5], kind: 'canal_wait' });
  assert.deepEqual(track.at(99).coordinates, [10, 5]);
  assert.deepEqual(track.at(-3).coordinates, [0, 0]);
});

test('ship crosses the date line at the seam without travelling through Greenwich', () => {
  const geometry = { type: 'MultiLineString', coordinates: [[[179, 20], [180, 20]], [[-180, 20], [-179, 20]]] };
  const track = createVoyageTrack({ durationHours: 2, geometry, segments: [{ geometry, entryTime: date(0), exitTime: date(2) }] }, departure);
  assert.ok(Math.abs(track.at(1).coordinates[0]) > 179.9);
  near(track.at(1.5).coordinates[0], -179.5);
});

test('forecast sampling interpolates in space/time but never extrapolates or treats null as calm', () => {
  const data = grid();
  assert.equal(validWaveGrid(data), true);
  assert.equal(waveAt(data, 3, [0, 0]), 3);
  assert.equal(waveAt(data, 7, [0, 0]), null);
  assert.equal(waveAt(data, 3, [30, 0]), null);
  data.frames[1].values[44] = null;
  assert.equal(waveAt(data, 3, [0, 0]), null);
  assert.equal(waveAt(data, 0, [0, 0]), 2);
  assert.deepEqual(framePair(data, 6), { a: 1, b: 1, mix: 0 });
  assert.equal(bilinear([0, 0, 0, 0], 2, 2, 0.5, 0.5), 0);
  assert.equal(bilinear([0, null, 0, 0], 2, 2, 0.5, 0.5), null);
});

test('wave raster has a bounded soft halo while numeric missing data and large gaps stay unknown', () => {
  const data = grid();
  const [tile] = renderWavePair(data, { a: 0, b: 1 }, { scale: 4 });
  const alpha = (x, y) => tile.pixels[0][(y * tile.width + x) * 4 + 3];
  assert.equal(alpha(0, 18), 0);
  assert.ok(alpha(4, 18) > 0 && alpha(4, 18) < alpha(8, 18));
  // The display may fade a few pixels across a coverage edge. It must not
  // manufacture numeric samples, or fill the interior of a large data gap.
  for (let y = 2; y <= 7; y++) for (let x = 2; x <= 7; x++) data.frames[0].values[y * data.columns + x] = null;
  assert.equal(waveAt(data, 0, [0, 0]), null);
  const hole = renderWavePair(data, { a: 0, b: 1 }, { scale: 4 })[0];
  assert.equal(hole.pixels[0][(18 * hole.width + 18) * 4 + 3], 0);
  assert.equal(hole.pixels[1][(18 * hole.width + 18) * 4 + 3], 0);
});

test('wide wave rasters use matching seam pixels and quads narrower than 180 degrees', () => {
  const data = grid(20); data.bounds = [-180, -60, 180, 60];
  const tiles = renderWavePair(data, { a: 0, b: 1 });
  assert.equal(tiles.length, 3);
  for (let i = 0; i < tiles.length - 1; i++) {
    const left = tiles[i], right = tiles[i + 1];
    assert.ok(left.coordinates[1][0] - left.coordinates[0][0] < 180);
    assert.equal(left.coordinates[1][0], right.coordinates[0][0]);
    for (let y = 0; y < left.height; y++) {
      const edge = (y * left.width + left.width - 1) * 4;
      assert.deepEqual(left.pixels[0].slice(edge, edge + 4), right.pixels[0].slice(y * right.width * 4, y * right.width * 4 + 4));
    }
  }
  const first = tiles[0], last = tiles.at(-1), y = Math.floor(first.height / 2);
  const leftOffset = y * first.width * 4, rightOffset = (y * last.width + last.width - 1) * 4;
  assert.ok(first.pixels[0][leftOffset + 3] > 0, 'the Pacific date line must not have an artificial transparent seam');
  assert.deepEqual(first.pixels[0].slice(leftOffset, leftOffset + 4), last.pixels[0].slice(rightOffset, rightOffset + 4));

  // Missing data on one side must feather consistently on the other side too.
  for (let row = 0; row < data.rows; row++) data.frames[0].values[row * data.columns + data.columns - 2] = null;
  const masked = renderWavePair(data, { a: 0, b: 1 });
  assert.ok(masked[0].pixels[0][leftOffset + 3] < first.pixels[0][leftOffset + 3]);
  assert.equal(masked[0].pixels[0][leftOffset + 3], masked.at(-1).pixels[0][rightOffset + 3]);
});

test('narrow seas retain visible forecast colour next to missing coastal cells', () => {
  const data = grid(20);
  for (const frame of data.frames) {
    frame.values = frame.values.map((v, i) => [9, 10].includes(Math.floor(i / data.columns)) ? v : null);
  }
  const [tile] = renderWavePair(data, { a: 0, b: 1 }, { scale: 4 });
  const alpha = (x, y) => tile.pixels[0][(y * tile.width + x) * 4 + 3];
  // Two valid rows form a narrow strip of sea. Previously its opacity was zero.
  assert.ok(alpha(38, 38) >= 25, 'the blurred field must retain visible colour in a narrow sea');
  assert.equal(alpha(38, 24), 0);
  assert.equal(alpha(38, 52), 0);
  assert.equal(waveAt(data, 0, [0, 10]), null, 'visual fading must not create numeric forecast coverage');
});
