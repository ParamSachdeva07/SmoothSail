// WindOverlay — wind streamlines for the flat dot-matrix map.
//
// Scope: one isolated layer. It does not touch the globe, the land dots, the
// routing data or any other screen. It mounts only while the Wind toggle is
// on, and fully tears down (canvas removed, rAF cancelled) when toggled off.
//
// How it draws flow rather than marks:
//   1. A gridded vector field (below) gives a smooth, spatially coherent
//      direction + speed anywhere on the map — neighbours never jump.
//   2. Each streamline is INTEGRATED through that field: from a seed point we
//      step along the local direction and keep the whole path. The result is
//      one continuous curved line following the flow, not an isolated dash.
//   3. A brighter window travels along each path to animate drift.
//
// ONE COORDINATE SYSTEM. Paths are stored in lon/lat — the same world space
// the land dots live in — and every point is re-projected each frame with the
// map's own `map.project()`, which carries the map's current centre, zoom and
// pan offset. Nothing is cached in screen coordinates, so the streamlines
// move with the land dots and route line during a drag, not just after it.
//
// The canvas is cleared, never filled: the map's var(--c-bg) and the black
// land dots show through untouched, and the route line is drawn above this.

import { SETTINGS } from '../settings.js';

// Same green as the globe's land dots — single source of truth, one hue.
const WIND_COLOUR = SETTINGS.dotColor; // #0CFD03

const CONFIG = {
  // Light directional texture, not an ocean fill.
  streamlinesPerMegapixel: 104,
  maxStreamlines: 210,
  stepPixels: 7,            // integration step, in screen pixels
  minSteps: 6,              // short wisps where the air is calm …
  maxSteps: 40,             // … long streaks where it is strong
  headLength: 10,           // points lit by the travelling highlight

  // Contrast within the single hue. All four vary with local speed, so the
  // field reads as dense dark clusters against near-empty calm patches
  // rather than an even wash.
  calmKnots: 3,
  strongKnots: 28,
  minWidth: 0.6,
  maxWidth: 1.9,
  minBaseAlpha: 0.05,
  maxBaseAlpha: 0.6,
  minHeadAlpha: 0.1,
  maxHeadAlpha: 1,
  // Seeds are rejection-sampled against speed: calm cells mostly reject, so
  // lines concentrate where the wind is, without raising the total count.
  calmSeedChance: 0.1,
  seedOversample: 3
};

