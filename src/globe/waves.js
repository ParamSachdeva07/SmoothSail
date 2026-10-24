// Display interpolation only. Unknown samples never become zero-height waves.
const mercator = (lat) => Math.asinh(Math.tan(lat * Math.PI / 180));
export const DEFAULT_WAVE_RAMP = [
  [0, 126, 176, 191, 70], [1, 105, 170, 180, 95], [2, 151, 186, 168, 120],
  [3, 210, 187, 134, 145], [4, 214, 150, 123, 165], [6, 183, 112, 126, 180]
];
export function validWaveGrid(grid) {
  return grid?.projection === 'mercator' && grid.rowOrder === 'north_to_south' && grid.units === 'm' &&
    grid.columns >= 2 && grid.rows >= 2 && Array.isArray(grid.bounds) && grid.bounds.length === 4 &&
    grid.bounds.every(Number.isFinite) && grid.bounds[0] < grid.bounds[2] && grid.bounds[1] < grid.bounds[3] &&
    Array.isArray(grid.frames) && grid.frames.length > 0 && grid.frames.every((frame, i) =>
      Number.isFinite(frame.hour) && (!i || frame.hour > grid.frames[i - 1].hour) &&
      Array.isArray(frame.values) && frame.values.length === grid.columns * grid.rows);
}
export function framePair(grid, hour) {
  if (!grid || !Number.isFinite(hour)) return null;
  const frames = grid.frames;
  if (hour < frames[0].hour || hour > frames.at(-1).hour) return null;
  const upper = frames.findIndex((frame) => frame.hour >= hour);
  if (frames[upper].hour === hour) return { a: upper, b: upper, mix: 0 };
  return { a: upper - 1, b: upper, mix: (hour - frames[upper - 1].hour) / (frames[upper].hour - frames[upper - 1].hour) };
}
// Display only: hold an explicitly dated snapshot when the ship travels beyond
// forecast coverage. waveAt() and route estimates never use this clamped time.
export function waveDisplayTime(grid, hour) {
  if (!grid || !Number.isFinite(hour)) return null;
  const first = grid.frames[0], last = grid.frames.at(-1);
  if (hour < first.hour) return { hour: first.hour, held: 'first', validAt: first.validAt };
  if (hour > last.hour) return { hour: last.hour, held: 'last', validAt: last.validAt };
  return { hour, held: null, validAt: null };
}
export function waveDisplayGrid(grid) {
  if (!validWaveGrid(grid)) return null;
  const counts = grid.frames.map(frame => frame.values.reduce((sum, value) => sum + (Number.isFinite(value) && value >= 0 ? 1 : 0), 0));
  const peak = Math.max(...counts);
  if (!peak) return null;
  // The global provider may end before a tiny regional supplement. Hold the
  // last broadly covered snapshot (>= half the peak coverage), not a nearly
  // empty regional tail. This selection is purely for the global display.
  const first = counts.findIndex(count => count >= peak / 2), last = counts.findLastIndex(count => count >= peak / 2);
  // Trim only the ends; an interior missing frame is not interpolated away.
  return first < 0 ? null : { ...grid, frames: grid.frames.slice(first, last + 1) };
}
export function bilinear(values, columns, rows, x, y) {
  if (x < 0 || y < 0 || x > columns - 1 || y > rows - 1) return null;
  const left = Math.min(columns - 2, Math.floor(x)), top = Math.min(rows - 2, Math.floor(y));
  const fx = x - left, fy = y - top;
  const indices = [top * columns + left, top * columns + left + 1, (top + 1) * columns + left, (top + 1) * columns + left + 1];
  const weights = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy];
  let value = 0;
  for (let i = 0; i < 4; i++) {
    if (weights[i] <= 1e-10) continue;
    if (!Number.isFinite(values[indices[i]])) return null;
    value += values[indices[i]] * weights[i];
  }
  return value;
}
export function waveAt(grid, hour, [longitude, latitude]) {
  const pair = framePair(grid, hour);
  if (!pair) return null;
  const [w, s, e, n] = grid.bounds;
  if (longitude < w || longitude > e || latitude < s || latitude > n) return null;
  const x = (longitude - w) / (e - w) * (grid.columns - 1);
  const y = (mercator(n) - mercator(latitude)) / (mercator(n) - mercator(s)) * (grid.rows - 1);
  const a = bilinear(grid.frames[pair.a].values, grid.columns, grid.rows, x, y);
  const b = bilinear(grid.frames[pair.b].values, grid.columns, grid.rows, x, y);
  return a === null || b === null ? null : a + (b - a) * pair.mix;
}

export function waveColor(value, ramp = DEFAULT_WAVE_RAMP) {
  if (!Number.isFinite(value)) return [0, 0, 0, 0];
  let upper = ramp.findIndex((stop) => stop[0] >= value);
  if (upper < 0) upper = ramp.length - 1;
  const b = ramp[upper], a = ramp[Math.max(0, upper - 1)];
  const f = a[0] === b[0] ? 0 : Math.min(1, Math.max(0, (value - a[0]) / (b[0] - a[0])));
  return a.slice(1).map((v, i) => v + (b[i + 1] - v) * f);
}
