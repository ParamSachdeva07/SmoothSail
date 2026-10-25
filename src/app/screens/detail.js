import { api } from '../../api/client.js';
import { rerouteRequest } from '../../data/reroute.js';
import { icon } from '../icons.js';
import { createFlatMap } from '../../globe/flatmap.js';
import { getReport, getRoutes, findRoute, presentRoute, reportPort, formatDuration, formatNm, formatUsd, formatNumber } from '../../data/routes.js';
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
        <div class="route-summary__head">
          <div class="route-tabs" role="group" aria-label="Select displayed route" hidden>
            <button class="route-tabs__option" type="button" data-alternative="false" aria-pressed="true">Original route</button>
            <button class="route-tabs__option" type="button" data-alternative="true" aria-pressed="false">Alternative route</button>
          </div>
          <button class="route-summary__hide" type="button" data-action="toggle-summary" aria-expanded="true">Hide</button>
        </div>
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
  let flat = null, rerouteController = null, alternativeResearchController = null;
  let alternativePreview = null, alternativeSelected = false, alternativeRouteId = null, alternativeResearch = null;
  const routeTabs = element.querySelector('.route-tabs');
  for (const tab of routeTabs.querySelectorAll('[data-alternative]')) tab.addEventListener('click', () => selectPreview(tab.dataset.alternative === 'true'));
  function updateRouteTabs() {
    routeTabs.hidden = !alternativePreview;
    for (const tab of routeTabs.querySelectorAll('[data-alternative]')) tab.setAttribute('aria-pressed', String((tab.dataset.alternative === 'true') === alternativeSelected));
  }
  const alternativeRoutes = () => (alternativePreview?.routes ?? (alternativePreview?.route ? [alternativePreview.route] : [])).map(presentRoute);
  const selectedAlternativeRoute = () => alternativeRoutes().find(route => route.id === alternativeRouteId) ?? alternativeRoutes()[0];
  function researchAlternative() {
    if (!alternativePreview || alternativeResearch?.pending) return;
    alternativeResearchController?.abort();
    const controller = new AbortController(); alternativeResearchController = controller;
    const original = routePlanner.getState(getReport());
    const input = { ...original?.routeInput, origin: alternativePreview.origin, destination: alternativePreview.destination,
      departureTime: alternativePreview.departureTime };
    if (original?.imoNumber) input.complianceContext = { ...input.complianceContext,
      vessel: { ...input.complianceContext?.vessel, imoNumber: original.imoNumber } };
    alternativeResearch = { pending: true, checks: {}, findings: [], congestion: [], error: null, complete: false };
    updateCompliance(original ?? { checks: {}, findings: [] });
    api.analyseVoyage({ routeRequest: input, previewReportId: alternativePreview.reportId,
      cargoText: original?.cargoText ?? '',
      documentReferences: original?.documentReferences ?? [] }, { signal: controller.signal, onEvent(event) {
      if (controller.signal.aborted || !alternativeResearch) return;
      if (event.type === 'assessment') {
        alternativeResearch.checks[event.category] = event;
        alternativeResearch.findings = Object.values(alternativeResearch.checks).flatMap(check => check.findings ?? []);
        if (event.category === 'congestion') alternativeResearch.congestion = event.assessments ?? [];
      }
      if (event.type === 'complete') { alternativeResearch.pending = false; alternativeResearch.complete = true; }
      if (event.type === 'error') { alternativeResearch.pending = false; alternativeResearch.error = event.message; }
      updateCompliance(original ?? { checks: {}, findings: [] });
    }}).catch(error => {
      if (controller.signal.aborted || !alternativeResearch) return;
      alternativeResearch.pending = false; alternativeResearch.error = error.message;
      updateCompliance(original ?? { checks: {}, findings: [] });
    });
  }
  async function onReroute(change) {
    const report = getReport(), route = findRoute(getSelectedRouteId());
    const input = rerouteRequest(report, route, change, routePlanner.getState(report)?.routeInput);
    rerouteController?.abort(); const controller = new AbortController(); rerouteController = controller;
    const selection = element.querySelector('[data-role="route-selection"]'); selection.textContent = 'Calculating alternative route…';
    try {
      const preview = await api.previewReroute(input, { signal: controller.signal });
      if (controller.signal.aborted) return;
      alternativeResearchController?.abort(); alternativeResearch = null;
      alternativePreview = preview; alternativeRouteId = preview.route.id;
      await flat?.setReroutePreview(preview);
      selectPreview(true);
    } catch (error) {
      if (rerouteController === controller && error.name !== 'AbortError') selection.textContent = error.message;
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
    const route = alternativeSelected ? selectedAlternativeRoute() : findRoute(getSelectedRouteId());
    showMetrics(route); updateRoutePicker();
    if (alternativeSelected) flat?.setReroutePreview({ ...alternativePreview, route });
    flat?.selectReroute(alternativeSelected); chat.close(); checklist.close();
    updateRouteTabs();
    const state = routePlanner.getState(getReport());
    if (state) { updateCompliance(state); flat?.setPortCongestion(alternativeSelected ? [] : state.congestion); }
  }
  function updateCompliance(state) {
    if (alternativeSelected && !alternativeResearch) {
      element.querySelector('[data-action="checklist"]').disabled = true;
      element.querySelector('[data-role="compliance-count"]').textContent = 'Not assessed';
      const checks = element.querySelector('[data-role="compliance-checks"]'); checks.replaceChildren();
      const note = document.createElement('p'); note.className = 'congestion-card__meta';
      note.textContent = 'This alternative has not undergone voyage compliance research. Select the original route to see its completed checks and checklist.';
      const research = document.createElement('button'); research.className = 'button button--primary'; research.type = 'button';
      research.textContent = 'Research alternative compliance'; research.addEventListener('click', researchAlternative);
      checks.append(note, research); flat?.setComplianceFindings([]); return;
    }
    const activeState = alternativeSelected ? alternativeResearch : state;
    element.querySelector('[data-action="checklist"]').disabled = alternativeSelected || !state.context || state.detailsPending;
    const count = Object.keys(activeState.checks).length;
    element.querySelector('[data-role="compliance-count"]').textContent = `${count} / ${COMPLIANCE_CATEGORIES.length}`;
    const checks = element.querySelector('[data-role="compliance-checks"]'); checks.replaceChildren();
    for (const category of COMPLIANCE_CATEGORIES) {
      const check = categoryProgress(activeState, category);
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
    flat?.setComplianceFindings(activeState.findings);
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
    for (const route of alternativeSelected ? alternativeRoutes() : getRoutes()) {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = route.label; button.className = 'route-picker__option';
      button.setAttribute('aria-pressed', String(route.id === (alternativeSelected ? selectedAlternativeRoute()?.id : getSelectedRouteId())));
      button.addEventListener('click', () => {
        if (alternativeSelected) { alternativeRouteId = route.id; selectPreview(true); return; }
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
    if (!preserveAlternative) { alternativeResearchController?.abort(); alternativeResearch = null; alternativePreview = null; }
    updateRouteTabs();
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
    leave() { rerouteController?.abort(); alternativeResearchController?.abort(); congestionRevision++; unsubscribe(); chat.close(); checklist.close(); flat?.setActive(false); }
  };
}
