import { icon } from '../icons.js';
import { createFlatMap } from '../../globe/flatmap.js';
import { getReport, getRoutes, findRoute, reportPort, formatDuration, formatNm, formatUsd, coverageLabel, formatNumber } from '../../data/routes.js';
import { formatEta } from '../../data/shipment.js';
import { validWaveGrid, waveAt } from '../../globe/waves.js';

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
          <div><dt><i class="dot dot--vessel"></i></dt><dd class="mono-label">Voyage preview · not live AIS</dd></div>
          <div><dt><i class="line line--alternate"></i></dt><dd class="mono-label">Other routes · may overlap</dd></div>
          <div><dt><i class="line line--hazard"></i></dt><dd class="mono-label">High-sea forecast · 4 / 6 m</dd></div>
        </dl>
        <div class="controls">
          <div class="toggles">
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
            <p class="toggles__note mono-label">Click an area for details</p>
          </div>
          <div class="zoom">
            <button class="button button--quiet" type="button" data-action="fit">Fit route</button>
            <button class="button button--quiet button--icon" type="button" data-action="zoom-in" aria-label="Zoom in">${icon('plus')}</button>
            <button class="button button--quiet button--icon" type="button" data-action="zoom-out" aria-label="Zoom out">${icon('minus')}</button>
          </div>
        </div>
      </div>
      <div class="detail__footer">
        <div class="voyage-timeline">
          <div class="voyage-timeline__head">
            <span class="mono-label">Voyage preview · 90s / voyage</span>
            <span class="mono-label" data-role="voyage-time"></span>
          </div>
          <div class="voyage-timeline__track">
            <button class="button button--quiet" type="button" data-action="play" aria-label="Pause voyage preview">Pause</button>
            <input type="range" min="0" max="1000" step="0.1" value="0" aria-label="Voyage progress" data-role="voyage-progress">
            <button class="button button--quiet" type="button" data-action="restart" aria-label="Restart voyage preview">Restart</button>
          </div>
          <p class="mono-label voyage-timeline__position" data-role="voyage-position"></p>
        </div>
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
        <p class="detail__credit mono-label">Mapbox Light · Planning estimate, not for navigation · Compliance not assessed</p>
      </div>
    </div>`;
  let flat = null;
  let activeReport = null;
  let lastUiTick = 0;
  const waveNote = element.querySelector('[data-role="wave-note"]');
  const waveScale = element.querySelector('[data-role="wave-scale"]');
  function updateWaveState({ status, held, validAt }) {
    waveNote.textContent = status === 'loading' ? 'Preparing wave display…' : status === 'error' ? 'Wave display unavailable' :
      status === 'unavailable' ? 'Forecast unavailable' : held ? `Forecast · ${formatEta(validAt)} · held` : 'Significant wave height';
    waveScale.dataset.available = String(status === 'ready');
  }
  function updateVoyage({ hour, duration, coordinates, kind, waveHeightM }) {
    const slider = element.querySelector('[data-role="voyage-progress"]');
    slider.value = String(duration ? hour / duration * 1000 : 0);
    const now = performance.now();
    if (now - lastUiTick < 200 && hour > 0 && hour < duration && document.activeElement !== slider) return;
    lastUiTick = now;
    const when = new Date(Date.parse(activeReport.departureTime) + hour * 3_600_000).toISOString();
    element.querySelector('[data-role="voyage-time"]').textContent = `${formatDuration(hour)} elapsed · ${formatEta(when)}`;
    slider.setAttribute('aria-valuetext', `${formatDuration(hour)} into voyage, ${formatEta(when)}`);
    const grid = validWaveGrid(activeReport.waveGrid) ? activeReport.waveGrid : null;
    const height = grid ? waveAt(grid, hour, coordinates) : null;
    const phase = hour >= duration ? 'Arrived at approach' : kind === 'canal_wait' ? 'Assumed canal wait' : kind === 'canal_transit' ? 'Canal transit' : 'Sailing';
    const sample = height !== null ? `${height.toFixed(1)} m waves here` : Number.isFinite(waveHeightM) ? `${waveHeightM.toFixed(1)} m waves · route sample` : 'Wave height here unavailable';
    element.querySelector('[data-role="voyage-position"]').textContent = `${phase} · ${sample} · Simulated position`;
  }
  function updatePlayback({ playing }) {
    const button = element.querySelector('[data-action="play"]');
    button.textContent = playing ? 'Pause' : 'Play';
    button.setAttribute('aria-label', `${playing ? 'Pause' : 'Play'} voyage preview`);
  }
  function updateNotices({ available, active }) {
    const toggle = element.querySelector('[data-overlay="restrictions"]');
    toggle.disabled = !available;
    if (!available) toggle.checked = false;
    element.querySelector('[data-role="restriction-note"]').textContent = available ? `${active} active supplied notices` : 'Verified data unavailable';
  }
  element.querySelector('[data-role="voyage-progress"]').addEventListener('input', (event) => {
    flat?.seekVoyage(Number(event.target.value) / 1000);
  });
  element.addEventListener('change', (event) => {
    if (event.target.dataset.overlay) flat?.setOverlay(event.target.dataset.overlay, event.target.checked);
    if (event.target.dataset.overlay === 'waves') element.querySelector('[data-role="wave-scale"]').hidden = !event.target.checked;
  });
  element.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action === 'back') onBack?.();
    if (action === 'zoom-in') flat?.zoomBy(0.6);
    if (action === 'zoom-out') flat?.zoomBy(-0.6);
    if (action === 'fit') flat?.fitRoute();
    if (action === 'play') flat?.togglePlayback();
    if (action === 'restart') flat?.restartPlayback();
  });
  function render(route) {
    const report = getReport();
    activeReport = report;
    lastUiTick = 0;
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
        try { flat = createFlatMap({ container: element.querySelector('#flatmap'), onStatus: (message) => { status.textContent = message; }, onVoyageTick: updateVoyage, onPlaybackState: updatePlayback, onNotices: updateNotices, onWaveState: updateWaveState }); }
        catch { status.textContent = 'Map rendering is unavailable in this browser. Route estimates are shown below.'; }
      }
      flat?.resize();
      const route = findRoute(getSelectedRouteId());
      if (route) render(route);
    },
    leave() { flat?.setActive(false); }
  };
}
