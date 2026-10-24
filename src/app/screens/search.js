// Screen 2 — Search panel.
// Reveals on scroll past the fold. Flat fields: hairline border, square
// corners, label above, icon flat beside the label. No pills, no containers
// around icons. Touching any field stops the globe spinning; choosing a port
// eases the globe toward that region.

import { icon } from '../icons.js';
import { PORTS, findPort, searchPorts } from '../../data/ports.js';
import { shipment, formatDate } from '../../data/shipment.js';

export function createSearchScreen({ getGlobe, onBack, onSubmit }) {
  const element = document.createElement('section');
  element.className = 'screen search';
  element.id = 'screen-search';
  element.innerHTML = `
    <div class="panel-column">
      <header class="panel-head">
        <h1 class="wordmark">SmoothSail</h1>
        <p class="mono-label">Plan a shipment</p>
      </header>

      <form class="form" novalidate>
        <div class="field" data-field="origin">
          <label class="field__label" for="field-origin">${icon('map-pin')}<span>From</span></label>
          <input class="field__input" id="field-origin" type="text" autocomplete="off"
                 role="combobox" aria-expanded="false" aria-controls="list-origin"
                 placeholder="Port of loading">
          <ul class="options" id="list-origin" role="listbox" hidden></ul>
        </div>

        <div class="field" data-field="destination">
          <label class="field__label" for="field-destination">${icon('flag')}<span>To</span></label>
          <input class="field__input" id="field-destination" type="text" autocomplete="off"
                 role="combobox" aria-expanded="false" aria-controls="list-destination"
                 placeholder="Port of discharge">
          <ul class="options" id="list-destination" role="listbox" hidden></ul>
        </div>

        <div class="field" data-field="departure">
          <label class="field__label" for="field-departure">${icon('calendar')}<span>Departure</span></label>
          <input class="field__input" id="field-departure" type="date" value="${shipment.departure}">
        </div>

        <p class="field__note mono-label" id="cargo-note"></p>

        <button class="button button--primary" type="submit">
          ${icon('search')}<span>Search routes</span>
        </button>
        <button class="button button--quiet" type="button" data-action="back">
          ${icon('arrow-left')}<span>Back to globe</span>
        </button>
      </form>

      <p class="panel-foot mono-label">
        ${PORTS.length} ports · Indicative routing · No freight quote
      </p>
    </div>
  `;

  const form = element.querySelector('.form');
  const cargoNote = element.querySelector('#cargo-note');
  const inputs = {
    origin: element.querySelector('#field-origin'),
    destination: element.querySelector('#field-destination'),
    departure: element.querySelector('#field-departure')
  };

  function renderCargoNote() {
    const { containers, containerType, grossWeightKg, commodity } = shipment.cargo;
    cargoNote.textContent =
      `${containers} × ${containerType} · ${grossWeightKg.toLocaleString('en-GB')} kg · ${commodity} · departs ${formatDate(shipment.departure)}`;
  }

  function labelFor(portId) {
    const port = findPort(portId);
    return port ? `${port.name}, ${port.country}` : '';
  }

  // --- Port combobox -----------------------------------------------------
  for (const key of ['origin', 'destination']) {
    const input = inputs[key];
    const list = element.querySelector(`#list-${key}`);

    const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); };

    const open = (query = '') => {
      // A field still showing its selected port lists everything, so the user
      // can browse rather than having to clear the text first.
      const needle = query === labelFor(shipment[`${key}Id`]) ? '' : query;
      const matches = searchPorts(needle).slice(0, 7);
      list.innerHTML = matches.map((port) => `
        <li role="option" tabindex="-1" data-id="${port.id}" aria-selected="${shipment[`${key}Id`] === port.id}">
          <span>${port.name}, ${port.country}</span>
          <span class="options__code">${port.code}</span>
        </li>
      `).join('');
      list.hidden = matches.length === 0;
      input.setAttribute('aria-expanded', String(!list.hidden));
    };

    const choose = (portId) => {
      shipment[`${key}Id`] = portId;
      input.value = labelFor(portId);
      close();
      // Ease-rotate the globe toward the chosen port.
      const port = findPort(portId);
      if (port) getGlobe()?.flyToRegion(port.coordinates, 1.6);
      renderCargoNote();
    };

    input.addEventListener('focus', () => { getGlobe()?.pauseAutoRotate(); open(input.value === labelFor(shipment[`${key}Id`]) ? '' : input.value); });
    input.addEventListener('input', () => open(input.value));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') close();
      if (event.key === 'Enter') {
        event.preventDefault();
        const first = list.querySelector('li');
        if (first && !list.hidden) choose(first.dataset.id);
      }
    });
    list.addEventListener('mousedown', (event) => {
      const option = event.target.closest('li');
      if (option) { event.preventDefault(); choose(option.dataset.id); }
    });
    input.addEventListener('blur', () => window.setTimeout(close, 120));
  }

  inputs.departure.addEventListener('focus', () => getGlobe()?.pauseAutoRotate());
  inputs.departure.addEventListener('change', () => {
    shipment.departure = inputs.departure.value || shipment.departure;
    renderCargoNote();
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    onSubmit?.();
  });

  element.querySelector('[data-action="back"]').addEventListener('click', () => onBack?.());

  return {
    element,
    showGlobe: true,
    enter() {
      inputs.origin.value = labelFor(shipment.originId);
      inputs.destination.value = labelFor(shipment.destinationId);
      inputs.departure.value = shipment.departure;
      renderCargoNote();
      // Bring the corridor into view behind the panel.
      getGlobe()?.flyToRegion([62, 26], 1.1);
    }
  };
}
