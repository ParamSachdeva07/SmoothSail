// Quiet Mapbox Light basemap for the selected route; the landing globe stays dotted.
import mapboxgl from 'mapbox-gl';
import { SETTINGS, cssToken, cssDurationMs } from '../settings.js';
import { routeFeature, routeBounds } from './geometry.js';
import { createWaveOverlay } from './wave-overlay.js';
import { createVoyagePlayer } from './voyage-player.js';
import { createHazardOverlay } from './hazard-overlay.js';
import { createSmoothZoom } from './smooth-zoom.js';

const empty = () => ({ type: 'FeatureCollection', features: [] });
const collection = (features) => ({ type: 'FeatureCollection', features });
const point = (coordinates, properties) => ({ type: 'Feature', properties, geometry: { type: 'Point', coordinates } });

export function createFlatMap({ container, onStatus = () => {}, onVoyageTick = () => {}, onPlaybackState = () => {}, onNotices = () => {}, onWaveState = () => {} }) {
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim();
  if (!token) { onStatus('Add a Mapbox public token to display the map.'); return null; }
  mapboxgl.accessToken = token;
  const background = cssToken('--bg', '#FAFAFA');
  const map = new mapboxgl.Map({
    container,
    style: 'mapbox://styles/mapbox/light-v11',
    // Keep the map and forecast canvas in the same projection so coastal
    // samples and vector hazard contours remain geographically aligned.
    projection: 'mercator', center: [55, 24], zoom: 1.1, minZoom: 0, maxZoom: 8,
    maxBounds: [[-180, -85.051129], [180, 85.051129]],
    pitch: 0, bearing: 0, attributionControl: true, renderWorldCopies: false, fadeDuration: 0
  });
  map.dragRotate.disable();
  map.touchZoomRotate.disableRotation();
  map.doubleClickZoom.disable();
  map.boxZoom.disable();
  const zoom = createSmoothZoom(map, { sensitivity: SETTINGS.zoomSensitivity });
  map.on('error', () => onStatus('Some map data could not load. Check your connection or Mapbox token.'));
  let waves = null, player = null, hazards = null, departure = null;
  let active = true, coastReady = false;
  map.on('sourcedata', (event) => {
    if (!coastReady && event.sourceId === 'coast-mask' && event.isSourceLoaded) {
      coastReady = true;
      waves?.setActive(active);
    }
  });
  const ready = new Promise((resolve) => map.once('load', () => {
    map.setPaintProperty('land', 'background-color', background);
    map.setPaintProperty('water', 'fill-color', cssToken('--map-water', '#F0F3F4'));
    map.setPaintProperty('water', 'fill-outline-color', cssToken('--map-coast', '#CDD6D8'));
    // Keep boundary lines and useful local labels, without country names or
    // city-level visual noise competing with the voyage and weather field.
    for (const layer of map.getStyle().layers) {
      if (['road', 'building', 'aeroway', 'poi_label'].includes(layer['source-layer']) ||
          layer['source-layer'] === 'place_label' ||
          ['country-label', 'continent-label', 'airport-label', 'settlement-subdivision-label', 'settlement-minor-label', 'settlement-major-label'].includes(layer.id)) {
        map.setLayoutProperty(layer.id, 'visibility', 'none');
      }
      if (layer.type === 'symbol') {
        map.setPaintProperty(layer.id, 'text-color', cssToken('--map-label', '#8A959A'));
        map.setPaintProperty(layer.id, 'text-halo-color', background);
      }
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
    // Above the water fill, beneath the basemap's structures, boundaries, labels
    // and our route. Do not let the opaque water fill cover the forecast raster.
    map.addSource('coast-mask', { type: 'geojson', data: `${import.meta.env.BASE_URL}data/land-mask.geojson`,
      tolerance: 0.5, attribution: '<a href="https://github.com/GenericMappingTools/gshhg-gmt">GSHHG</a>' });
    map.addLayer({ id: 'wave-shore-fade', type: 'line', source: 'coast-mask', paint: {
      'line-color': background, 'line-width': ['interpolate', ['linear'], ['zoom'], 0, 3, 5, 10, 8, 18],
      'line-blur': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 4, 8, 7]
    } }, 'land-structure-polygon');
    map.addLayer({ id: 'wave-land-mask', type: 'fill', source: 'coast-mask', paint: {
      'fill-color': background, 'fill-opacity': 1
    } }, 'land-structure-polygon');
    hazards = createHazardOverlay(map, { beforeLayer: 'route-layer', onNotices });
    waves = createWaveOverlay(map, { beforeLayer: 'wave-shore-fade', onError: onStatus, onHazards: data => hazards.setSeas(data), onDisplayState: onWaveState });
    player = createVoyagePlayer(map, {
      onTime: (hour, immediate) => waves.setHour(hour, immediate),
      onTick: (state) => {
        if (departure) hazards.setTime(new Date(Date.parse(departure) + state.hour * 3_600_000).toISOString());
        onVoyageTick(state);
      },
      onState: onPlaybackState
    });
    onStatus('');
    resolve();
  }));
  let latestRoute = null;
  let revision = 0;
  const markers = [];
  function fit() {
    if (!latestRoute || !container.clientWidth || !container.clientHeight) return;
    zoom.reset();
    const mobile = container.clientWidth < 900;
    map.fitBounds(routeBounds(latestRoute.geometry), {
      padding: { top: 150, right: mobile ? 30 : 240, bottom: Math.max(mobile ? 270 : 230, (container.parentElement.querySelector('.detail__footer')?.offsetHeight ?? 180) + 65), left: mobile ? 30 : 65 },
      retainPadding: false,
      maxZoom: 6, duration: cssDurationMs('--camera-fit-duration', 900)
    });
  }
  function resize() {
    const { clientWidth: width, clientHeight: height } = container;
    if (!width || !height) return;
    map.resize();
    // Mercator's world is 512px at zoom zero. Keep it at least as large as
    // both viewport dimensions; world bounds also prevent panning into blank space.
    const minimum = Math.max(0, Math.log2(Math.max(width, height) / 512));
    if (Math.abs(map.getMinZoom() - minimum) > 0.001) map.setMinZoom(minimum);
  }
  const observer = new ResizeObserver(() => { resize(); if (latestRoute && container.clientWidth) fit(); });
  observer.observe(container);
  resize();

  return {
    resize,
    destroy: () => { player?.destroy(); waves?.destroy(); hazards?.destroy(); zoom.destroy(); observer.disconnect(); markers.forEach((marker) => marker.remove()); map.remove(); },
    showRoute(route, { origin, destination, departureTime, waveGrid, overlays }) {
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
        departure = departureTime;
        hazards.setNotices(overlays);
        hazards.setVisible('hazards', true);
        hazards.setVisible('restrictions', true);
        waves.setGrid(waveGrid);
        waves.setHazardsVisible(true);
        waves.setActive(active && coastReady);
        waves.setVisible(true);
        player.setActive(active);
        player.load(route, departureTime);
        fit();
      });
    },
    setAlternates(routes) { ready.then(() => map.getSource('alt-routes').setData(collection(routes.map(routeFeature)))); },
    setOverlay(id, visible) {
      if (id === 'waves') ready.then(() => waves.setVisible(visible));
      if (id === 'alternates') ready.then(() => map.setLayoutProperty('alt-routes-layer', 'visibility', visible ? 'visible' : 'none'));
      if (id === 'hazards' || id === 'restrictions') ready.then(() => {
        hazards.setVisible(id, visible);
        if (id === 'hazards') waves.setHazardsVisible(visible);
      });
    },
    setActive(next) { active = next; player?.setActive(next); waves?.setActive(next && coastReady); },
    togglePlayback() { player?.toggle(); },
    restartPlayback() { player?.restart(); },
    seekVoyage(fraction) { player?.seek(fraction); },
    fitRoute: fit,
    zoomBy: zoom.zoomBy
  };
}
