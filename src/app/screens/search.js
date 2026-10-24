import { icon } from '../icons.js';
import { PORTS, findPort, searchPorts, loadPorts } from '../../data/ports.js';
import { shipment, toRouteRequest } from '../../data/shipment.js';
import { escapeHtml } from '../../data/routes.js';
import { api } from '../../api/client.js';

export function createSearchScreen({ getGlobe, onBack, onSubmit }) {
  const element = document.createElement('section');
  element.className = 'screen search';
  element.id = 'screen-search';
  element.innerHTML = `
    <div class="panel-column">
      <header class="panel-head"><h1 class="wordmark">SmoothSail</h1><p class="mono-label">Plan a shipment</p></header>
      <form class="form" novalidate>
        ${['origin', 'destination'].map((key) => `
          <div class="field" data-field="${key}">
            <label class="field__label" for="field-${key}">${icon(key === 'origin' ? 'map-pin' : 'flag')}<span>${key === 'origin' ? 'From' : 'To'}</span></label>
            <input class="field__input" id="field-${key}" type="text" autocomplete="off"
              role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="list-${key}"
              placeholder="${key === 'origin' ? 'Port of loading' : 'Port of discharge'}" disabled>
            <ul class="options" id="list-${key}" role="listbox" hidden></ul>
          </div>`).join('')}
        <div class="field">
          <label class="field__label" for="field-departure">${icon('calendar')}<span>Departure · UTC</span></label>
          <input class="field__input" id="field-departure" type="date" value="${shipment.departure}" min="${shipment.departure}">
        </div>
        <p class="field__note mono-label">Generic container vessel · Fastest, cheapest and lowest CO₂ · Today means depart now</p>
        <details class="cargo-options">
          <summary class="mono-label">Cargo & compliance · optional</summary>
          <label class="field__label" for="cargo-text">Cargo list or manifest text</label>
          <textarea id="cargo-text" class="cargo-input" rows="4" maxlength="200000" placeholder="e.g. machinery, cleaning liquids, lithium batteries…"></textarea>
          <label class="cargo-upload mono-label">Add a document <input type="file" accept=".pdf,.docx,.txt,.csv,.md" data-role="cargo-file"></label>
          <p class="mono-label" data-role="upload-status" role="status"></p>
          <label class="field__label" for="vessel-imo">Vessel IMO · optional</label>
          <input class="field__input" id="vessel-imo" inputmode="numeric" maxlength="7" placeholder="7-digit IMO number">
          <p class="field__note mono-label">Readable PDF, DOCX or text · 10 MiB max · Session only</p>
        </details>
        <p class="form-status mono-label" role="status" aria-live="polite"></p>
        <button class="button button--primary" type="submit" disabled>${icon('search')}<span>Search routes</span></button>
        <button class="button button--quiet" type="button" data-action="retry" hidden>Retry loading ports</button>
        <button class="button button--quiet" type="button" data-action="back">${icon('arrow-left')}<span>Back to globe</span></button>
      </form>
      <p class="panel-foot mono-label">Loading supported ports…</p>
    </div>`;

  const form = element.querySelector('form');
  const status = element.querySelector('.form-status');
  const submit = element.querySelector('[type="submit"]');
  const retry = element.querySelector('[data-action="retry"]');
  const inputs = Object.fromEntries(['origin', 'destination', 'departure'].map((key) => [key, element.querySelector(`#field-${key}`)]));
  let controller = null;
  let interval = null;
  let active = false;
  let entryRevision = 0;
  let extracting = false;
  const cargo = element.querySelector('#cargo-text');
  const imo = element.querySelector('#vessel-imo');
  const fileInput = element.querySelector('[data-role="cargo-file"]');
  cargo.value = shipment.cargoText;
  cargo.addEventListener('input', () => { shipment.cargoText = cargo.value; shipment.documentReferences = []; });
  imo.addEventListener('input', () => { shipment.imoNumber = imo.value.trim(); });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0]; if (!file) return;
    const uploadStatus = element.querySelector('[data-role="upload-status"]');
    extracting = true; submit.disabled = true; fileInput.disabled = true;
    uploadStatus.textContent = 'Reading document…';
    try {
      const result = await api.extractDocument(file);
      shipment.cargoText = cargo.value = result.text;
      shipment.documentReferences = result.references;
      uploadStatus.textContent = `${file.name} · ${result.references.length} source sections ready`;
    } catch (error) { uploadStatus.textContent = error.message; }
    finally { extracting = false; fileInput.disabled = false; submit.disabled = !PORTS.length || Boolean(controller); }
  });

  function showStatus(message, error = false) {
    status.textContent = message;
    status.dataset.error = String(error);
  }
  function labelFor(id) {
    const port = findPort(id);
    return port ? `${port.name}, ${port.country}` : '';
  }
  function setBusy(busy) {
    form.setAttribute('aria-busy', String(busy));
    for (const [key, input] of Object.entries(inputs)) input.disabled = busy || (key !== 'departure' && !PORTS.length);
    submit.disabled = busy || !PORTS.length;
    cargo.disabled = busy || extracting; imo.disabled = busy; fileInput.disabled = busy || extracting;
    submit.querySelector('span').textContent = busy ? 'Calculating routes…' : 'Search routes';
    element.querySelector('[data-action="back"] span').textContent = busy ? 'Cancel and go back' : 'Back to globe';
  }
  function cancel() {
    controller?.abort();
    controller = null;
    clearInterval(interval);
    setBusy(false);
  }
  async function preparePorts() {
    showStatus('Loading supported ports…');
    retry.hidden = true;
    try {
      await loadPorts();
      for (const key of ['origin', 'destination']) inputs[key].value = labelFor(shipment[`${key}Id`]);
      element.querySelector('.panel-foot').textContent = `${PORTS.length} supported ports · Indicative routing · No freight quote`;
      if (active) showStatus('');
      setBusy(false);
      return true;
    } catch (error) {
      showStatus(error.message, true);
      retry.hidden = false;
      element.querySelector('.panel-foot').textContent = 'Port catalogue unavailable';
      return false;
    }
  }

  for (const key of ['origin', 'destination']) {
    const input = inputs[key];
    const list = element.querySelector(`#list-${key}`);
    let matches = [];
    let highlighted = -1;
    const close = () => {
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    };
    const highlight = (index) => {
      highlighted = index;
      [...list.children].forEach((node, i) => node.setAttribute('aria-selected', String(i === highlighted)));
      const node = list.children[highlighted];
      if (node) {
        input.setAttribute('aria-activedescendant', node.id);
        node.scrollIntoView({ block: 'nearest' });
      }
    };
    const open = () => {
      const needle = input.value === labelFor(shipment[`${key}Id`]) ? '' : input.value;
      matches = searchPorts(needle);
      highlighted = -1;
      list.innerHTML = matches.length ? matches.map((port, i) => `
        <li id="${key}-option-${i}" role="option" data-id="${escapeHtml(port.id)}" aria-selected="false">
          <span>${escapeHtml(port.name)}, ${escapeHtml(port.country)}</span><span class="options__code">${escapeHtml(port.code)}</span>
        </li>`).join('') : '<li role="presentation">No supported ports match</li>';
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      input.removeAttribute('aria-activedescendant');
    };
    const choose = (id) => {
      const port = findPort(id);
      if (!port) return;
      shipment[`${key}Id`] = id;
      input.value = labelFor(id);
      input.removeAttribute('aria-invalid');
      close();
      showStatus('');
      getGlobe()?.flyToRegion(port.coordinates, 1.6);
    };
    input.addEventListener('focus', () => { getGlobe()?.pauseAutoRotate(); open(); });
    input.addEventListener('input', () => {
      shipment[`${key}Id`] = null; // Edited text must never silently submit the previous port.
      open();
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') close();
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (list.hidden) open();
        if (matches.length) highlight((highlighted + (event.key === 'ArrowDown' ? 1 : matches.length - 1) + matches.length) % matches.length);
      }
      if (event.key === 'Enter' && !list.hidden) {
        event.preventDefault();
        if (matches.length) choose(matches[Math.max(highlighted, 0)].id);
      }
    });
    list.addEventListener('pointerdown', (event) => {
      const option = event.target.closest('[data-id]');
      if (option) { event.preventDefault(); choose(option.dataset.id); }
    });
    input.addEventListener('blur', close);
  }

  inputs.departure.addEventListener('focus', () => getGlobe()?.pauseAutoRotate());
  inputs.departure.addEventListener('change', () => { shipment.departure = inputs.departure.value; });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (controller || extracting || !PORTS.length) return;
    let request;
    try {
      for (const key of ['origin', 'destination']) {
        if (!findPort(shipment[`${key}Id`])) {
          inputs[key].setAttribute('aria-invalid', 'true');
          throw new Error(`Choose a ${key === 'origin' ? 'departure' : 'destination'} port from the suggestions.`);
        }
      }
      shipment.departure = inputs.departure.value;
      if (shipment.imoNumber && !/^\d{7}$/.test(shipment.imoNumber)) throw new Error('Enter a 7-digit IMO number or leave it blank.');
      request = toRouteRequest();
    } catch (error) { showStatus(error.message, true); return; }
    const pending = new AbortController();
    controller = pending;
    setBusy(true);
    const started = performance.now();
    const progress = () => showStatus(`Calculating route options · ${Math.floor((performance.now() - started) / 1000)}s elapsed. A cold start can take longer.`);
    progress();
    interval = setInterval(progress, 1000);
    try {
      await onSubmit(request, pending.signal);
    } catch (error) {
      if (!pending.signal.aborted) showStatus(error.message, true);
    } finally {
      if (controller === pending) { controller = null; clearInterval(interval); setBusy(false); }
    }
  });
  retry.addEventListener('click', preparePorts);
  element.querySelector('[data-action="back"]').addEventListener('click', () => { cancel(); onBack?.(); });

  return {
    element, showGlobe: true,
    enter({ autoSubmit = false } = {}) {
      active = true;
      const revision = ++entryRevision;
      showStatus('');
      inputs.departure.min = new Date().toISOString().slice(0, 10);
      inputs.departure.value = shipment.departure;
      preparePorts().then(ready => {
        if (ready && active && revision === entryRevision && autoSubmit) form.requestSubmit();
      });
      getGlobe()?.flyToRegion([62, 26], 1.1);
    },
    leave() { active = false; entryRevision++; cancel(); }
  };
}
