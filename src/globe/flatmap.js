// Flat dot-matrix map.
//
// Same engine, same land data as the globe: it reads the identical
// precomputed `/data/dots-*.geojson` point sets produced by
// scripts/generate-dots.mjs (Natural Earth 10m land rasterised to a 0.05°
// binary mask), and renders them as Mapbox circle layers. The only difference
// is the projection — `equirectangular` instead of `globe` — so there is no
// sphere and no curvature. No new land-detection logic exists here.
//
// Palette inverts for the flat view: off-white ground, black dots.

import mapboxgl from 'mapbox-gl';
import { SETTINGS, cssToken, cssDurationMs } from '../settings.js';
import { createWindOverlay } from './wind-overlay.js';

const FLAT = {
  // Design values come from src/tokens.css; the literals are fallbacks only.
  background: cssToken('--bg', '#FAFAFA'),
  dot: cssToken('--text', '#0A0A0A'),
  // Heavily simplified: two density levels only, so the map reads as a
  // diagram rather than a coastline survey. These are the *flat* lattices
  // (equal lon/lat steps, no stagger) — the globe's levels widen longitude
  // spacing by 1 / cos(latitude), which streaks under plate carrée.
  levels: SETTINGS.flatLevels,
  // Content bounds: the full lattice, minus the extreme polar rows that carry
  // almost no land. Panning is clamped to this.
  latitudeLimit: 164,          // total latitude span of the bounds, in degrees
  worldBounds: [[-180, -82], [180, 82]]
};

