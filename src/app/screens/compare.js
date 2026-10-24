// Screen 3 — Route comparison.
// Three cards, side by side, equal height, identical anatomy. Content that
// would make one card taller is truncated behind a flat "Info" affordance that
// swaps the text inside the fixed summary block rather than growing the card.

import { icon } from '../icons.js';
import { ROUTES, formatDuration, formatNm, formatUsd, arrivalDate } from '../../data/routes.js';
import { shipment, formatDate } from '../../data/shipment.js';
import { findPort } from '../../data/ports.js';

const RISK_TONE = { clear: 'positive', attention: 'warning', blocked: 'accent' };

export function createCompareScreen({ onBack, onViewRoute, onSelectRoute }) {
  const element = document.createElement('section');
  element.className = 'screen compare';
  element.id = 'screen-compare';

  function card(route) {
    const [first, ...rest] = route.summary;
    return `
      <article class="card" data-route="${route.id}">
        <header class="card__head">
          <p class="mono-label">${route.label}</p>
          <h2 class="card__name">${route.name}</h2>
        </header>

        <dl class="metrics">
          <div class="metric">
            <dt class="mono-label">Transit</dt>
            <dd class="metric__value">${formatDuration(route.durationHours)}</dd>
            <dd class="metric__note mono-label">Arrives ${arrivalDate(shipment.departure, route.durationHours)}</dd>
          </div>
          <div class="metric">
            <dt class="mono-label">Distance</dt>
            <dd class="metric__value">${formatNm(route.distanceNm)}</dd>
            <dd class="metric__note mono-label">${route.speedKnots} kn service speed</dd>
          </div>
          <div class="metric">
            <dt class="mono-label">Est. voyage cost</dt>
            <dd class="metric__value">${formatUsd(route.cost.totalUsd, { compact: true })}</dd>
            <dd class="metric__note mono-label">${formatUsd(route.cost.totalUsd)} · demo figure</dd>
          </div>
          <div class="metric">
            <dt class="mono-label">Risk screening</dt>
            <dd class="metric__value metric__value--small">
              <span class="dot dot--${RISK_TONE[route.risk.level]}"></span>${route.risk.summary}
            </dd>
            <dd class="metric__note mono-label">${route.co2Tonnes.toFixed(0)} t CO₂ · ${route.fuelTonnes.toFixed(0)} t fuel</dd>
          </div>
        </dl>

        <ul class="tags">
          ${route.tags.map((tag) => `<li class="tag tag--${tag.tone}">${tag.text}</li>`).join('')}
        </ul>

        <div class="card__summary" data-expanded="false">
          <p data-role="short">${first}</p>
          <div data-role="full" hidden>${route.summary.map((line) => `<p>${line}</p>`).join('')}</div>
        </div>

        <div class="card__actions">
          <button class="button button--quiet" type="button" data-action="info" aria-expanded="false">
            ${icon('info')}<span>Info</span>
          </button>
          <button class="button button--quiet" type="button" data-action="view">
            ${icon('ship')}<span>View route</span>
          </button>
          <button class="button button--primary" type="button" data-action="select">
            ${icon('arrow-right')}<span>Select this route</span>
          </button>
        </div>
      </article>
    `;
  }

  const origin = findPort(shipment.originId);
  const destination = findPort(shipment.destinationId);

  element.innerHTML = `
    <div class="sheet">
      <header class="sheet__head">
        <div>
          <h1 class="wordmark">SmoothSail</h1>
          <p class="mono-label">Three candidate routes</p>
        </div>
        <button class="button button--quiet" type="button" data-action="back">
          ${icon('arrow-left')}<span>Change shipment</span>
        </button>
      </header>

      <p class="sheet__context mono-label">
        ${origin.name} (${origin.code}) → ${destination.name} (${destination.code})
        · departs ${formatDate(shipment.departure)}
        · ${shipment.cargo.containers} × ${shipment.cargo.containerType}
        · ${shipment.cargo.grossWeightKg.toLocaleString('en-GB')} kg ${shipment.cargo.commodity.toLowerCase()}
      </p>

      <div class="cards">${ROUTES.map(card).join('')}</div>

      <p class="sheet__foot mono-label">
        Indicative routing · costs are prototype demo values, not a freight quote
      </p>
    </div>
  `;

  element.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const routeId = button.closest('[data-route]')?.dataset.route;

    if (button.dataset.action === 'back') onBack?.();
    if (button.dataset.action === 'view') onViewRoute?.(routeId);
    if (button.dataset.action === 'select') onSelectRoute?.(routeId);

    if (button.dataset.action === 'info') {
      const summary = button.closest('.card').querySelector('.card__summary');
      const expanded = summary.dataset.expanded === 'true';
      summary.dataset.expanded = String(!expanded);
      summary.querySelector('[data-role="short"]').hidden = !expanded;
      summary.querySelector('[data-role="full"]').hidden = expanded;
      button.setAttribute('aria-expanded', String(!expanded));
    }
  });

  return { element, showGlobe: false };
}
