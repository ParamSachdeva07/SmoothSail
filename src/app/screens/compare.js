import { icon } from '../icons.js';
import { getReport, getRoutes, reportPort, escapeHtml as h, formatDuration, formatNm, formatUsd, formatNumber, coverageLabel } from '../../data/routes.js';
import { formatEta } from '../../data/shipment.js';

export function createCompareScreen({ onBack, onViewRoute, onSelectRoute }) {
  const element = document.createElement('section');
  element.className = 'screen compare';
  element.id = 'screen-compare';

  function card(route) {
    const summary = (route.explanations ?? []).filter((line) => !line.startsWith('Estimated USD')).slice(0, 3);
    return `
      <article class="card" data-route="${h(route.id)}">
        <header class="card__head"><p class="mono-label">${h(route.label)}</p><h2 class="card__name">${h(route.name)}</h2></header>
        <dl class="metrics">
          <div class="metric"><dt class="mono-label">Transit</dt><dd class="metric__value">${formatDuration(route.durationHours)}</dd><dd class="metric__note mono-label">ETA ${h(formatEta(route.eta))}</dd></div>
          <div class="metric"><dt class="mono-label">Distance</dt><dd class="metric__value">${formatNm(route.distanceNm)}</dd><dd class="metric__note mono-label">${formatNumber(route.speedKnots, 1)} kn cruising setting</dd></div>
          <div class="metric"><dt class="mono-label">Est. voyage cost</dt><dd class="metric__value">${formatUsd(route.cost?.totalUsd, { compact: true })}</dd><dd class="metric__note mono-label">${formatUsd(route.cost?.totalUsd)} USD · whole voyage</dd></div>
          <div class="metric"><dt class="mono-label">Est. emissions</dt><dd class="metric__value">${formatNumber(route.emissions?.co2Tonnes)} t CO₂</dd><dd class="metric__note mono-label">${formatNumber(route.cost?.fuelTonnes)} t fuel · tank-to-wake</dd></div>
        </dl>
        <ul class="tags"><li class="tag tag--neutral">${h(coverageLabel(route))}</li><li class="tag tag--neutral">Compliance not assessed</li></ul>
        <div class="card__summary">${summary.map((line) => `<p>${h(line)}</p>`).join('')}</div>
        <div class="card__actions">
          <button class="button button--quiet" type="button" data-action="info" disabled title="Route information is coming soon">${icon('info')}<span>Info</span></button>
          <button class="button button--quiet" type="button" data-action="view">${icon('ship')}<span>View route</span></button>
          <button class="button button--primary" type="button" data-action="select"><span>Select this route</span></button>
        </div>
      </article>`;
  }
  function render() {
    const report = getReport();
    const routes = getRoutes();
    const origin = reportPort(report, 'origin');
    const destination = reportPort(report, 'destination');
    element.innerHTML = `
      <div class="sheet">
        <header class="sheet__head"><div><h1 class="wordmark">SmoothSail</h1><p class="mono-label">${routes.length} route options</p></div>
          <button class="button button--quiet" type="button" data-action="back">${icon('arrow-left')}<span>Change shipment</span></button></header>
        <p class="sheet__context mono-label">${h(origin.name)} (${h(origin.code)}) → ${h(destination.name)} (${h(destination.code)}) · departs ${h(formatEta(report?.departureTime))} · Generic container vessel</p>
        <div class="cards">${routes.map(card).join('')}</div>
        <p class="sheet__foot mono-label">Whole-vessel planning estimates, not freight quotes · Fuel + vessel time + canal charges · Insurance, port charges and emissions allowances excluded · Shared paths may have different speeds</p>
      </div>`;
  }
  element.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button || button.disabled) return;
    const id = button.closest('[data-route]')?.dataset.route;
    if (button.dataset.action === 'back') onBack?.();
    if (button.dataset.action === 'view') onViewRoute?.(id);
    if (button.dataset.action === 'select') onSelectRoute?.(id);
  });
  return { element, showGlobe: false, enter: render };
}
