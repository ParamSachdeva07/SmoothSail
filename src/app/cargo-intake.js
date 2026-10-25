import { api } from '../api/client.js';
import { shipment } from '../data/shipment.js';

/** Native dialog provides focus containment and Escape; uploads stay in memory. */
export function requestCargoDetails(parent) {
  const previousFocus = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'cargo-dialog';
  dialog.setAttribute('aria-labelledby', 'intake-title');
  dialog.innerHTML = `
    <form novalidate>
      <header class="cargo-dialog__head">
        <div><p class="mono-label">Compliance details · Optional</p><h2 id="intake-title">Vessel &amp; cargo information</h2></div>
        <button class="dialog-close" type="button" autofocus data-action="cancel" aria-label="Close">×</button>
      </header>
      <p class="cargo-dialog__intro">Share your vessel manifest and IMO number so we can give you more detailed compliance information. Every field is optional.</p>
      <label class="field"><span class="field__label">Vessel manifest or documents</span>
        <input class="field__input field__file" type="file" name="manifest" accept=".pdf,.docx,.txt,.csv,.md" multiple></label>
      <p class="mono-label cargo-dialog__upload" data-role="upload-status" role="status"></p>
      <p class="field__note">Readable PDF, DOCX or text · 10 MiB per file · Session only</p>
      <label class="field"><span class="field__label">IMO number</span>
        <input class="field__input" type="text" name="imo" inputmode="numeric" autocomplete="off" placeholder="IMO 1234567" maxlength="11"></label>
      <label class="field"><span class="field__label">Other notes (cargo type, flag state, previous ports)</span>
        <textarea class="field__input field__textarea" name="notes" rows="4"></textarea></label>
      <label class="cargo-dialog__skip"><input type="checkbox" name="skip"><span>Continue without filling in information</span></label>
      <p class="form-status" role="alert"></p>
      <footer class="cargo-dialog__actions">
        <button class="button button--secondary" type="button" data-action="cancel">Cancel</button>
        <button class="button button--primary" type="submit">Submit</button>
      </footer>
    </form>`;
  parent.append(dialog);
  const form = dialog.querySelector('form'), file = form.elements.manifest;
  let manifestText = shipment.manifestText || '', references = [...shipment.documentReferences];
  let reading = false, revision = 0;
  const controller = new AbortController();
  form.elements.imo.value = shipment.imoNumber || '';
  form.elements.notes.value = shipment.cargoNotes || '';
  const uploadStatus = dialog.querySelector('[data-role="upload-status"]');
  if (manifestText) uploadStatus.textContent = 'Previous document text is ready for this session.';
  const status = dialog.querySelector('[role="alert"]');
  file.addEventListener('change', async () => {
    const files = [...file.files]; if (!files.length) return;
    const version = ++revision; reading = true;
    form.querySelector('[type="submit"]').disabled = true;
    status.textContent = ''; uploadStatus.textContent = 'Reading documents…';
    try {
      if (files.some(item => item.size > 10 * 1024 * 1024)) throw new Error('Each document must be 10 MiB or smaller.');
      const results = [];
      for (const item of files) results.push(await api.extractDocument(item, { signal: controller.signal }));
      if (version !== revision || !dialog.isConnected) return;
      const text = results.map(result => result.text).join('\n\n');
      const refs = results.flatMap(result => result.references);
      if (text.length > 200000 || refs.length > 200) throw new Error('Combined documents exceed 200,000 characters or 200 sections. Use fewer documents.');
      manifestText = text; references = refs;
      uploadStatus.textContent = `${files.length} document${files.length === 1 ? '' : 's'} · ${refs.length} sections ready`;
    } catch (error) {
      if (!controller.signal.aborted) { status.textContent = error.message; file.value = ''; uploadStatus.textContent = manifestText ? 'Previous document text retained.' : ''; }
    } finally {
      reading = false; form.querySelector('[type="submit"]').disabled = false;
    }
  });
  form.elements.skip.addEventListener('change', () => {
    for (const input of [file, form.elements.imo, form.elements.notes]) input.disabled = form.elements.skip.checked;
  });
  return new Promise(resolve => {
    let settled = false;
    const finish = value => {
      if (settled) return; settled = true; controller.abort(); dialog.close(); dialog.remove(); previousFocus?.focus(); resolve(value);
    };
    dialog.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
    dialog.addEventListener('click', event => { if (event.target.closest('[data-action="cancel"]')) finish(null); });
    form.addEventListener('submit', event => {
      event.preventDefault(); if (reading) return;
      const skip = form.elements.skip.checked;
      const imoNumber = skip ? '' : form.elements.imo.value.trim().replace(/^IMO\s*/i, '');
      if (imoNumber && !/^\d{7}$/.test(imoNumber)) { status.textContent = 'Enter a 7-digit IMO number or leave it blank.'; form.elements.imo.focus(); return; }
      const notes = skip ? '' : form.elements.notes.value.trim();
      const cargoText = skip ? '' : [manifestText, notes].filter(Boolean).join('\n\n');
      if (cargoText.length > 200000) { status.textContent = 'Combined cargo text is too long. Use a smaller document or fewer notes.'; return; }
      finish({ cargoText, documentReferences: skip ? [] : references, imoNumber,
        manifestText: skip ? '' : manifestText, cargoNotes: notes });
    });
    dialog.showModal();
  });
}