export function createFlatMap({ container }) {
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim();
  if (!token) return null;
  mapboxgl.accessToken = token;

  const map = new mapboxgl.Map({
    container,
    style: {
      version: 8,
      name: 'Flat Dot Matrix',
      sources: {},
      layers: [{
        id: 'flat-background',
        type: 'background',
        paint: { 'background-color': FLAT.background }
      }],
      projection: { name: 'equirectangular' }
    },
    projection: 'equirectangular',
    center: [55, 24],
    zoom: 1.1,
    minZoom: 0.6,
    maxZoom: 5.5,
    pitch: 0,
    bearing: 0,
    attributionControl: true,
    renderWorldCopies: false,
    fadeDuration: 0
  });

  if (import.meta.env.DEV) window.__flatMap = map;

  map.dragRotate.disable();
  map.touchZoomRotate.disableRotation();
  map.doubleClickZoom.disable();
  map.boxZoom.disable();
  map.scrollZoom.setWheelZoomRate(SETTINGS.zoomSensitivity / 450);
  map.scrollZoom.setZoomRate(SETTINGS.zoomSensitivity / 100);

  // Panning stops at the content edges.
  //
  // `setMaxBounds` is ignored under the equirectangular projection (Mapbox
  // only honours it in Mercator), so the camera is clamped directly on every
  // `move` — which covers the drag itself and the inertia that follows it,
  // in both axes. Latitude and longitude are both linear in this projection,
  // so an overshoot can be corrected by subtracting it from the centre.
  // `map.getBounds()` is not usable here: it saturates latitude at Mercator's
  // ±85.05°, so an overshoot past our ±82° content edge reads back as 85.05
  // and the correction never converges. The visible span is derived from zoom
  // instead — in plate carrée both axes share one scale, 360° across
  // 512 · 2^zoom pixels — and the centre is clamped arithmetically.
  let clamping = false;
  let lastLng = map.getCenter().lng;
  function clampCamera() {
    if (clamping) return;
    const [[west, south], [east, north]] = FLAT.worldBounds;
    const degreesPerPixel = 360 / (512 * 2 ** map.getZoom());
    const halfWidth = (container.clientWidth * degreesPerPixel) / 2;
    const halfHeight = (container.clientHeight * degreesPerPixel) / 2;
    const centre = map.getCenter();

    const clamp = (value, low, high) => (low > high
      ? (low + high) / 2                       // content narrower than the view
      : Math.min(high, Math.max(low, value)));

    // Longitude must be clamped on the *unwrapped* delta. Mapbox normalises
    // the centre into [-180, 180], so a drag past the antimeridian reads as a
    // jump to the opposite edge and would otherwise be clamped to the wrong
    // side — i.e. dragging west off the map would teleport you to the east.
    let delta = centre.lng - lastLng;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;

    const lng = clamp(lastLng + delta, west + halfWidth, east - halfWidth);
    const lat = clamp(centre.lat, south + halfHeight, north - halfHeight);
    lastLng = lng;

    if (Math.abs(lng - centre.lng) > 1e-9 || Math.abs(lat - centre.lat) > 1e-9) {
      clamping = true;
      map.stop();                                    // kill any remaining inertia
      map.setCenter([lng, lat]);
      clamping = false;
    }
  }
  map.on('move', clampCamera);

  // The world must never be narrower or shorter than the container, or there
  // would be empty space to pan into. Recomputed whenever the box changes.
  function applyFitConstraints() {
    const { clientWidth: width, clientHeight: height } = container;
    if (!width || !height) return;
    // Equirectangular: 512 px covers 360° of longitude at zoom 0, and the
    // visible latitude span is half that in pixels per degree.
    const forWidth = Math.log2(width / 512);
    const forHeight = Math.log2(height / (512 * (FLAT.latitudeLimit / 180)));
    const minZoom = Math.max(forWidth, forHeight);
    map.setMinZoom(Number(minZoom.toFixed(3)));
    if (map.getZoom() < minZoom) map.setZoom(minZoom);
  }

  const ready = new Promise((resolve) => map.on('load', () => resolve(map)));
  let wind = null;

  // Mapbox only tracks *window* resizes. A ResizeObserver catches every
  // container change — panel open, layout shift, devtools — and rebuilds the
  // canvas size, the zoom constraints and the dependent overlay together.
  const observer = new ResizeObserver(() => {
    map.resize();
    applyFitConstraints();
    wind?.resize();
  });
  observer.observe(container);
  ready.then(applyFitConstraints);

  map.on('load', () => {
    // --- Land dots ------------------------------------------------------
    for (const level of FLAT.levels) {
      const id = level.id;
      map.addSource(`flat-dots-${id}`, {
        type: 'geojson',
        data: `/data/dots-${id}.geojson`,
        maxzoom: 8,
        buffer: 32
      });
      const isOverview = id === 'flat-coarse';
      map.addLayer({
        id: `flat-dots-${id}-layer`,
        type: 'circle',
        source: `flat-dots-${id}`,
        minzoom: isOverview ? 0 : 1.9,
        maxzoom: isOverview ? 2.35 : 8,
        paint: {
          'circle-color': FLAT.dot,
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            0.6, level.radius * 0.85,
            2.5, level.radius * 1.45,
            5.5, level.radius * 2.1
          ],
          // Screen-aligned, so a dot is a true circle at every latitude.
          'circle-pitch-alignment': 'viewport',
          // Short, symmetrical crossfade so the map never looks half-drawn.
          'circle-opacity': isOverview
            ? ['interpolate', ['linear'], ['zoom'], 2.0, 1, 2.3, 0]
            : ['interpolate', ['linear'], ['zoom'], 2.0, 0, 2.3, 1]
        }
      });
    }

    // --- Overlay dot grids (placeholder data, same dot language) --------
    // Wind is handled separately by WindOverlay (animated streamlines).
    map.addSource('overlay-risk', { type: 'geojson', data: riskGrid() });
    map.addLayer({
      id: 'overlay-risk-layer',
      type: 'circle',
      source: 'overlay-risk',
      layout: { visibility: 'none' },
      paint: {
        'circle-color': cssToken('--accent-primary', '#FF00A1'),
        'circle-radius': 2.2,
        'circle-opacity': ['interpolate', ['linear'], ['get', 'severity'], 0, 0.25, 1, 0.9]
      }
    });

    // --- Alternate candidate routes -------------------------------------
    map.addSource('alt-routes', { type: 'geojson', data: emptyCollection() });
    map.addLayer({
      id: 'alt-routes-layer',
      type: 'line',
      source: 'alt-routes',
      layout: { visibility: 'none', 'line-cap': 'butt', 'line-join': 'miter' },
      paint: { 'line-color': cssToken('--accent-secondary', '#FFF200'), 'line-width': 1.25 }
    });

    // --- Selected route --------------------------------------------------
    map.addSource('route', { type: 'geojson', data: emptyCollection() });
    map.addLayer({
      id: 'route-layer',
      type: 'line',
      source: 'route',
      layout: { 'line-cap': 'butt', 'line-join': 'miter' },
      paint: { 'line-color': cssToken('--accent-primary', '#FF00A1'), 'line-width': 1.5 }
    });

    // --- Ports and vessel -------------------------------------------------
    map.addSource('ports', { type: 'geojson', data: emptyCollection() });
    map.addLayer({
      id: 'ports-layer',
      type: 'circle',
      source: 'ports',
      paint: {
        'circle-color': ['match', ['get', 'role'],
          'origin', cssToken('--accent-primary', '#FF00A1'),
          'destination', cssToken('--accent-primary', '#FF00A1'),
          cssToken('--text', '#0A0A0A')],
        'circle-radius': ['match', ['get', 'role'], 'stop', 2.5, 4],
        'circle-stroke-width': 1,
        'circle-stroke-color': FLAT.background
      }
    });

    map.addSource('vessel', { type: 'geojson', data: emptyCollection() });
    map.addLayer({
      id: 'vessel-layer',
      type: 'circle',
      source: 'vessel',
      paint: {
        'circle-color': cssToken('--vessel', '#FF0F13'),
        'circle-radius': 4.5,
        'circle-stroke-width': 1,
        'circle-stroke-color': FLAT.background
      }
    });
  });

  function setData(sourceId, data) {
    ready.then(() => map.getSource(sourceId)?.setData(data));
  }

  return {
    map,
    ready,
    resize: () => { map.resize(); applyFitConstraints(); wind?.resize(); },
    destroy: () => { observer.disconnect(); wind?.unmount(); map.remove(); },

    showRoute(route, { origin, destination, vesselAt = 0.38 }) {
      setData('route', lineCollection(route.coordinates));
      setData('ports', {
        type: 'FeatureCollection',
        features: [
          point(origin.coordinates, { role: 'origin', name: origin.name }),
          point(destination.coordinates, { role: 'destination', name: destination.name }),
          ...(route.stops ?? []).map((stop) => point(stop.coordinates, { role: 'stop', name: stop.name }))
        ]
      });
      setData('vessel', {
        type: 'FeatureCollection',
        features: [point(alongRoute(route.coordinates, vesselAt), { role: 'vessel' })]
      });
      ready.then(() => map.fitBounds(boundsOf(route.coordinates), {
        padding: { top: 90, right: 90, bottom: 150, left: 90 },
        duration: cssDurationMs('--camera-fit-duration', 900)
      }));
    },

    setAlternates(routes) {
      setData('alt-routes', {
        type: 'FeatureCollection',
        features: routes.map((route) => ({
          type: 'Feature',
          properties: { id: route.id },
          geometry: { type: 'LineString', coordinates: route.coordinates }
        }))
      });
    },

    setOverlay(id, visible) {
      // Wind is a mounted/unmounted canvas layer, not a style layer.
      if (id === 'wind') {
        ready.then(() => {
          if (!wind) wind = createWindOverlay({ map, container });
          if (visible) wind.mount(); else wind.unmount();
        });
        return;
      }
      const layerId = { risk: 'overlay-risk-layer', alternates: 'alt-routes-layer' }[id];
      ready.then(() => map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none'));
    },

    zoomBy(delta) {
      map.easeTo({ zoom: map.getZoom() + delta, duration: cssDurationMs('--camera-zoom-duration', 300) });
    }
  };
}

