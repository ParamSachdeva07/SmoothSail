// Dot-matrix globe engine.
//
// Moved verbatim out of src/main.js so the app shell can own the page and the
// globe can be mounted/queried as a module. The rendering maths — projection,
// LOD fade stops, radius interpolation, drag/zoom tuning and the auto-rotation
// loop — is unchanged from the audited prototype. Do not edit it casually.

import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import '../globe.css';
import { SETTINGS, cssDurationMs } from '../settings.js';

export function createGlobe({ container, onStatus = () => {} }) {
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim();
  if (!token) {
    onStatus('Mapbox token missing. Copy .env.example to .env.local, add your public token, then restart the dev server.');
    return null;
  }
  mapboxgl.accessToken = token;

  const loadedLevels = new Set();
  let lastAutoRotateAt = 0;
  let autoRotateEnabled = SETTINGS.autoRotate;

  const map = new mapboxgl.Map({
    container,
    style: {
      version: 8,
      name: 'Minimal Dot Globe',
      sources: {},
      layers: [{
        id: 'sphere-background',
        type: 'background',
        paint: { 'background-color': SETTINGS.backgroundColor }
      }],
      projection: { name: 'globe' }
    },
    projection: 'globe',
    center: [SETTINGS.initialLongitude, SETTINGS.initialLatitude],
    zoom: SETTINGS.initialZoom,
    minZoom: SETTINGS.minZoom,
    maxZoom: SETTINGS.maxZoom,
    pitch: 0,
    bearing: 0,
    attributionControl: true,
    renderWorldCopies: false,
    interactive: true,
    cooperativeGestures: false,
    fadeDuration: 0,
    trackResize: true
  });
  if (import.meta.env.DEV) window.__dotGlobeMap = map;

  map.dragPan.disable();
  map.dragPan.enable({
    linearity: SETTINGS.rotationSensitivity,
    maxSpeed: 1200,
    deceleration: 1400 * (1 / SETTINGS.inertia)
  });
  map.dragRotate.disable();
  map.touchZoomRotate.enable({ around: 'center' });
  map.touchZoomRotate.disableRotation();
  map.scrollZoom.enable();
  map.scrollZoom.setWheelZoomRate(SETTINGS.zoomSensitivity / 450);
  map.scrollZoom.setZoomRate(SETTINGS.zoomSensitivity / 100);
  map.doubleClickZoom.disable();
  map.boxZoom.disable();
  map.keyboard.disable();

  map.on('load', () => {
    onStatus('');
    map.setProjection('globe');
    map.setFog({
      color: SETTINGS.backgroundColor,
      'high-color': SETTINGS.backgroundColor,
      'space-color': SETTINGS.screenBackgroundColor,
      'horizon-blend': 0,
      'star-intensity': 0
    });
    loadDensityThrough(map.getZoom() + 0.8);
    map.on('zoom', () => loadDensityThrough(map.getZoom() + 0.8));
    if (SETTINGS.autoRotate) initializeAutoRotate();
  });

  map.on('error', (event) => {
    console.error('Mapbox globe error:', event.error ?? event);
    if (event.error?.status === 401 || event.error?.status === 403) {
      onStatus('Mapbox rejected this token. Check that it is valid and allowed for this site origin.');
    }
  });

  function addDensityLevel(level) {
    if (loadedLevels.has(level.id)) return;
    loadedLevels.add(level.id);
    const sourceId = `land-dots-${level.id}`;
    const layerId = `${sourceId}-layer`;
    map.addSource(sourceId, {
      type: 'geojson',
      data: `/data/dots-${level.id}.geojson`,
      maxzoom: 8,
      buffer: 32
    });

    map.addLayer({
      id: layerId,
      type: 'circle',
      source: sourceId,
      minzoom: level.fade[0],
      maxzoom: level.fade[3] + 0.01,
      paint: {
        'circle-color': SETTINGS.dotColor,
        'circle-radius': [
          'interpolate', ['linear'], ['zoom'],
          level.fade[0], level.radius * 1.12,
          (level.fade[1] + level.fade[2]) / 2, level.radius,
          level.fade[3], level.radius * 0.88
        ],
        'circle-opacity': [
          'interpolate', ['linear'], ['zoom'],
          level.fade[0], 0,
          level.fade[1], 1,
          level.fade[2], 1,
          level.fade[3], 0
        ],
        'circle-pitch-alignment': 'map',
        'circle-pitch-scale': 'map'
      }
    });
  }

  function loadDensityThrough(zoom) {
    for (const level of SETTINGS.levels) {
      if (zoom >= level.fade[0]) addDensityLevel(level);
    }
  }

  function initializeAutoRotate() {
    map.on('render', autoRotate);

    // Any direct manipulation pauses rotation and leaves the user in control.
    map.on('mousedown', pauseAutoRotate);
    map.on('touchstart', pauseAutoRotate);
    map.on('zoomstart', pauseAutoRotate);

    // Auto-rotation returns only after the user reaches the full-globe zoom.
    map.on('zoomend', resumeAutoRotateAtMinimumZoom);
    map.getCanvas().addEventListener('wheel', resumeAutoRotateFromMinimumZoom, { passive: true });
    map.triggerRepaint();
  }

  function pauseAutoRotate() {
    autoRotateEnabled = false;
    lastAutoRotateAt = 0;
  }

  function resumeAutoRotateAtMinimumZoom() {
    if (map.getZoom() <= SETTINGS.minZoom + SETTINGS.autoRotateResumeZoomTolerance) {
      autoRotateEnabled = true;
      lastAutoRotateAt = 0;
      map.triggerRepaint();
    }
  }

  function resumeAutoRotateFromMinimumZoom(event) {
    const isZoomingOut = event.deltaY > 0;
    if (isZoomingOut) resumeAutoRotateAtMinimumZoom();
  }

  function autoRotate() {
    if (!autoRotateEnabled || map.isMoving()) {
      lastAutoRotateAt = 0;
      return;
    }
    const timestamp = performance.now();
    if (!lastAutoRotateAt) {
      lastAutoRotateAt = timestamp;
      map.triggerRepaint();
      return;
    }
    const elapsed = Math.min(50, timestamp - lastAutoRotateAt);
    lastAutoRotateAt = timestamp;
    const center = map.getCenter();
    // A decreasing camera longitude makes the globe itself rotate eastward,
    // matching Earth's west-to-east rotation.
    const nextLongitude = wrapLongitude(center.lng - SETTINGS.autoRotateSpeed * elapsed / 1000);
    map.setCenter([nextLongitude, center.lat]);
  }

  return {
    map,
    // Ease-rotate the globe toward a region, e.g. when a port is selected.
    flyToRegion([longitude, latitude], zoom = SETTINGS.initialZoom) {
      pauseAutoRotate();
      map.easeTo({ center: [longitude, latitude], zoom, duration: cssDurationMs('--camera-ease-duration', 1600), easing: (t) => 1 - Math.pow(1 - t, 3) });
    },
    pauseAutoRotate,
    resumeAutoRotate: resumeAutoRotateAtMinimumZoom
  };
}

function wrapLongitude(longitude) {
  return ((longitude + 180) % 360 + 360) % 360 - 180;
}
