// Preserve the original dot-map design; all route geometry comes from the API.
import mapboxgl from 'mapbox-gl';
import { SETTINGS, cssToken, cssDurationMs } from '../settings.js';
import { routeFeature, routeBounds } from './geometry.js';

const empty = () => ({ type: 'FeatureCollection', features: [] });
const collection = (features) => ({ type: 'FeatureCollection', features });
const point = (coordinates, properties) => ({ type: 'Feature', properties, geometry: { type: 'Point', coordinates } });

export function createFlatMap({ container, onStatus = () => {} }) {
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim();
  if (!token) { onStatus('Add a Mapbox public token to display the map.'); return null; }
  mapboxgl.accessToken = token;
  const background = cssToken('--bg', '#FAFAFA');
  const map = new mapboxgl.Map({
    container,
    style: { version: 8, sources: {}, layers: [{ id: 'flat-background', type: 'background', paint: { 'background-color': background } }] },
    projection: 'equirectangular', center: [55, 24], zoom: 1.1, minZoom: -1, maxZoom: 8,
    pitch: 0, bearing: 0, attributionControl: true, renderWorldCopies: false, fadeDuration: 0
  });
  map.dragRotate.disable();
  map.touchZoomRotate.disableRotation();
  map.doubleClickZoom.disable();
  map.boxZoom.disable();
  map.scrollZoom.setWheelZoomRate(SETTINGS.zoomSensitivity / 450);
  map.scrollZoom.setZoomRate(SETTINGS.zoomSensitivity / 100);
  map.on('error', () => onStatus('Some map data could not load. Check your connection or Mapbox token.'));
  const ready = new Promise((resolve) => map.once('load', () => {
    for (const level of SETTINGS.flatLevels) {
      const id = `flat-dots-${level.id}`;
      const coarse = level.id === 'flat-coarse';
      map.addSource(id, { type: 'geojson', data: `/data/dots-${level.id}.geojson`, maxzoom: 8, buffer: 32 });
      map.addLayer({ id, type: 'circle', source: id, minzoom: coarse ? 0 : 1.9, maxzoom: coarse ? 2.35 : 24,
        paint: {
          'circle-color': cssToken('--text', '#0A0A0A'),
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 0.6, level.radius * 0.85, 2.5, level.radius * 1.45, 5.5, level.radius * 2.1],
          'circle-pitch-alignment': 'viewport',
          'circle-opacity': coarse ? ['interpolate', ['linear'], ['zoom'], 2, 1, 2.3, 0] : ['interpolate', ['linear'], ['zoom'], 2, 0, 2.3, 1]
        }
      });
    }
    for (const [id, color, width] of [
      ['alt-routes', cssToken('--accent-secondary', '#FFF200'), 2.5],
      ['route', cssToken('--accent-primary', '#FF00A1'), 1.8]
    ]) {
      // tolerance 0 retains narrow canal turns; no interpolated display curve.
      map.addSource(id, { type: 'geojson', data: empty(), tolerance: 0 });
      map.addLayer({ id: `${id}-layer`, type: 'line', source: id,
        layout: { 'line-cap': 'round', 'line-join': 'round', visibility: id === 'route' ? 'visible' : 'none' },
        paint: { 'line-color': color, 'line-width': width }
      });
    }
    map.addSource('ports', { type: 'geojson', data: empty() });
    map.addLayer({ id: 'ports-layer', type: 'circle', source: 'ports', paint: {
      'circle-color': cssToken('--accent-primary', '#FF00A1'), 'circle-radius': 5,
      'circle-stroke-width': 1, 'circle-stroke-color': background
    } });
    onStatus('');
    resolve();
  }));
  let latestRoute = null;
  let revision = 0;
  const markers = [];
  function fit() {
    if (!latestRoute || !container.clientWidth || !container.clientHeight) return;
    const mobile = container.clientWidth < 900;
    map.fitBounds(routeBounds(latestRoute.geometry), {
      padding: { top: 150, right: mobile ? 30 : 240, bottom: mobile ? 255 : 180, left: mobile ? 30 : 65 },
      maxZoom: 6, duration: cssDurationMs('--camera-fit-duration', 900)
    });
  }
  const observer = new ResizeObserver(() => { map.resize(); if (latestRoute && container.clientWidth) fit(); });
  observer.observe(container);

  return {
    resize: () => map.resize(),
    destroy: () => { observer.disconnect(); markers.forEach((marker) => marker.remove()); map.remove(); },
    showRoute(route, { origin, destination }) {
      latestRoute = route;
      const current = ++revision;
      return ready.then(() => {
        if (revision !== current) return;
        map.getSource('route').setData(collection([routeFeature(route)]));
        const ports = [{ ...origin, role: 'origin' }, { ...destination, role: 'destination' }];
        map.getSource('ports').setData(collection(ports.map((port) => point(port.coordinates, { role: port.role, name: port.name }))));
        markers.splice(0).forEach((marker) => marker.remove());
        ports.forEach((port, i) => {
          const label = document.createElement('span');
          label.className = 'map-port-label';
          label.textContent = `${i ? 'B' : 'A'} · ${port.name}`;
          markers.push(new mapboxgl.Marker({ element: label, anchor: 'bottom', offset: [0, -10] }).setLngLat(port.coordinates).addTo(map));
        });
        fit();
      });
    },
    setAlternates(routes) { ready.then(() => map.getSource('alt-routes').setData(collection(routes.map(routeFeature)))); },
    setOverlay(id, visible) {
      if (id === 'alternates') ready.then(() => map.setLayoutProperty('alt-routes-layer', 'visibility', visible ? 'visible' : 'none'));
    },
    fitRoute: fit,
    zoomBy(delta) { map.easeTo({ zoom: map.getZoom() + delta, duration: cssDurationMs('--camera-zoom-duration', 300) }); }
  };
}
