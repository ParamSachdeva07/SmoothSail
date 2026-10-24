import { DEFAULT_WAVE_RAMP, framePair, validWaveGrid } from './waves.js';
import { cssToken } from '../settings.js';

function palette() {
  return DEFAULT_WAVE_RAMP.map(([height, r, g, b, alpha], i) => {
    const hex = cssToken(`--wave-${i}`, '').replace('#', '');
    return /^[0-9a-f]{6}$/i.test(hex) ? [height, ...[0, 2, 4].map((offset) => parseInt(hex.slice(offset, offset + 2), 16)), alpha] : [height, r, g, b, alpha];
  });
}
function imageCanvas(tile, pixels) {
  const canvas = document.createElement('canvas');
  canvas.width = tile.width; canvas.height = tile.height;
  canvas.getContext('2d').putImageData(new ImageData(pixels, tile.width, tile.height), 0, 0);
  return canvas;
}

export function createWaveOverlay(map, { beforeLayer, onError = () => {}, onHazards = () => {} }) {
  let grid = null, worker = null, hour = 0, visible = true, active = true, failed = false;
  const cache = new Map(), pending = new Set(), sources = [];
  function hide() { sources.forEach(({ id }) => map.setLayoutProperty(id, 'visibility', 'none')); }
  function request(pair) {
    if (!pair) return;
    const key = `${pair.a}:${pair.b}`;
    if (cache.has(key) || pending.has(key)) return;
    pending.add(key);
    worker.postMessage({ type: 'render', key, pair });
  }
  function draw() {
    if (!active || !grid || failed) { hide(); onHazards(null); return; }
    const pair = framePair(grid, hour);
    if (!pair) { hide(); onHazards(null); return; }
    const key = `${pair.a}:${pair.b}`;
    const entry = cache.get(key);
    if (!entry) { hide(); onHazards(null); request(pair); return; }
    // Cache only a few forecast pairs, and prepare the next interval ahead of playback.
    cache.delete(key); cache.set(key, entry);
    if (pair.b < grid.frames.length - 1) request({ a: pair.b, b: pair.b + 1 });
    onHazards(entry.hazards[pair.mix < 0.5 ? 0 : 1]);
    if (!visible) { hide(); return; }
    entry.tiles.forEach((tile, i) => {
      let source = sources[i];
      if (!source) {
        const canvas = document.createElement('canvas');
        canvas.width = tile.width; canvas.height = tile.height;
        source = { id: `voyage-waves-${i}`, canvas, context: canvas.getContext('2d') };
        sources.push(source);
        map.addSource(source.id, { type: 'canvas', canvas, animate: false, coordinates: tile.coordinates });
        map.addLayer({ id: source.id, type: 'raster', source: source.id,
          paint: { 'raster-resampling': 'linear', 'raster-fade-duration': 0, 'raster-opacity': 1 }
        }, beforeLayer);
      }
      const { context, canvas, id } = source;
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.globalCompositeOperation = 'source-over';
      context.globalAlpha = 1 - pair.mix;
      context.drawImage(tile.images[0], 0, 0);
      // Add premultiplied colours to avoid an opacity dip halfway between frames.
      context.globalCompositeOperation = 'lighter';
      context.globalAlpha = pair.mix;
      context.drawImage(tile.images[1], 0, 0);
      context.globalAlpha = 1; context.globalCompositeOperation = 'source-over';
      map.setLayoutProperty(id, 'visibility', 'visible');
      const live = map.getSource(id);
      live.play(); live.pause(); // Upload this frame; do not run a hidden repaint loop.
    });
    map.triggerRepaint();
  }
  function clear() {
    worker?.terminate(); worker = null;
    cache.clear(); pending.clear();
    sources.splice(0).forEach(({ id }) => { if (map.getLayer(id)) map.removeLayer(id); if (map.getSource(id)) map.removeSource(id); });
  }
  return {
    setGrid(next) {
      if (grid === next) return;
      clear(); failed = false;
      grid = validWaveGrid(next) ? next : null;
      if (!grid) return;
      worker = new Worker(new URL('./waves.worker.js', import.meta.url), { type: 'module' });
      worker.postMessage({ type: 'init', grid, ramp: palette() });
      worker.onmessage = ({ data }) => {
        pending.delete(data.key);
        if (data.error) { failed = true; hide(); onError('Wave display could not load. Route estimates are unaffected.'); return; }
        cache.set(data.key, { hazards: data.hazards, tiles: data.tiles.map((tile) => ({ ...tile, pixels: undefined, images: tile.pixels.map((pixels) => imageCanvas(tile, pixels)) })) });
        while (cache.size > 4) cache.delete(cache.keys().next().value);
        const pair = framePair(grid, hour);
        if (pair && data.key === `${pair.a}:${pair.b}`) draw();
      };
      worker.onerror = () => { failed = true; hide(); onError('Wave display could not load. Route estimates are unaffected.'); };
    },
    setHour(next) { hour = next; draw(); },
    setVisible(next) { visible = next; draw(); },
    setActive(next) { active = next; if (active) draw(); },
    destroy: clear
  };
}
