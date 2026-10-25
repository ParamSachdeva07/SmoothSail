import { api } from '../../api/client.js';
import { rerouteRequest } from '../../data/reroute.js';
import { transportEstimate } from '../../globe/transport-estimate.js';
import { icon } from '../icons.js';
import { createFlatMap } from '../../globe/flatmap.js';
import { getReport, getRoutes, findRoute, reportPort, formatDuration, formatNm, formatUsd, formatNumber } from '../../data/routes.js';
import { formatEta } from '../../data/shipment.js';
import { validWaveGrid } from '../../globe/waves.js';
import { routePlanner } from '../../data/route-planning.js';
import { COMPLIANCE_CATEGORIES, categoryProgress } from '../../data/compliance.js';
import { createVoyageChecklist } from '../voyage-checklist.js';
import { createComplianceChat } from '../compliance-chat.js';

export function createDetailScreen({ getSelectedRouteId, onSelectRoute, onBack }) {
  const element = document.createElement('section');
  element.className = 'screen detail';
  element.id = 'screen-detail';
  element.innerHTML = `
    <div class="flatmap" id="flatmap" aria-label="Selected maritime route map"></div>
    <div class="detail__layout">
      <header class="detail__head">
        <div><h1 class="wordmark">SmoothSail</h1><p class="mono-label map-status" role="status"></p></div>
        <div class="detail__head-actions"><button class="button button--primary" type="button" data-action="checklist" disabled>Create voyage checklist</button><button class="button button--quiet" type="button" data-action="back">${icon('arrow-left')}<span>All routes</span></button></div>
      </header>
      <div class="detail__middle" aria-hidden="true"></div>
      <button class="route-summary__show" type="button" data-action="toggle-summary" aria-expanded="false" hidden>Show</button>
      <div class="route-summary" aria-label="Route summary">
        <button class="route-summary__hide" type="button" data-action="toggle-summary" aria-expanded="true">Hide</button>
        <div class="route-picker" role="group" aria-label="Choose route option"></div>
        <p class="route-summary__selection" data-role="route-selection" aria-live="polite"></p>
        <dl class="route-summary__metrics">
          <div class="metric"><dt class="mono-label">Transit</dt><dd class="metric__value" data-role="duration"></dd></div>
          <div class="metric"><dt class="mono-label">Distance</dt><dd class="metric__value" data-role="distance"></dd></div>
          <div class="metric"><dt class="mono-label">Est. cost</dt><dd class="metric__value" data-role="cost"></dd></div>
          <div class="metric"><dt class="mono-label">Emission</dt><dd class="metric__value" data-role="emissions"></dd></div>
          <div class="metric route-summary__eta"><dt class="mono-label">ETA · UTC</dt><dd class="metric__value" data-role="arrival"></dd></div>
          <div class="route-summary__wave" data-role="summary-wave-scale" aria-label="Wave forecast scale">
            <div class="route-summary__wave-title"><i class="route-summary__wave-swatch" aria-hidden="true"></i><span>Wave forecast</span></div>
            <div class="wave-scale__ramp" aria-hidden="true"></div>
            <div class="wave-scale__labels"><span>0</span><span>2</span><span>4</span><span>6+ m</span></div>
          </div>
        </dl>
        <section class="reroute-comparison" aria-label="Alternative route comparison" hidden></section>
        <div class="route-summary__footer">
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
    </div>
    <details class="compliance-progress" aria-label="Voyage compliance check" open>
      <summary><span>Voyage compliance check</span><span class="mono-label" data-role="compliance-count" role="status">0 / 6</span></summary>
      <div class="compliance-progress__body">
        <dl data-role="compliance-checks"></dl>
      </div>
    </details>`;
  let flat = null, rerouteController = null, alternativePreview = null, alternativeSelected = false;
  const alternativePanel = element.querySelector('.reroute-comparison');
  async function onReroute(change) {
    const report = getReport(), route = findRoute(getSelectedRouteId());
    const input = rerouteRequest(report, route, change, routePlanner.getState(report)?.routeInput);
    rerouteController?.abort(); const controller = new AbortController(); rerouteController = controller;
    alternativePanel.hidden = false; alternativePanel.textContent = 'Calculating alternative route…';
    try {
      const preview = await api.previewReroute(input, { signal: controller.signal });
      if (controller.signal.aborted) return;
      alternativePreview = preview;
      await flat?.setReroutePreview(preview);
      alternativePanel.replaceChildren();
      const selector = document.createElement('div'); selector.className = 'reroute-selector'; selector.setAttribute('role', 'group'); selector.setAttribute('aria-label', 'Select displayed route');
      for (const [label, isAlternative] of [['Original route', false], ['Alternative route', true]]) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'button button--quiet';
        button.textContent = label; button.dataset.alternative = String(isAlternative);
        button.addEventListener('click', () => selectPreview(isAlternative)); selector.append(button);
      }
      const title = document.createElement('h3'); title.textContent = `Alternative via ${change.alternativePort.name}`;
      const legend = document.createElement('p'); legend.className = 'reroute-legend';
      legend.textContent = 'Pink · original   Yellow · alternative   Dashed · road transfer';
      const sea = document.createElement('p');
      sea.textContent = `${formatDuration(preview.route.durationHours)} · ${formatNm(preview.route.distanceNm)} · ${formatUsd(preview.route.cost?.totalUsd)} whole-vessel sea cost`;
      const note = document.createElement('p'); note.className = 'congestion-card__meta'; note.textContent = preview.notice;
      const remove = document.createElement('button'); remove.className = 'button button--quiet'; remove.type = 'button'; remove.textContent = 'Remove alternative';
      remove.addEventListener('click', () => { selectPreview(false); alternativePreview = null; flat?.setReroutePreview(null); alternativePanel.hidden = true; });
      alternativePanel.append(selector, title, legend, sea, transportEstimate(preview.onwardTransport), note, remove);
      selectPreview(true);
    } catch (error) {
      if (rerouteController === controller) { alternativePanel.textContent = error.name === 'AbortError' ? '' : error.message; alternativePanel.hidden = error.name === 'AbortError'; }
      throw error;
    }
  }
  let congestionRevision = 0;
  let unsubscribe = () => {};
  const chat = createComplianceChat(element);
  const checklist = createVoyageChecklist(element);
  const progress = element.querySelector('.compliance-progress');
  if (window.matchMedia('(max-width: 760px)').matches) progress.open = false;
  const learnMore = finding => {
    const state = routePlanner.getState(getReport());
    if (state) { progress.open = false; chat.open(finding, state, getSelectedRouteId()); }
  };
  function selectPreview(alternative) {
    alternativeSelected = alternative && Boolean(alternativePreview);
    const route = alternativeSelected ? alternativePreview.route : findRoute(getSelectedRouteId());
    showMetrics(route); updateRoutePicker(); flat?.selectReroute(alternativeSelected); chat.close(); checklist.close();
    for (const button of alternativePanel.querySelectorAll('[data-alternative]')) button.setAttribute('aria-pressed', String((button.dataset.alternative === 'true') === alternativeSelected));
    const state = routePlanner.getState(getReport());
    if (state) { updateCompliance(state); flat?.setPortCongestion(alternativeSelected ? [] : state.congestion); }
  }
  function updateCompliance(state) {
    if (alternativeSelected) {
      element.querySelector('[data-action="checklist"]').disabled = true;
      element.querySelector('[data-role="compliance-count"]').textContent = 'Not assessed';
      const checks = element.querySelector('[data-role="compliance-checks"]'); checks.replaceChildren();
      const note = document.createElement('p'); note.className = 'congestion-card__meta';
      note.textContent = 'This alternative has not undergone voyage compliance research. Select the original route to see its completed checks and checklist.';
      checks.append(note); flat?.setComplianceFindings([]); return;
    }
    element.querySelector('[data-action="checklist"]').disabled = !state.context || state.detailsPending;
    const count = Object.keys(state.checks).length;
    element.querySelector('[data-role="compliance-count"]').textContent = `${count} / ${COMPLIANCE_CATEGORIES.length}`;
    const checks = element.querySelector('[data-role="compliance-checks"]'); checks.replaceChildren();
    for (const category of COMPLIANCE_CATEGORIES) {
      const check = categoryProgress(state, category);
      const row = document.createElement('div'); row.className = 'compliance-progress__row'; row.dataset.phase = check.phase;
      row.title = check.description;
      const name = document.createElement('dt'); name.textContent = check.name;
      const status = document.createElement('dd'); status.setAttribute('aria-label', check.label);
      const indicator = document.createElement('span'); indicator.className = 'compliance-progress__indicator'; indicator.setAttribute('aria-hidden', 'true');
      if (check.phase === 'done') {
        indicator.innerHTML = icon('check', 12);
        status.title = 'Research complete. Open the port issues to read findings.';
        status.append(indicator);
      } else {
        status.append(indicator, document.createTextNode(check.label));
      }
      row.append(name, status); checks.append(row);
    }
    flat?.setComplianceFindings(state.findings);
  }
  const waveScale = element.querySelector('[data-role="summary-wave-scale"]');
  function updateWaveState({ status, held, validAt }) {
    waveScale.dataset.available = String(status === 'ready');
    waveScale.title = status === 'loading' ? 'Preparing wave display…' : status === 'error' ? 'Wave display unavailable' :
      status === 'unavailable' ? 'Forecast unavailable' : held ? `Forecast · ${formatEta(validAt)} · held` : 'Significant wave height';
  }
  function updatePlayback({ playing, hour = 0, duration = 0, speed = 1 }) {
    const button = element.querySelector('[data-action="preview"]');
    const label = playing ? 'Pause' : hour >= duration && hour > 0 ? 'Replay' : hour > 0 ? 'Resume' : 'Preview';
    button.textContent = label;
    button.setAttribute('aria-label', `${label} vessel voyage`);
    element.querySelector('[data-role="playback-speed"]').hidden = !playing && hour === 0;
    element.querySelector('[data-action="speed"]').value = String(speed);
  }
  element.addEventListener('change', (event) => {
    if (event.target.dataset.action === 'speed') flat?.setPlaybackSpeed(Number(event.target.value));
  });
  element.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action === 'checklist') {
      const state = routePlanner.getState(getReport());
      if (state?.context) checklist.open(state, getSelectedRouteId());
    }
    if (action === 'back') onBack?.();
    if (action === 'preview') flat?.togglePlayback();
    if (action === 'toggle-summary') {
      const panel = element.querySelector('.route-summary');
      const show = element.querySelector('.route-summary__show');
      panel.hidden = !panel.hidden;
      show.hidden = !panel.hidden;
      (panel.hidden ? show : element.querySelector('.route-summary__hide')).focus();
    }
  });
  function updateRoutePicker() {
    const picker = element.querySelector('.route-picker'); picker.replaceChildren();
    for (const route of getRoutes()) {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = route.label; button.className = 'route-picker__option';
      button.setAttribute('aria-pressed', String(!alternativeSelected && route.id === getSelectedRouteId()));
      button.addEventListener('click', () => {
        if (route.id === getSelectedRouteId()) { selectPreview(false); return; }
        onSelectRoute(route.id); chat.close(); checklist.close(); render(route, true);
      });
      picker.append(button);
    }
  }
  function showMetrics(route) {
    const text = (role, value) => { element.querySelector(`[data-role="${role}"]`).textContent = value; };
    text('route-selection', alternativeSelected ? `Alternative · ${alternativePreview.origin} → ${alternativePreview.destination}` : `${route.label} · ${route.name}`);
    text('duration', formatDuration(route.durationHours));
    text('distance', formatNm(route.distanceNm));
    text('cost', formatUsd(route.cost?.totalUsd, { compact: true }));
    text('emissions', `${formatNumber(route.emissions?.co2Tonnes)} t CO₂`);
    text('arrival', formatEta(route.eta));
  }
  function render(route, preserveAlternative = false) {
    rerouteController?.abort(); alternativeSelected = false;
    if (!preserveAlternative) { alternativePanel.hidden = true; alternativePreview = null; }
    for (const button of alternativePanel.querySelectorAll('[data-alternative]')) button.setAttribute('aria-pressed', String(button.dataset.alternative === 'false'));
    updateRoutePicker();
    const report = getReport();
    const origin = reportPort(report, 'origin');
    const destination = reportPort(report, 'destination');
    showMetrics(route);
    waveScale.dataset.available = String(validWaveGrid(report.waveGrid));
    flat?.setActive(true);
    const revision = ++congestionRevision;
    unsubscribe();
    // Progress is independent of the map/texture loading lifecycle.
    const mapReady = flat?.showRoute(route, { origin, destination, departureTime: report.departureTime, waveGrid: report.waveGrid, overlays: report.overlays });
    let previousCongestion = null;
    unsubscribe = routePlanner.subscribe(report, state => {
      if (congestionRevision !== revision) return;
      updateCompliance(state);
      if (previousCongestion !== state.congestion) {
        previousCongestion = state.congestion; flat?.setPortCongestion(alternativeSelected ? [] : state.congestion);
      }
    });
    Promise.resolve(mapReady).then(async () => {
      if (congestionRevision !== revision) return;
      if (preserveAlternative && alternativePreview) await flat?.setReroutePreview(alternativePreview);
      if (congestionRevision !== revision) return;
      const state = routePlanner.getState(report);
      if (state) { updateCompliance(state); flat?.setPortCongestion(alternativeSelected ? [] : state.congestion); }
    });
  }
  return {
    element, showGlobe: false,
    enter() {
      const status = element.querySelector('.map-status');
      if (!flat) {
        status.textContent = 'Loading map…';
        try { flat = createFlatMap({ container: element.querySelector('#flatmap'), onStatus: (message) => { status.textContent = message; }, onPlaybackState: updatePlayback, onWaveState: updateWaveState, onReroute, onLearnMore: learnMore }); }
        catch { status.textContent = 'Map rendering is unavailable in this browser. Route estimates are shown below.'; }
      }
      flat?.resize();
      const route = findRoute(getSelectedRouteId());
      if (route) render(route);
    },
    leave() { rerouteController?.abort(); congestionRevision++; unsubscribe(); chat.close(); checklist.close(); flat?.setActive(false); }
  };
}
