import { icon } from '../icons.js';
import { createFlatMap } from '../../globe/flatmap.js';
import { getReport, getRoutes, findRoute, reportPort, formatDuration, formatNm, formatUsd, coverageLabel, formatNumber } from '../../data/routes.js';
import { formatEta } from '../../data/shipment.js';

export function createDetailScreen({ getSelectedRouteId, onBack }) {
  const element = document.createElement('section');
  element.className = 'screen detail';
  element.id = 'screen-detail';
  element.innerHTML = `
    <div class="flatmap" id="flatmap" aria-label="Selected maritime route map"></div>
    <div class="detail__layout">
      <header class="detail__head">
        <div><h1 class="wordmark">SmoothSail</h1><p class="mono-label" data-role="route-name"></p><p class="mono-label map-status" role="status"></p></div>
        <button class="button button--quiet" type="button" data-action="back">${icon('arrow-left')}<span>All routes</span></button>
      </header>
      <div class="detail__middle">
        <dl class="legend">
          <div><dt><i class="dot dot--accent"></i></dt><dd class="mono-label">Port approaches · A to B</dd></div>
          <div><dt><i class="line line--accent"></i></dt><dd class="mono-label">Selected route</dd></div>
          <div><dt><i class="line line--alternate"></i></dt><dd class="mono-label">Other routes · may overlap</dd></div>
        </dl>
        <div class="controls">
          <div class="toggles">
            <p class="toggles__title mono-label">${icon('layers')}<span>Overlays</span></p>
            <label class="toggle" title="Wind direction data is not supplied by this API"><input type="checkbox" disabled><span>Wind prediction</span></label>
            <label class="toggle" title="Conflict screening is not connected"><input type="checkbox" disabled><span>Conflict zones</span></label>
            <label class="toggle"><input type="checkbox" data-overlay="alternates"><span>Other routes</span></label>
            <p class="toggles__note mono-label">Wind / conflict layers unavailable</p>
          </div>
          <div class="zoom">
            <button class="button button--quiet" type="button" data-action="fit">Fit route</button>
            <button class="button button--quiet button--icon" type="button" data-action="zoom-in" aria-label="Zoom in">${icon('plus')}</button>
            <button class="button button--quiet button--icon" type="button" data-action="zoom-out" aria-label="Zoom out">${icon('minus')}</button>
          </div>
        </div>
      </div>
      <div class="detail__footer">
        <div class="infostrip">
          <dl class="metrics metrics--strip">
            <div class="metric"><dt class="mono-label">Transit</dt><dd class="metric__value" data-role="duration"></dd></div>
            <div class="metric"><dt class="mono-label">Distance</dt><dd class="metric__value" data-role="distance"></dd></div>
            <div class="metric"><dt class="mono-label">Est. voyage cost</dt><dd class="metric__value" data-role="cost"></dd></div>
            <div class="metric"><dt class="mono-label">ETA · UTC</dt><dd class="metric__value metric__value--eta" data-role="arrival"></dd></div>
          </dl>
          <div class="infostrip__actions"><button class="button button--quiet" type="button" disabled title="Route information is coming soon">${icon('info')}<span>More info</span></button></div>
        </div>
        <p class="detail__credit mono-label" data-role="coverage"></p>
        <p class="detail__credit mono-label">Map Mapbox · Land Natural Earth 1:10m · Planning estimate, not for navigation · Compliance not assessed</p>
      </div>
    </div>`;
  let flat = null;
  element.addEventListener('change', (event) => {
    if (event.target.dataset.overlay) flat?.setOverlay(event.target.dataset.overlay, event.target.checked);
  });
  element.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action === 'back') onBack?.();
    if (action === 'zoom-in') flat?.zoomBy(0.6);
    if (action === 'zoom-out') flat?.zoomBy(-0.6);
    if (action === 'fit') flat?.fitRoute();
  });
  function render(route) {
    const report = getReport();
    const origin = reportPort(report, 'origin');
    const destination = reportPort(report, 'destination');
    const text = (role, value) => { element.querySelector(`[data-role="${role}"]`).textContent = value; };
    text('route-name', `${route.label} · ${route.name} · ${origin.name} → ${destination.name}`);
    text('duration', formatDuration(route.durationHours));
    text('distance', formatNm(route.distanceNm));
    text('cost', formatUsd(route.cost?.totalUsd, { compact: true }));
    text('arrival', formatEta(route.eta));
    text('coverage', `${coverageLabel(route)} · Uncovered conditions are unknown · ${formatNumber(route.emissions?.co2Tonnes)} t CO₂ · ${formatNumber(route.cost?.fuelTonnes)} t fuel · Whole-vessel voyage cost`);
    element.querySelector('[data-overlay="alternates"]').checked = false;
    flat?.setOverlay('alternates', false);
    flat?.setAlternates(getRoutes().filter((candidate) => candidate.id !== route.id));
    flat?.showRoute(route, { origin, destination });
  }
  return {
    element, showGlobe: false,
    enter() {
      const status = element.querySelector('.map-status');
      if (!flat) {
        status.textContent = 'Loading map…';
        try { flat = createFlatMap({ container: element.querySelector('#flatmap'), onStatus: (message) => { status.textContent = message; } }); }
        catch { status.textContent = 'Map rendering is unavailable in this browser. Route estimates are shown below.'; }
      }
      flat?.resize();
      const route = findRoute(getSelectedRouteId());
      if (route) render(route);
    }
  };
}
