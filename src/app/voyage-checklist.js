import { checklistItems, toggleAllChecklistItems, checklistExportInput, curateChecklist } from '../data/checklist.js';
import { api } from '../api/client.js';
import { sourceList, formattedText } from '../globe/issue-content.js';

const NAMES = { security: 'Security & insurance', environment: 'Environment & emissions', trade: 'Customs & port charges',
  sanctions: 'Sanctions & registry', dangerous_goods: 'Dangerous goods', congestion: 'Port operations' };
const readable = value => String(value || '').replaceAll('_', ' ');
const make = (tag, className, text) => {
  const el = document.createElement(tag); if (className) el.className = className;
  if (text != null) el.textContent = text; return el;
};

export function createVoyageChecklist(parent) {
  const dialog = document.createElement('dialog');
  dialog.className = 'voyage-checklist'; dialog.setAttribute('aria-labelledby', 'checklist-title');
  dialog.innerHTML = `
    <header class="voyage-checklist__head"><div><p class="mono-label">VOYAGE PREPARATION</p><h2 id="checklist-title">Voyage checklist</h2></div>
      <button type="button" class="dialog-close" aria-label="Close voyage checklist">×</button></header>
    <p class="checklist-banner checklist-error" role="alert" hidden></p>
    <div class="voyage-checklist__body"></div>
    <footer class="voyage-checklist__footer"><span class="voyage-checklist__count" role="status"></span>
      <div><button type="button" class="button button--quiet" data-checklist="select-all">Select all</button>
      <button type="button" class="button button--quiet" data-checklist="refresh">Refresh</button>
      <button type="button" class="button button--quiet" data-checklist="pdf">PDF only</button>
      <button type="button" class="button button--primary" data-checklist="export">Download package</button><a class="checklist-download" data-checklist="download" hidden download="SmoothSail-voyage-checklist.pdf">Download PDF</a></div></footer>`;
  parent.append(dialog);
  const body = dialog.querySelector('.voyage-checklist__body'), count = dialog.querySelector('[role="status"]');
  const refresh = dialog.querySelector('[data-checklist="refresh"]'), exportButton = dialog.querySelector('[data-checklist="export"]');
  const pdfButton = dialog.querySelector('[data-checklist="pdf"]');
  const selectAll = dialog.querySelector('[data-checklist="select-all"]');
  const download = dialog.querySelector('[data-checklist="download"]');
  const errorMessage = dialog.querySelector('[role="alert"]');
  const sessions = new WeakMap();
  let downloadUrl;
  function clearDownload() {
    download.hidden = true; download.removeAttribute('href');
    if (downloadUrl) { const old = downloadUrl; setTimeout(() => URL.revokeObjectURL(old), 60000); downloadUrl = null; }
  }
  function showError(message = '') { errorMessage.textContent = message; errorMessage.hidden = !message; }
  let state, routeId, session, result, revision = 0, exporting = false;
  function request() { return { analysisId: state.context.analysisId, contextToken: state.context.contextToken, routeId }; }
  function progress() {
    refresh.disabled = Boolean(session?.pending);
    const items = checklistItems(result);
    count.textContent = result ? `${items.filter(i => session.checked.has(i.id)).length} of ${items.length} checked` : '';
    exportButton.disabled = !result || exporting;
    pdfButton.disabled = !result || exporting;
    selectAll.disabled = !items.length;
    selectAll.textContent = items.length && items.every(item => session.checked.has(item.id)) ? 'Deselect all' : 'Select all';
  }
  function field(container, label, value) {
    if (!value) return;
    const block = make('div', 'checklist-field'); block.append(make('span', 'mono-label', label), formattedText('rich-text', value)); container.append(block);
  }
  function section(title) { const el = make('section', 'checklist-section'); el.append(make('h3', '', title)); body.append(el); return el; }
  function itemCard(item, document = false) {
    const card = make('article', 'checklist-item'), row = make('div', 'checklist-item__head');
    const checkbox = make('input'); checkbox.type = 'checkbox'; checkbox.dataset.itemId = item.id; checkbox.checked = session.checked.has(item.id);
    checkbox.setAttribute('aria-label', `Completed: ${item.title}`);
    checkbox.addEventListener('change', () => { clearDownload(); checkbox.checked ? session.checked.add(item.id) : session.checked.delete(item.id); progress(); });
    const detail = make('details'), summary = make('summary');
    summary.append(make('span', 'checklist-item__title', item.title), make('span', 'mono-label',
      document ? readable(item.applicability) : `${NAMES[item.category]} · ${readable(item.status)}`));
    detail.append(summary);
    if (item.portIds?.length) detail.append(make('p', 'checklist-ports', item.portIds.join(' · ')));
    if (document) {
      field(detail, 'Purpose', item.purpose);
      field(detail, 'Provider / issuer', item.provider || 'Confirm with the responsible authority or provider.');
      field(detail, 'Timing', item.timing || 'Not verified; confirm before arranging shipment.');
      field(detail, 'How to obtain', item.obtainInstructions || 'Contact the responsible authority or provider.');
      field(detail, 'Related actions', item.actionIds.map(id => result.actions.find(a => a.id === id)?.title).filter(Boolean).join('; '));
    } else {
      // Keep the actual recommendation visible even with explanation collapsed.
      summary.append(formattedText('checklist-action rich-text', item.action));
      field(detail, 'Why this matters', item.explanation);
      if (item.origin === 'operational_follow_up') detail.append(make('p', 'checklist-note', 'Operational follow-up based on current congestion reporting.'));
    }
    if (item.missingInputs?.length) {
      detail.append(make('span', 'mono-label', 'Information needed'));
      const list = make('ul'); item.missingInputs.forEach(text => list.append(make('li', '', text))); detail.append(list);
    }
    if (item.evidence?.length) { detail.append(make('span', 'mono-label', 'Sources'), sourceList(item.evidence)); }
    else detail.append(make('p', 'checklist-note', 'No verified source attached. Confirm applicability before acting.'));
    const label = make('label', 'checklist-notes', 'Your notes'); const notes = make('textarea');
    notes.rows = 2; notes.maxLength = 1000; notes.placeholder = 'Owner, reference number, next step…'; notes.value = session.notes[item.id] || '';
    notes.addEventListener('input', () => { clearDownload(); session.notes[item.id] = notes.value; }); label.append(notes); detail.append(label);
    row.append(checkbox, detail); card.append(row); return card;
  }
  function render() {
    body.replaceChildren();
    body.append(make('p', 'checklist-voyage', `${result.voyage.origin} → ${result.voyage.destination} · ${readable(result.route.strategy)}`));
    body.append(make('p', 'checklist-note', `Departure: ${result.voyage.departureTime || 'Not specified'} · Created ${new Date(result.generatedAt).toLocaleString()}`));
    if (result.partial) body.append(make('p', 'checklist-banner', 'Research is still running. This snapshot includes results returned so far; refresh when the remaining checks finish.'));
    if (result.researchStatus === 'unavailable') body.append(make('p', 'checklist-banner', 'Document research is unavailable. Your recommended actions are included. Refresh to retry.'));
    body.append(make('p', 'checklist-note', result.notice));
    body.append(make('p', 'checklist-note', 'Download package includes the checklist PDF, available blank forms and references, and instructions for every listed document. Issued certificates and signed declarations must be obtained from their provider.'));
    const actions = section(`Recommended actions (${result.actions.length})`);
    if (!result.actions.length) actions.append(make('p', '', 'No actions returned for this route. Check research coverage below; this does not establish clearance.'));
    for (const item of result.actions) actions.append(itemCard(item));
    const docs = section(`Documents to prepare or verify (${result.documents.length})`);
    if (result.researchStatus === 'researching') docs.append(make('p', 'checklist-loading', 'Researching supporting documents… You can review and check off the actions now.'));
    else if (!result.documents.length) docs.append(make('p', '', 'No documents identified in this pass. This does not mean no documents are required.'));
    for (const item of result.documents) docs.append(itemCard(item, true));
    const coverage = section('Research coverage & unresolved information');
    for (const check of result.coverage) {
      const row = make('details', 'checklist-coverage');
      row.append(make('summary', '', `${NAMES[check.category]} · ${readable(check.status)}`), formattedText('rich-text', check.summary));
      for (const note of check.notes || []) row.append(make('p', '', note)); coverage.append(row);
    }
    const gaps = make('ul'); for (const gap of result.researchGaps) gaps.append(make('li', '', gap)); coverage.append(gaps);
    progress();
  }
  function showSession() {
    result = session.result; showError(session.error || '');
    if (result) render();
    else {
      body.replaceChildren(make('p', 'checklist-loading', session.error ? 'Unable to refresh. Try Refresh again.' : 'Compiling actions and researching supporting documents…'));
      progress(); count.textContent = session.pending ? 'Researching' : '';
    }
  }
  function load() {
    const target = session;
    showError(); clearDownload();
    return curateChecklist(target, request(), input => api.createVoyageChecklist(input), () => {
      // Background completion must never overwrite another route's open checklist.
      if (session === target && dialog.open) showSession();
    });
  }
  function close() { clearDownload(); dialog.close(); }
  dialog.querySelector('.dialog-close').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  refresh.addEventListener('click', load);
  selectAll.addEventListener('click', () => {
    if (!result) return;
    clearDownload(); toggleAllChecklistItems(result, session.checked);
    for (const checkbox of body.querySelectorAll('input[data-item-id]')) checkbox.checked = session.checked.has(checkbox.dataset.itemId);
    progress();
  });
  async function exportFile(format) {
    if (!result || exporting) return;
    const version = revision; exporting = true; progress();
    const activeButton = format === 'bundle' ? exportButton : pdfButton;
    activeButton.textContent = format === 'bundle' ? 'Preparing package…' : 'Exporting…';
    showError(); clearDownload();
    try {
      const blob = await api.exportVoyageChecklist(checklistExportInput(state.context, result, session.checked, session.notes),
        { format });
      if (version !== revision) return;
      download.download = format === 'bundle' ? 'SmoothSail-voyage-package.zip' : 'SmoothSail-voyage-checklist.pdf';
      download.textContent = format === 'bundle' ? 'Download ZIP' : 'Download PDF';
      downloadUrl = URL.createObjectURL(blob); download.href = downloadUrl; download.hidden = false;
      // Use an attached link; leave it available for browsers that require another explicit click.
      download.click();
    } catch (error) {
      if (version === revision && error.name !== 'AbortError') showError(error.message);
    } finally { exporting = false; exportButton.textContent = 'Download package'; pdfButton.textContent = 'PDF only'; if (dialog.open) progress(); }
  }
  exportButton.addEventListener('click', () => exportFile('bundle'));
  pdfButton.addEventListener('click', () => exportFile('pdf'));
  return {
    open(nextState, selectedRouteId) {
      state = nextState; routeId = selectedRouteId;
      let voyages = sessions.get(state); if (!voyages) { voyages = new Map(); sessions.set(state, voyages); }
      const key = `${routeId}:${state.context.contextSha256}`;
      if (!voyages.has(key)) voyages.set(key, { checked: new Set(), notes: {}, result: null, pending: null, error: null });
      const nextSession = voyages.get(key);
      if (session !== nextSession) { revision++; clearDownload(); }
      session = nextSession; result = session.result;
      if (!dialog.open) dialog.showModal();
      showSession();
      if (!session.pending && (!result || result.researchStatus === 'researching')) load();
    }, close
  };
}
