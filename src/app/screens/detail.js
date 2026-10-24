// Screen 4 — Route detail, flat dot-matrix map.
// Only what the voyage needs: departure port, arrival port, stops, the vessel
// glyph and the route line. A compact info strip holds the key numbers; the
// overlay toggles sit bottom-right with the zoom controls.

import { icon } from '../icons.js';
import { createFlatMap } from '../../globe/flatmap.js';
import { ROUTES, findRoute, formatDuration, formatNm, formatUsd, arrivalDate } from '../../data/routes.js';
import { shipment, formatDate } from '../../data/shipment.js';
import { findPort } from '../../data/ports.js';

const OVERLAYS = [
  { id: 'wind', label: 'Wind prediction' },
  { id: 'risk', label: 'Conflict zones' },
  { id: 'alternates', label: 'Other routes' }
];

export function createDetailScreen({ getSelectedRouteId, onBack, onMoreInfo, onChoose }) {
  const element = document.createElement('section');
  element.className = 'screen detail';
  element.id = 'screen-detail';
  // One flex column at the screen gutter: header / middle row / info strip.
  // Nothing is independently positioned, so the three bands cannot collide
  // at any viewport width.
  element.innerHTML = `
    <div class="flatmap" id="flatmap"></div>

    <div class="detail__layout">
      <header class="detail__head">
        <div>
          <h1 class="wordmark">SmoothSail</h1>
          <p class="mono-label" data-role="route-name"></p>
        </div>
        <button class="button button--quiet" type="button" data-action="back">
          ${icon('arrow-left')}<span>All routes</span>
        </button>
      </header>

      <div class="detail__middle">
        <dl class="legend">
          <div><dt><i class="dot dot--accent"></i></dt><dd class="mono-label">Ports</dd></div>
          <div><dt><i class="dot dot--vessel"></i></dt><dd class="mono-label">Vessel</dd></div>
          <div><dt><i class="line line--accent"></i></dt><dd class="mono-label">Selected route</dd></div>
        </dl>

        <div class="controls">
          <div class="toggles">
            <p class="toggles__title mono-label">${icon('layers')}<span>Overlays</span></p>
            ${OVERLAYS.map((overlay) => `
              <label class="toggle">
                <input type="checkbox" data-overlay="${overlay.id}">
                <span>${overlay.label}</span>
              </label>
            `).join('')}
            <p class="toggles__note mono-label">Placeholder data</p>
          </div>
          <div class="zoom">
            <button class="button button--quiet button--icon" type="button" data-action="zoom-in" aria-label="Zoom in">${icon('plus')}</button>
            <button class="button button--quiet button--icon" type="button" data-action="zoom-out" aria-label="Zoom out">${icon('minus')}</button>
          </div>
        </div>
      </div>

      <div class="detail__footer">
      <div class="infostrip">
        <dl class="metrics metrics--strip">
          <div class="metric">
            <dt class="mono-label">Transit</dt>
            <dd class="metric__value" data-role="duration"></dd>
          </div>
          <div class="metric">
            <dt class="mono-label">Distance</dt>
            <dd class="metric__value" data-role="distance"></dd>
          </div>
          <div class="metric">
            <dt class="mono-label">Est. voyage cost</dt>
            <dd class="metric__value" data-role="cost"></dd>
          </div>
          <div class="metric">
            <dt class="mono-label">Arrives</dt>
            <dd class="metric__value" data-role="arrival"></dd>
          </div>
        </dl>
        <div class="infostrip__actions">
          <button class="button button--quiet" type="button" data-action="more">${icon('info')}<span>More info</span></button>
          <button class="button button--primary" type="button" data-action="choose">${icon('check')}<span>Choose this route</span></button>
        </div>
      </div>

      <p class="detail__credit mono-label">Map Mapbox · Land Natural Earth 1:10m · Indicative routing, not for navigation</p>
      </div>
    </div>
  `;

  let flat = null;

  element.addEventListener('change', (event) => {
    const overlay = event.target.dataset?.overlay;
    if (overlay) flat?.setOverlay(overlay, event.target.checked);
  });

  element.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action === 'back') onBack?.();
    if (action === 'more') onMoreInfo?.(getSelectedRouteId());
    if (action === 'choose') onChoose?.(getSelectedRouteId());
    if (action === 'zoom-in') flat?.zoomBy(0.6);
    if (action === 'zoom-out') flat?.zoomBy(-0.6);
  });

  function render(route) {
    element.querySelector('[data-role="route-name"]').textContent =
      `${route.label} · ${route.name} · departs ${formatDate(shipment.departure)}`;
    element.querySelector('[data-role="duration"]').textContent = formatDuration(route.durationHours);
    element.querySelector('[data-role="distance"]').textContent = formatNm(route.distanceNm);
    element.querySelector('[data-role="cost"]').textContent = formatUsd(route.cost.totalUsd, { compact: true });
    element.querySelector('[data-role="arrival"]').textContent =
      arrivalDate(shipment.departure, route.durationHours);

    flat.showRoute(route, {
      origin: findPort(shipment.originId),
      destination: findPort(shipment.destinationId)
    });
    flat.setAlternates(ROUTES.filter((candidate) => candidate.id !== route.id));
  }

  return {
    element,
    showGlobe: false,
    enter() {
      if (!flat) flat = createFlatMap({ container: element.querySelector('#flatmap') });
      flat?.resize();
      const route = findRoute(getSelectedRouteId()) ?? ROUTES[0];
      if (flat) render(route);
    }
  };
}
