import { geometryLines } from './geometry.js';

const radians = (v) => v * Math.PI / 180;
const wrap = (v) => ((v + 180) % 360 + 360) % 360 - 180;
function distance(a, b) {
  const dLat = radians(b[1] - a[1]), dLon = radians(wrap(b[0] - a[0]));
  return 2 * Math.asin(Math.min(1, Math.sqrt(Math.sin(dLat / 2) ** 2 +
    Math.cos(radians(a[1])) * Math.cos(radians(b[1])) * Math.sin(dLon / 2) ** 2)));
}
function pathIndex(geometry) {
  const points = geometryLines(geometry).flat();
  const cumulative = [0];
  for (let i = 1; i < points.length; i++) cumulative.push(cumulative.at(-1) + distance(points[i - 1], points[i]));
  return { points, cumulative, length: cumulative.at(-1) ?? 0 };
}
function along(path, fraction) {
  if (!path.points.length) return null;
  if (!path.length || fraction <= 0) return path.points[0];
  if (fraction >= 1) return path.points.at(-1);
  const target = fraction * path.length;
  let low = 1, high = path.points.length - 1;
  while (low < high) { const mid = (low + high) >> 1; if (path.cumulative[mid] < target) low = mid + 1; else high = mid; }
  const a = path.points[low - 1], b = path.points[low];
  const span = path.cumulative[low] - path.cumulative[low - 1];
  const f = span ? (target - path.cumulative[low - 1]) / span : 0;
  // Interpolate on the returned polyline, including its shortest date-line seam.
  // Do not spline positions: that would cut canal corners or coastlines.
  return [wrap(a[0] + wrap(b[0] - a[0]) * f), a[1] + (b[1] - a[1]) * f];
}

export function createVoyageTrack(route, departureTime) {
  const departure = Date.parse(departureTime);
  const duration = route.durationHours;
  const fallback = pathIndex(route.geometry);
  const segments = (route.segments ?? []).map((segment) => ({
    start: (Date.parse(segment.entryTime) - departure) / 3_600_000,
    end: (Date.parse(segment.exitTime) - departure) / 3_600_000,
    kind: segment.kind, waveHeightM: segment.waveHeightM,
    path: pathIndex(segment.geometry)
  })).filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end >= s.start && s.path.points.length);
  return {
    duration,
    at(hour) {
      const bounded = Math.max(0, Math.min(duration, hour));
      if (!segments.length) return { coordinates: along(fallback, bounded / duration), kind: 'sailing' };
      let low = 0, high = segments.length - 1;
      while (low < high) { const mid = (low + high) >> 1; if (segments[mid].end < bounded) low = mid + 1; else high = mid; }
      const s = segments[low];
      const f = s.end > s.start ? Math.max(0, Math.min(1, (bounded - s.start) / (s.end - s.start))) : 1;
      return { coordinates: along(s.path, f), kind: s.kind ?? 'sailing', ...(Number.isFinite(s.waveHeightM) ? { waveHeightM: s.waveHeightM } : {}) };
    }
  };
}
