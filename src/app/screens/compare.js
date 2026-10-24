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
          <button class="button button--quiet" type="button" data-action="info">${icon('info')}<span>Info</span></button>
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
  let pending = null;
  let lastFocus = null;
  function openModal(action, id) {
    pending = { action, id };
    lastFocus = document.activeElement;
    element.querySelector('.modal')?.remove();
    element.insertAdjacentHTML('beforeend', `
      <div class="modal">
        <form class="modal__panel" role="dialog" aria-modal="true" aria-labelledby="intake-title" novalidate>
          <header class="modal__head">
            <div><p class="mono-label">Compliance details · Optional</p><h2 class="card__name" id="intake-title">Vessel &amp; cargo information</h2></div>
            <button class="button button--quiet" type="button" data-action="close" aria-label="Close">${icon('minus')}</button>
          </header>
          <p class="modal__intro">Share your vessel manifest and IMO number so we can give you more detailed compliance information. Every field is optional.</p>
          <label class="field"><span class="field__label">Vessel manifest or documents</span>
            <input class="field__input field__file" type="file" name="manifest" accept=".pdf,.doc,.docx,.xls,.xlsx,.csv" multiple></label>
          <label class="field"><span class="field__label">IMO number</span>
            <input class="field__input" type="text" name="imo" inputmode="numeric" autocomplete="off" placeholder="IMO 1234567" maxlength="11"></label>
          <label class="field"><span class="field__label">Other notes (cargo type, flag state, previous ports)</span>
            <textarea class="field__input field__textarea" name="notes" rows="3" placeholder="Anything else relevant to compliance"></textarea></label>
          <label class="modal__check"><input type="checkbox" name="skip"><span>Continue without filling in information</span></label>
          <footer class="modal__actions">
            <button class="button button--quiet" type="button" data-action="close">Cancel</button>
            <button class="button button--primary" type="submit"><span>Submit</span></button>
          </footer>
        </form>
      </div>`);
    element.querySelector('input[name="manifest"]').focus();
  }
  function closeModal() {
    element.querySelector('.modal')?.remove();
    pending = null;
    lastFocus?.focus?.();
  }
  element.addEventListener('submit', (event) => {
    event.preventDefault();
    const { action, id } = pending ?? {};
    closeModal();
    if (action === 'view') onViewRoute?.(id);
    if (action === 'select') onSelectRoute?.(id);
  });
  element.addEventListener('keydown', (event) => { if (event.key === 'Escape' && pending) closeModal(); });
  element.addEventListener('click', (event) => {
    if (event.target.classList.contains('modal')) return closeModal();
    const button = event.target.closest('button[data-action]');
    if (!button || button.disabled) return;
    const id = button.closest('[data-route]')?.dataset.route;
    if (button.dataset.action === 'back') onBack?.();
    if (button.dataset.action === 'close') closeModal();
    if (['info', 'view', 'select'].includes(button.dataset.action)) openModal(button.dataset.action, id);
  });
  return { element, showGlobe: false, enter: render };
}
