import { framePair } from './waves.js';

// One request in flight, latest time wins. A dedicated worker keeps contours
// moving even while the raster worker prepares a new pair of blurred textures.
export function createSeaContours(grid, onData, onError = () => {}, canUpdate = () => true) {
  const worker = new Worker(new URL('./sea-contours.worker.js', import.meta.url), { type: 'module' });
  worker.postMessage({ type: 'init', grid: { columns: grid.columns, rows: grid.rows, bounds: grid.bounds } });
  let hour = 0, active = false, busy = false, timer = null, revision = 0, failed = false;
  let sentKey = '', sentHour = null, lastSent = -Infinity;
  const keyFor = pair => `${pair.a}:${pair.b}`;
  function request() {
    if (!active || busy || failed || timer !== null) return;
    const pair = framePair(grid, hour);
    if (!pair || hour === sentHour) return;
    // Retiling global GeoJSON at 30 Hz competed with camera animation. Keep
    // the current geometry attached to the map during a zoom, then catch up.
    const remaining = canUpdate() ? 1000 / 12 - (performance.now() - lastSent) : 100;
    if (remaining > 0) {
      timer = setTimeout(() => { timer = null; request(); }, remaining);
      return;
    }
    const key = keyFor(pair);
    // Send only the current interval, not another copy of the entire global forecast.
    const frames = key === sentKey ? undefined : [grid.frames[pair.a], ...(pair.b === pair.a ? [] : [grid.frames[pair.b]])];
    busy = true; sentKey = key; sentHour = hour; lastSent = performance.now();
    worker.postMessage({ key, hour, revision, frames });
  }
  const fail = () => { failed = true; onData(null); onError('High-sea outlines could not load. Wave colours and route estimates are unaffected.'); };
  worker.onerror = fail;
  worker.onmessage = ({ data }) => {
    busy = false;
    if (data.error) { fail(); return; }
    const pair = framePair(grid, hour);
    if (active && data.revision === revision && pair && data.key === keyFor(pair)) onData(data.features);
    request();
  };
  return {
    setHour(next, immediate = false) {
      if (immediate) { revision++; sentHour = null; }
      hour = next;
      if (!framePair(grid, hour)) { revision++; onData(null); return; }
      request();
    },
    setActive(next) {
      if (active === next) return;
      active = next; revision++; sentHour = null;
      if (active) request();
      else { clearTimeout(timer); timer = null; onData(null); }
    },
    destroy() { clearTimeout(timer); worker.terminate(); }
  };
}
