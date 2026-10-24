import { DEFAULT_WAVE_RAMP, framePair, waveDisplayGrid, waveDisplayTime } from './waves.js';
import { cssToken } from '../settings.js';
import { createSeaContours } from './sea-contours.js';
import { createWaveGpuLayer } from './wave-gpu.js';
import { createWaveFrameCache } from './wave-cache.js';

function palette() {
  return DEFAULT_WAVE_RAMP.map(([height, r, g, b, alpha], i) => {
    const hex = cssToken(`--wave-${i}`, '').replace('#', '');
    return /^[0-9a-f]{6}$/i.test(hex) ? [height, ...[0, 2, 4].map(offset => parseInt(hex.slice(offset, offset + 2), 16)), alpha] : [height, r, g, b, alpha];
  });
}

export function createWaveOverlay(map, { beforeLayer, onError = () => {}, onHazards = () => {}, onDisplayState = () => {} }) {
  let sourceGrid = null, grid = null, layer = null, cache = null, contours = null, hour = 0;
  let active = true, visible = true, hazardsVisible = true, failed = false, previousState = '';
  function draw() {
    const time = waveDisplayTime(grid, hour);
    const pair = time ? framePair(grid, time.hour) : null, enabled = active && visible && !failed;
    cache?.update(pair, enabled);
    const ready = enabled && pair && cache?.ready();
    layer?.show(pair, Boolean(ready));
    const state = { status: failed ? 'error' : !grid || !pair ? 'unavailable' : ready ? 'ready' : 'loading', held: time?.held, validAt: time?.validAt };
    const key = JSON.stringify(state);
    if (key !== previousState) { previousState = key; onDisplayState(state); }
  }
  function fail() { failed = true; draw(); onError('Wave display could not load. Route estimates are unaffected.'); }
  function clear() {
    cache?.destroy(); cache = null; contours?.destroy(); contours = null; onHazards(null);
    if (layer && map.getLayer(layer.id)) map.removeLayer(layer.id);
    layer = null;
  }
  return {
    setGrid(next) {
      if (sourceGrid === next) return;
      sourceGrid = next;
      clear(); failed = false;
      grid = waveDisplayGrid(next);
      if (!grid) { draw(); return; }
      layer = createWaveGpuLayer(grid, fail); map.addLayer(layer, beforeLayer);
      const worker = new Worker(new URL('./waves.worker.js', import.meta.url), { type: 'module' });
      worker.postMessage({ type: 'init', grid: { columns: grid.columns, rows: grid.rows, bounds: grid.bounds }, ramp: palette() });
      cache = createWaveFrameCache(grid, { worker, layer, onReady: draw, onError: fail });
      contours = createSeaContours(grid, onHazards, onError, () => !map.isMoving());
      contours.setHour(waveDisplayTime(grid, hour).hour, true); contours.setActive(active && hazardsVisible);
      draw();
    },
    setHour(next, immediate = false) { hour = next; contours?.setHour(waveDisplayTime(grid, next)?.hour ?? next, immediate); draw(); },
    setVisible(next) { visible = next; draw(); },
    setActive(next) { active = next; contours?.setActive(active && hazardsVisible); draw(); },
    setHazardsVisible(next) { hazardsVisible = next; contours?.setActive(active && hazardsVisible); },
    destroy: clear
  };
}