// --- Geometry helpers ----------------------------------------------------

function emptyCollection() {
  return { type: 'FeatureCollection', features: [] };
}

function lineCollection(coordinates) {
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates } }]
  };
}

function point(coordinates, properties) {
  return { type: 'Feature', properties, geometry: { type: 'Point', coordinates } };
}

function boundsOf(coordinates) {
  return coordinates.reduce(
    (bounds, coordinate) => bounds.extend(coordinate),
    new mapboxgl.LngLatBounds(coordinates[0], coordinates[0])
  );
}

// Position along the polyline by fraction of total planar length. Good enough
// for a demo glyph; the MVP's vessel-motion.ts does this on a great circle and
// never extrapolates past the last report.
function alongRoute(coordinates, fraction) {
  const spans = [];
  let total = 0;
  for (let i = 1; i < coordinates.length; i += 1) {
    const length = Math.hypot(
      coordinates[i][0] - coordinates[i - 1][0],
      coordinates[i][1] - coordinates[i - 1][1]
    );
    spans.push(length);
    total += length;
  }
  let travelled = total * fraction;
  for (let i = 0; i < spans.length; i += 1) {
    if (travelled <= spans[i]) {
      const t = spans[i] === 0 ? 0 : travelled / spans[i];
      return [
        coordinates[i][0] + (coordinates[i + 1][0] - coordinates[i][0]) * t,
        coordinates[i][1] + (coordinates[i + 1][1] - coordinates[i][1]) * t
      ];
    }
    travelled -= spans[i];
  }
  return coordinates[coordinates.length - 1];
}

// --- Placeholder overlay data -------------------------------------------
// PLACEHOLDER: a deterministic pseudo-field, not a forecast. The MVP fetches
// real Open-Meteo marine samples (AUDIT-MVP.md §2.2); wiring those in means
// replacing this function and nothing else. (Wind's placeholder field lives
// in wind-overlay.js alongside its renderer.)

function riskGrid() {
  // Flagged corridor: southern Red Sea, Bab al-Mandab and the Gulf of Aden.
  const zones = [
    { lonMin: 32, lonMax: 44, latMin: 12, latMax: 28, severity: 0.55 },
    { lonMin: 42, lonMax: 46, latMin: 11, latMax: 15, severity: 1 },
    { lonMin: 44, lonMax: 54, latMin: 10, latMax: 16, severity: 0.8 }
  ];
  const features = [];
  for (const zone of zones) {
    for (let lat = zone.latMin; lat <= zone.latMax; lat += 0.9) {
      for (let lon = zone.lonMin; lon <= zone.lonMax; lon += 0.9) {
        features.push(point([lon, lat], { severity: zone.severity }));
      }
    }
  }
  return { type: 'FeatureCollection', features };
}
