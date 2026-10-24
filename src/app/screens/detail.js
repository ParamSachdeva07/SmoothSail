import { createFlatMap } from '../../globe/flatmap.js';
import { getReport, findRoute, reportPort, formatDuration, formatNm, formatUsd, formatNumber } from '../../data/routes.js';
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
        <div><h1 class="wordmark">SmoothSail</h1><p class="mono-label" data-role="route-name"></p><p class="mono-label map-status" role="status"></p></div>
      </header>
      <button class="route-summary__show" type="button" data-action="toggle-summary" aria-expanded="false" hidden>Show</button>
      <div class="route-summary" aria-label="Route summary">
        <button class="route-summary__hide" type="button" data-action="toggle-summary" aria-expanded="true">Hide</button>
        <dl class="route-summary__metrics">
          <div class="metric"><dt class="mono-label">Transit</dt><dd class="metric__value" data-role="duration"></dd></div>
          <div class="metric"><dt class="mono-label">Distance</dt><dd class="metric__value" data-role="distance"></dd></div>
          <div class="metric"><dt class="mono-label">Est. cost</dt><dd class="metric__value" data-role="cost"></dd></div>
          <div class="metric"><dt class="mono-label">Emission</dt><dd class="metric__value" data-role="emissions"></dd></div>
          <div class="metric"><dt class="mono-label">ETA · UTC</dt><dd class="metric__value" data-role="arrival"></dd></div>
          <div class="route-summary__wave" data-role="wave-scale" aria-label="Wave forecast scale">
            <div class="route-summary__wave-title"><i class="route-summary__wave-swatch" aria-hidden="true"></i><span>Wave forecast</span></div>
            <div class="wave-scale__ramp" aria-hidden="true"></div>
            <div class="wave-scale__labels"><span>0</span><span>2</span><span>4</span><span>6+ m</span></div>
          </div>
        </dl>
        <div class="route-summary__footer">
          <button class="route-summary__back" type="button" data-action="back">Go Back</button>
          <div class="route-summary__playback">
            <span class="route-summary__speed" aria-label="Playback speed">1×</span>
            <button class="route-summary__preview" type="button" data-action="play" aria-label="Pause voyage preview">Pause</button>
          </div>
        </div>
      </div>
    </div>`;
  let flat = null;
  const waveScale = element.querySelector('[data-role="wave-scale"]');
  function updateWaveState({ status }) {
    waveScale.dataset.available = String(status === 'ready');
  }
  function updatePlayback({ playing }) {
    const button = element.querySelector('[data-action="play"]');
    button.textContent = playing ? 'Pause' : 'Replay';
    button.setAttribute('aria-label', `${playing ? 'Pause' : 'Replay'} voyage preview`);
  }
  element.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action === 'back') onBack?.();
    if (action === 'play') flat?.togglePlayback();
    if (action === 'toggle-summary') {
      const panel = element.querySelector('.route-summary');
      const show = element.querySelector('.route-summary__show');
      panel.hidden = !panel.hidden;
      show.hidden = !panel.hidden;
      (panel.hidden ? show : element.querySelector('.route-summary__hide')).focus();
    }
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
    text('emissions', `${formatNumber(route.emissions?.co2Tonnes)} t CO₂`);
    text('arrival', formatEta(route.eta));
    waveScale.dataset.available = String(validWaveGrid(report.waveGrid));
    flat?.setActive(true);
    flat?.showRoute(route, { origin, destination, departureTime: report.departureTime, waveGrid: report.waveGrid, overlays: report.overlays });
  }
  return {
    element, showGlobe: false,
    enter() {
      const status = element.querySelector('.map-status');
      if (!flat) {
        status.textContent = 'Loading map…';
        try { flat = createFlatMap({ container: element.querySelector('#flatmap'), onStatus: (message) => { status.textContent = message; }, onPlaybackState: updatePlayback, onWaveState: updateWaveState }); }
        catch { status.textContent = 'Map rendering is unavailable in this browser. Route estimates are shown below.'; }
      }
      flat?.resize();
      const route = findRoute(getSelectedRouteId());
      if (route) render(route);
    },
    leave() { flat?.setActive(false); }
  };
}
