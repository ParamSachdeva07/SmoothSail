import { contours } from 'd3-contour';
import { framePair } from './waves.js';

const collection = (features = []) => ({ type: 'FeatureCollection', features });
const mercator = lat => Math.asinh(Math.tan(lat * Math.PI / 180));

// Display-only thresholds, not storm warnings, navigational limits or exclusions.
export function highSeasFeatures(grid, frameIndex) {
  const frame = grid.frames[frameIndex];
  const values = frame.values.map(v => Number.isFinite(v) && v >= 0 ? v : NaN);
  return contourFeatures(grid, values, frame.validAt, false);
}

// Contour the interpolated scalar field, rather than morphing unrelated polygon
// vertices. Regions can grow, split and disappear as the forecast changes.
export function highSeasAtHour(grid, hour) {
  const pair = framePair(grid, hour);
  if (!pair) return collection();
  if (pair.a === pair.b) return highSeasFeatures(grid, pair.a);
  const a = grid.frames[pair.a], b = grid.frames[pair.b];
  const values = Float64Array.from(a.values, (v, i) => Number.isFinite(v) && v >= 0 && Number.isFinite(b.values[i]) && b.values[i] >= 0
    ? v + (b.values[i] - v) * pair.mix : NaN);
  const validAt = new Date(Date.parse(a.validAt) + (hour - a.hour) * 3_600_000).toISOString();
  return contourFeatures(grid, values, validAt, true);
}

function contourFeatures(grid, values, validAt, interpolated) {
  const [west, south, east, north] = grid.bounds;
  const top = mercator(north), bottom = mercator(south);
  const coordinate = ([x, y]) => {
    const fx = Math.max(0, Math.min(1, (x - 0.5) / (grid.columns - 1)));
    const fy = Math.max(0, Math.min(1, (y - 0.5) / (grid.rows - 1)));
    return [west + fx * (east - west), Math.atan(Math.sinh(top + fy * (bottom - top))) * 180 / Math.PI];
  };
  const features = [];
  for (const contour of contours().size([grid.columns, grid.rows]).thresholds([4, 6])(values)) {
    for (const [index, polygon] of contour.coordinates.entries()) {
      const properties = { kind: 'high_seas', thresholdM: contour.value,
        validAt, interpolated, basis: `${interpolated ? 'Time-interpolated wave' : 'Wave'} forecast threshold; not a confirmed storm or official warning.` };
      features.push({ type: 'Feature', id: `${contour.value}-${index}`, properties,
        geometry: { type: 'Polygon', coordinates: polygon.map(ring => ring.map(coordinate)) } });
    }
  }
  return collection(features);
}

export function verifiedAreaNotices(overlays) {
  return (overlays?.features ?? []).filter(f => f.properties?.kind === 'restriction' &&
    f.properties.verified === true && !f.properties.cancelled && ['Polygon', 'MultiPolygon'].includes(f.geometry?.type));
}
export function activeAreaNotices(features, when) {
  const instant = Date.parse(when);
  return collection(features.filter(({ properties: p }) => {
    const from = p.validFrom ? Date.parse(p.validFrom) : -Infinity;
    const until = p.validTo ? Date.parse(p.validTo) : Infinity;
    return instant >= from && instant < until;
  }).map(f => ({ ...f, properties: { ...f.properties,
    label: `${f.properties.action === 'exclude' ? 'Restricted' : 'Area notice'} · ${f.properties.name || f.properties.id || 'Unnamed area'}` } })));
}