export function createWindOverlay({ map, container, field = createMockWindField() }) {
  const canvas = document.createElement('canvas');
  canvas.className = 'wind-overlay';
  const context = canvas.getContext('2d');

  let streamlines = [];
  let frame = null;
  let mounted = false;

  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

  function size() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const { clientWidth: width, clientHeight: height } = container;
    canvas.width = Math.max(1, Math.floor(width * ratio));
    canvas.height = Math.max(1, Math.floor(height * ratio));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { width, height };
  }

  function intensity(knots) {
    const t = (knots - CONFIG.calmKnots) / (CONFIG.strongKnots - CONFIG.calmKnots);
    const clamped = Math.max(0, Math.min(1, t));
    return clamped * clamped;      // eased, so calm really does fall away
  }

  const mix = (from, to, t) => from + (to - from) * t;

  // Integrate one path through the field. Seeded from a screen point, but the
  // result is stored as lon/lat only — never as screen coordinates.
  function trace(seedX, seedY, degreesPerPixel) {
    const start = map.unproject([seedX, seedY]);
    let lon = start.lng;
    let lat = start.lat;

    const strength = intensity(field.sample(lon, lat).knots);
    // Length scales with speed, so calm areas are short faint wisps.
    const steps = Math.round(mix(CONFIG.minSteps, CONFIG.maxSteps, strength));
    const stepDegrees = CONFIG.stepPixels * degreesPerPixel;

    const path = [];
    let speedSum = 0;
    for (let i = 0; i <= steps; i += 1) {
      path.push([lon, lat]);

      // Midpoint (RK2) step keeps curves smooth through turning flow.
      const a = field.sample(lon, lat);
      const aMagnitude = Math.hypot(a.u, a.v) || 1;
      const b = field.sample(
        lon + (a.u / aMagnitude) * stepDegrees * 0.5,
        lat + (a.v / aMagnitude) * stepDegrees * 0.5
      );
      const bMagnitude = Math.hypot(b.u, b.v) || 1;

      lon += (b.u / bMagnitude) * stepDegrees;
      lat += (b.v / bMagnitude) * stepDegrees;
      speedSum += b.knots;
      if (lat > 86 || lat < -86) break;
    }

    return { path, knots: speedSum / Math.max(1, path.length), phase: Math.random() };
  }

  function build() {
    const { width, height } = size();
    const target = Math.min(
      CONFIG.maxStreamlines,
      Math.round((width * height) / 1_000_000 * CONFIG.streamlinesPerMegapixel)
    );
    const degreesPerPixel = 360 / (512 * 2 ** map.getZoom());

    // Stratified seeding over an oversampled grid, then rejection-sampled by
    // local speed: even coverage, but weighted toward the windy regions.
    const candidates = target * CONFIG.seedOversample;
    const columns = Math.max(1, Math.round(Math.sqrt(candidates * (width / height))));
    const rows = Math.max(1, Math.round(candidates / columns));
    const cellWidth = width / columns;
    const cellHeight = height / rows;

    streamlines = [];
    for (let row = 0; row < rows && streamlines.length < target; row += 1) {
      for (let column = 0; column < columns && streamlines.length < target; column += 1) {
        const x = (column + 0.15 + Math.random() * 0.7) * cellWidth;
        const y = (row + 0.15 + Math.random() * 0.7) * cellHeight;
        const seed = map.unproject([x, y]);
        const strength = intensity(field.sample(seed.lng, seed.lat).knots);
        const chance = CONFIG.calmSeedChance + (1 - CONFIG.calmSeedChance) * strength;
        if (Math.random() > chance) continue;
        const line = trace(x, y, degreesPerPixel);
        if (line.path.length > 2) streamlines.push(line);
      }
    }
  }

  function strokePath(points, from, to, alpha, width) {
    if (alpha <= 0.015 || to - from < 1) return;
    context.strokeStyle = withAlpha(WIND_COLOUR, alpha);
    context.lineWidth = width;
    context.beginPath();
    context.moveTo(points[from].x, points[from].y);
    for (let i = from + 1; i <= to && i < points.length; i += 1) {
      context.lineTo(points[i].x, points[i].y);
    }
    context.stroke();
  }

  function render(timestamp) {
    const width = container.clientWidth;
    const height = container.clientHeight;
    context.clearRect(0, 0, width, height);
    context.lineCap = 'round';
    context.lineJoin = 'round';

    const seconds = timestamp / 1000;
    for (const line of streamlines) {
      // Re-project from lon/lat every frame with the map's own transform —
      // this is what keeps wind locked to the land dots while panning.
      const points = line.path.map(([lon, lat]) => map.project([lon, lat]));
      const strength = intensity(line.knots);
      const lineWidth = mix(CONFIG.minWidth, CONFIG.maxWidth, strength);

      strokePath(points, 0, points.length - 1,
        mix(CONFIG.minBaseAlpha, CONFIG.maxBaseAlpha, strength), lineWidth);

      if (!reduceMotion) {
        const cycle = (line.phase + seconds * (0.07 + strength * 0.16)) % 1;
        const head = Math.floor(cycle * points.length);
        strokePath(points, Math.max(0, head - CONFIG.headLength), head,
          mix(CONFIG.minHeadAlpha, CONFIG.maxHeadAlpha, strength), lineWidth);
      }
    }

    frame = window.requestAnimationFrame(render);
  }

  function restart() {
    build();
    if (reduceMotion) render(0);
  }

  // Re-seeding after a camera move keeps coverage even; the paths themselves
  // track the map continuously because they are projected every frame.
  const onMoveEnd = () => { if (mounted) restart(); };

  return {
    mount() {
      if (mounted) return;
      mounted = true;
      container.append(canvas);
      restart();
      map.on('moveend', onMoveEnd);
      if (!reduceMotion) frame = window.requestAnimationFrame(render);
    },

    unmount() {
      if (!mounted) return;
      mounted = false;
      if (frame) window.cancelAnimationFrame(frame);
      frame = null;
      map.off('moveend', onMoveEnd);
      canvas.remove();
    },

    // Called by the map's ResizeObserver: the canvas must match the new
    // container box and the seed density must be recomputed for it.
    resize() {
      if (mounted) restart();
    }
  };
}

