import { validWaveGrid } from './waves.js';

const mercator = latitude => Math.asinh(Math.tan(latitude * Math.PI / 180));
const latitude = y => Math.atan(Math.sinh(y)) * 180 / Math.PI;
const limit = 85.0511287798066;
export const WORLD_BOUNDS = [[-180, -limit], [180, limit]];

// Keep a stable extent throughout playback. Trim only wholly empty polar rows;
// missing cells within this envelope remain unknown, including land and ice.
export function forecastMapBounds(grid) {
  if (!validWaveGrid(grid)) return WORLD_BOUNDS;
  const [west, south, east, north] = grid.bounds;
  if (west < -180 || east > 180 || south < -limit || north > limit) return WORLD_BOUNDS;
  let first = grid.rows, last = -1;
  const hasData = (values, row) => {
    const end = (row + 1) * grid.columns;
    for (let i = row * grid.columns; i < end; i++) {
      if (Number.isFinite(values[i]) && values[i] >= 0) return true;
    }
    return false;
  };
  for (const { values } of grid.frames) {
    for (let row = 0; row < first; row++) {
      if (hasData(values, row)) { first = row; break; }
    }
    for (let row = grid.rows - 1; row > last; row--) {
      if (hasData(values, row)) { last = row; break; }
    }
  }
  // A missing or single-row forecast cannot define a navigable map envelope.
  if (first >= last) return WORLD_BOUNDS;
  const top = mercator(north), span = mercator(south) - top;
  const rowLatitude = row => latitude(top + span * row / (grid.rows - 1));
  return [[west, rowLatitude(last)], [east, rowLatitude(first)]];
}

// At zoom 0 a Mercator world is 512 px. Fit the entire viewport INSIDE the
// forecast envelope, rather than fitting the envelope inside the viewport.
export function minimumCoverageZoom(bounds, width, height) {
  const [[west, south], [east, north]] = bounds;
  const xSpan = (east - west) / 360;
  const ySpan = (mercator(north) - mercator(south)) / (2 * Math.PI);
  return Math.max(0, Math.log2(Math.max(width / (512 * xSpan), height / (512 * ySpan))));
}
