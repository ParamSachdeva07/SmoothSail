import { icon } from '../icons.js';
import { createFlatMap } from '../../globe/flatmap.js';
import { getReport, getRoutes, findRoute, reportPort, formatDuration, formatNm, formatUsd, formatNumber } from '../../data/routes.js';
import { formatEta } from '../../data/shipment.js';
import { validWaveGrid } from '../../globe/waves.js';

export function createDetailScreen({ getSelectedRouteId, onBack }) {
  const element = document.createElement('section');
  element.className = 'screen detail';
  element.id = 'screen-detail';
  element.innerHTML = `
    <div class="flatmap" id="flatmap" aria-label="Selected maritime route map"></div>
    <div class="detail__layout">
      <header class="detail__head">
        <div><h1 class="wordmark">SmoothSail</h1><p class="mono-label map-status" role="status"></p></div>
        <button class="button button--quiet" type="button" data-action="back">${icon('arrow-left')}<span>All routes</span></button>
      </header>
      <div class="detail__middle">
        <div class="controls">
          <button class="overlay-trigger" type="button" data-action="overlays" aria-expanded="false">
            ${icon('layers')}<span>Overlays</span>
          </button>
          <div class="toggles" hidden>
            <p class="toggles__title mono-label">${icon('layers')}<span>Overlays</span></p>
            <label class="toggle"><input type="checkbox" data-overlay="waves" checked><span>Wave forecast</span></label>
            <div class="wave-scale" data-role="wave-scale">
              <div class="wave-scale__ramp" aria-hidden="true"></div>
              <div class="wave-scale__labels mono-label"><span>0</span><span>2</span><span>4</span><span>6+ m</span></div>
              <p class="toggles__note mono-label" data-role="wave-note">Significant wave height</p>
            </div>
            <label class="toggle" title="Forecast wave-height contours, not official storm warnings"><input type="checkbox" data-overlay="hazards" checked><span>High seas · 4+ m</span></label>
            <label class="toggle"><input type="checkbox" data-overlay="restrictions" disabled><span>Restricted areas</span></label>
            <p class="toggles__note mono-label" data-role="restriction-note">Data unavailable</p>
            <label class="toggle"><input type="checkbox" data-overlay="alternates"><span>Other routes</span></label>
            <p class="toggles__note mono-label">Click a restricted area for details</p>
          </div>
        </div>
      </div>
      <div class="route-summary" aria-label="Route summary">
        <dl class="route-summary__metrics">
          <div class="metric"><dt class="mono-label">Transit</dt><dd class="metric__value" data-role="duration"></dd></div>
          <div class="metric"><dt class="mono-label">Distance</dt><dd class="metric__value" data-role="distance"></dd></div>
          <div class="metric"><dt class="mono-label">Est. cost</dt><dd class="metric__value" data-role="cost"></dd></div>
          <div class="metric"><dt class="mono-label">Emission</dt><dd class="metric__value" data-role="emissions"></dd></div>
        </dl>
        <div class="route-summary__footer">
          <div class="metric route-summary__eta"><dt class="mono-label">ETA · UTC</dt><dd class="metric__value" data-role="arrival"></dd></div>
          <div class="route-summary__playback">
            <label class="playback-speed" data-role="playback-speed" hidden>
            <select data-action="speed" aria-label="Voyage preview speed">
              <option value="1">1×</option>
              <option value="1.5">1.5×</option>
              <option value="2">2×</option>
              <option value="4">4×</option>
            </select>
            </label>
            <button class="route-summary__preview" type="button" data-action="preview" aria-label="Preview vessel voyage">Preview</button>
          </div>
        </div>
      </div>
    </div>`;
  let flat = null;
  const waveNote = element.querySelector('[data-role="wave-note"]');
  const waveScale = element.querySelector('[data-role="wave-scale"]');
  function updateWaveState({ status, held, validAt }) {
    waveNote.textContent = status === 'loading' ? 'Preparing wave display…' : status === 'error' ? 'Wave display unavailable' :
      status === 'unavailable' ? 'Forecast unavailable' : held ? `Forecast · ${formatEta(validAt)} · held` : 'Significant wave height';
    waveScale.dataset.available = String(status === 'ready');
  }
  function updatePlayback({ playing, hour = 0, duration = 0, speed = 1 }) {
    const button = element.querySelector('[data-action="preview"]');
    const label = playing ? 'Pause' : hour >= duration && hour > 0 ? 'Replay' : hour > 0 ? 'Resume' : 'Preview';
    button.textContent = label;
    button.setAttribute('aria-label', `${label} vessel voyage`);
    element.querySelector('[data-role="playback-speed"]').hidden = !playing && hour === 0;
    element.querySelector('[data-action="speed"]').value = String(speed);
  }
  function updateNotices({ available, active }) {
    const toggle = element.querySelector('[data-overlay="restrictions"]');
    toggle.disabled = !available;
    if (!available) toggle.checked = false;
    element.querySelector('[data-role="restriction-note"]').textContent = available ? `${active} active supplied notices` : 'Verified data unavailable';
  }
  element.addEventListener('change', (event) => {
    if (event.target.dataset.overlay) flat?.setOverlay(event.target.dataset.overlay, event.target.checked);
    if (event.target.dataset.overlay === 'waves') element.querySelector('[data-role="wave-scale"]').hidden = !event.target.checked;
    if (event.target.dataset.action === 'speed') flat?.setPlaybackSpeed(Number(event.target.value));
  });
  element.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action === 'back') onBack?.();
    if (action === 'overlays') {
      const trigger = element.querySelector('[data-action="overlays"]');
      const panel = element.querySelector('.toggles');
      const expanded = trigger.getAttribute('aria-expanded') !== 'true';
      trigger.setAttribute('aria-expanded', String(expanded));
      panel.hidden = !expanded;
    }
    if (action === 'preview') flat?.togglePlayback();
  });
  function render(route) {
    const report = getReport();
    const origin = reportPort(report, 'origin');
    const destination = reportPort(report, 'destination');
    const text = (role, value) => { element.querySelector(`[data-role="${role}"]`).textContent = value; };
    text('duration', formatDuration(route.durationHours));
    text('distance', formatNm(route.distanceNm));
    text('cost', formatUsd(route.cost?.totalUsd, { compact: true }));
    text('emissions', `${formatNumber(route.emissions?.co2Tonnes)} t CO₂`);
    text('arrival', formatEta(route.eta));
    element.querySelector('[data-overlay="alternates"]').checked = false;
    flat?.setOverlay('alternates', false);
    flat?.setAlternates(getRoutes().filter((candidate) => candidate.id !== route.id));
    const waveToggle = element.querySelector('[data-overlay="waves"]');
    waveToggle.disabled = !validWaveGrid(report.waveGrid);
    waveToggle.checked = !waveToggle.disabled;
    const hazardToggle = element.querySelector('[data-overlay="hazards"]');
    hazardToggle.disabled = waveToggle.disabled;
    hazardToggle.checked = !hazardToggle.disabled;
    element.querySelector('[data-overlay="restrictions"]').checked = true;
    element.querySelector('[data-role="wave-scale"]').hidden = waveToggle.disabled;
    flat?.setActive(true);
    flat?.showRoute(route, { origin, destination, departureTime: report.departureTime, waveGrid: report.waveGrid, overlays: report.overlays });
  }
  return {
    element, showGlobe: false,
    enter() {
      const status = element.querySelector('.map-status');
      if (!flat) {
        status.textContent = 'Loading map…';
        try { flat = createFlatMap({ container: element.querySelector('#flatmap'), onStatus: (message) => { status.textContent = message; }, onPlaybackState: updatePlayback, onNotices: updateNotices, onWaveState: updateWaveState }); }
        catch { status.textContent = 'Map rendering is unavailable in this browser. Route estimates are shown below.'; }
      }
      flat?.resize();
      const route = findRoute(getSelectedRouteId());
      if (route) render(route);
    },
    leave() { flat?.setActive(false); }
  };
}