function withAlpha(hex, alpha) {
  const value = hex.replace('#', '');
  return `rgba(${parseInt(value.slice(0, 2), 16)}, ${parseInt(value.slice(2, 4), 16)}, ${parseInt(value.slice(4, 6), 16)}, ${alpha.toFixed(3)})`;
}

// --- Wind field ----------------------------------------------------------
//
// PLACEHOLDER DATA, in the shape real data arrives in: a regular grid of
// { lat, lon, direction, speed } cells, bilinearly interpolated on sample so
// the field is smooth and spatially coherent everywhere between cells.
//
// The renderer only calls `field.sample(lon, lat)` and reads `{ u, v, knots }`.
// Swapping in the teammate's wind data means filling GRID from their response
// and nothing else. AUDIT-MVP.md §2.2 documents the live source — Open-Meteo /
// Copernicus wind read through `src/lib/ocean-data.ts`, returning MarinePoint
// samples — and `src/lib/ocean-field.ts` already interpolates a sparse grid
// the same way for ocean currents.

const GRID_STEP_DEGREES = 4;

export function createMockWindField() {
  const columns = Math.round(360 / GRID_STEP_DEGREES) + 1;
  const rows = Math.round(180 / GRID_STEP_DEGREES) + 1;
  const cells = new Float32Array(columns * rows * 2);

  for (let row = 0; row < rows; row += 1) {
    const lat = -90 + row * GRID_STEP_DEGREES;
    for (let column = 0; column < columns; column += 1) {
      const lon = -180 + column * GRID_STEP_DEGREES;
      const { u, v } = synthesise(lon, lat);
      cells[(row * columns + column) * 2] = u;
      cells[(row * columns + column) * 2 + 1] = v;
    }
  }

  function at(column, row, component) {
    const c = Math.max(0, Math.min(columns - 1, column));
    const r = Math.max(0, Math.min(rows - 1, row));
    return cells[(r * columns + c) * 2 + component];
  }

  return {
    // The grid itself, exposed in the shape real data would carry.
    gridStepDegrees: GRID_STEP_DEGREES,

    sample(lon, lat) {
      const wrapped = ((lon + 180) % 360 + 360) % 360 - 180;
      const x = (wrapped + 180) / GRID_STEP_DEGREES;
      const y = (Math.max(-90, Math.min(90, lat)) + 90) / GRID_STEP_DEGREES;
      const column = Math.floor(x);
      const row = Math.floor(y);
      const fx = x - column;
      const fy = y - row;

      const lerp = (component) => {
        const top = at(column, row, component) * (1 - fx) + at(column + 1, row, component) * fx;
        const bottom = at(column, row + 1, component) * (1 - fx) + at(column + 1, row + 1, component) * fx;
        return top * (1 - fy) + bottom * fy;
      };

      const u = lerp(0);
      const v = lerp(1);
      return { u, v, knots: Math.hypot(u, v) };
    }
  };
}

// Crude but recognisable global circulation, sampled into the grid above:
// tropical easterlies, mid-latitude westerlies, two long waves so the flow
// meanders into troughs and ridges, and damped calm belts at the equator and
// the horse latitudes.
function synthesise(lon, lat) {
  const waveA = Math.sin((lon * Math.PI) / 52 + (lat * Math.PI) / 44);
  const waveB = Math.cos((lon * Math.PI) / 31 - (lat * Math.PI) / 26);
  const phase = waveA * 0.65 + waveB * 0.35;

  const trades = -Math.cos((lat * Math.PI) / 22) * 14;
  const westerlies = Math.sin((Math.abs(lat) - 12) * Math.PI / 58) * 20;
  const u = (Math.abs(lat) < 28 ? trades : westerlies) + phase * 7;
  const v = waveA * 9 + waveB * 5 - Math.sin((lat * Math.PI) / 30) * 2.5;

  const doldrums = Math.exp(-((lat / 6) ** 2)) * 0.75;
  const horse = Math.exp(-(((Math.abs(lat) - 30) / 5) ** 2)) * 0.5;
  const damping = 1 - Math.min(0.85, doldrums + horse);

  return { u: u * damping, v: v * damping };
}
