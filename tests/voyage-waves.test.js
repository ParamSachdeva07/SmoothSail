import { renderWaveFrame, waveQuad } from '../src/globe/wave-texture.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import { createVoyageTrack } from '../src/globe/voyage.js';
import { bilinear, framePair, waveAt, validWaveGrid, waveDisplayTime, waveDisplayGrid } from '../src/globe/waves.js';

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

test('holding a dated display snapshot does not extend numerical forecast coverage', () => {
  const data = grid();
  data.frames.forEach(frame => { frame.validAt = date(frame.hour); });
  assert.deepEqual(waveDisplayTime(data, 30), { hour: 6, held: 'last', validAt: date(6) });
  assert.deepEqual(waveDisplayTime(data, -1), { hour: 0, held: 'first', validAt: date(0) });
  assert.deepEqual(waveDisplayTime(data, 3), { hour: 3, held: null, validAt: null });
  assert.equal(waveAt(data, 30, [0, 0]), null);
  assert.equal(waveDisplayTime(null, 3), null);
});

test('the held snapshot is the last populated forecast, not an empty padded time step', () => {
  const data = grid();
  data.frames.push({ hour: 12, values: Array(100).fill(null) }, { hour: 18, values: Array(100).fill(null) });
  const display = waveDisplayGrid(data);
  assert.equal(waveDisplayTime(display, 30).hour, 6);
  assert.equal(data.frames.length, 4);
  data.frames[3].values[0] = 3;
  assert.equal(waveDisplayTime(waveDisplayGrid(data), 30).hour, 6, 'a sparse regional tail must not blank the global display');
  data.frames[0].values.fill(null);
  assert.equal(waveDisplayGrid(data).frames[0].hour, 6);
  data.frames[3].values.fill(2);
  assert.equal(waveDisplayGrid(data).frames.length, 3, 'preserve the internal missing frame');
  assert.equal(waveAt(waveDisplayGrid(data), 12, [0, 0]), null);
  data.frames.forEach(frame => frame.values.fill(null));
  assert.equal(waveDisplayGrid(data), null);
});

test('native wave texture keeps missing data numeric and large holes transparent', () => {
  const data = grid(20);
  const frame = renderWaveFrame(data, data.frames[0].values);
  assert.equal(frame.pixels.byteLength, 20 * 20 * 4);
  const alpha = (image, x, y) => image.pixels[(y * image.width + x) * 4 + 3];
  assert.equal(alpha(frame, 0, 10), 0);
  assert.ok(alpha(frame, 1, 10) > 0 && alpha(frame, 1, 10) < alpha(frame, 3, 10));
  for (let y = 5; y <= 14; y++) for (let x = 5; x <= 14; x++) data.frames[0].values[y * 20 + x] = null;
  const hole = renderWaveFrame(data, data.frames[0].values);
  assert.equal(alpha(hole, 10, 10), 0);
  assert.equal(waveAt(data, 0, [0, 0]), null);
  // Stored colours must be premultiplied, to blend correctly without dark seams.
  for (let i = 0; i < frame.pixels.length; i += 4) for (let c = 0; c < 3; c++) assert.ok(frame.pixels[i + c] <= frame.pixels[i + 3]);
});

test('native textures wrap seamlessly at the date line, including missing coastal samples', () => {
  const data = grid(20); data.bounds = [-180, -60, 180, 60];
  for (let row = 0; row < 20; row++) data.frames[0].values[row * 20 + 18] = null;
  const { pixels } = renderWaveFrame(data, data.frames[0].values);
  for (let row = 0; row < 20; row++) assert.deepEqual(pixels.slice(row * 80, row * 80 + 4), pixels.slice(row * 80 + 76, row * 80 + 80));
  assert.ok(pixels[10 * 80 + 3] > 0);
  const quad = waveQuad(data.bounds, 20, 20);
  near(quad[0], 0); near(quad[8], 1);
  near(quad[2], 0.025); near(quad[10], 0.975);
  assert.ok(quad[1] < quad[5]);
});

test('native texture retains narrow seas and does not fill distant data gaps', () => {
  const data = grid(20);
  const values = data.frames[0].values.map((v, i) => [9, 10].includes(Math.floor(i / 20)) ? v : null);
  const frame = renderWaveFrame(data, values);
  const alpha = y => frame.pixels[(y * 20 + 10) * 4 + 3];
  assert.ok(alpha(9) >= 25);
  assert.equal(alpha(5), 0); assert.equal(alpha(14), 0);
});
