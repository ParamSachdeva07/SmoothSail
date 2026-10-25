import { api } from '../api/client.js';
import { evidenceLink } from '../globe/port-issues.js';
import { renderRichText } from './rich-text.js';
import { icon } from './icons.js';

export function createComplianceChat(container) {
  const element = document.createElement('aside');
  element.className = 'compliance-chat'; element.hidden = true;
  element.setAttribute('aria-label', 'Compliance research chat');
  element.innerHTML = `
    <header class="compliance-chat__header">
      <span class="compliance-chat__avatar" aria-hidden="true">${icon('ship', 19)}</span>
      <div><h2>Voyage assistant</h2><p>Cited answers for your voyage</p></div>
      <button type="button" class="compliance-chat__close" aria-label="Close compliance chat">×</button>
    </header>
    <div class="compliance-chat__context"><span class="mono-label">Discussing</span><p data-role="topic"></p></div>
    <div class="compliance-chat__messages" role="log" aria-live="polite" aria-relevant="additions text" aria-label="Conversation"></div>
    <form class="compliance-chat__composer">
      <label class="sr-only" for="compliance-question">Your question</label>
      <textarea id="compliance-question" rows="2" placeholder="Ask about this issue…" maxlength="4000" required></textarea>
      <div class="compliance-chat__composer-actions"><span>Enter to send · Shift + Enter for a new line</span>
        <button type="submit" aria-label="Send message"><span>Send</span>${icon('arrow-right', 15)}</button></div>
    </form>`;
  container.append(element);
  const messages = element.querySelector('[role="log"]'), input = element.querySelector('textarea');
  const form = element.querySelector('form'), send = element.querySelector('[type="submit"]');
  let context = null, controller = null, revision = 0, history = [], previousFocus = null;
  function bottom() { messages.scrollTop = messages.scrollHeight; }
  function message(text, role, evidence = []) {
    const article = document.createElement('article'); article.className = `compliance-chat__message compliance-chat__message--${role}`;
    const actor = document.createElement('p'); actor.className = 'compliance-chat__actor'; actor.textContent = role === 'user' ? 'You' : 'Voyage assistant';
    const bubble = document.createElement('div'); bubble.className = 'compliance-chat__bubble';
    if (role === 'user') bubble.textContent = text;
    else renderRichText(bubble, text, evidence);
    article.append(actor, bubble); messages.append(article); bottom();
    return { article, bubble };
  }
  function addSources(parent, evidence = []) {
    if (!evidence.length) return;
    const details = document.createElement('details'); details.className = 'compliance-chat__sources';
    const summary = document.createElement('summary'); summary.textContent = `${evidence.length} source${evidence.length === 1 ? '' : 's'}`;
    details.append(summary);
    for (const [index, source] of evidence.entries()) {
      const link = evidenceLink({ ...source, title: `[${index + 1}] ${source.title}` });
      if (link) details.append(link);
    }
    parent.append(details);
  }
  function close() {
    element.hidden = true; controller?.abort(); controller = null; revision++;
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
  }
  element.querySelector('header button').addEventListener('click', close);
  element.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (!context || !input.value.trim() || controller) return;
    const question = input.value.trim(); input.value = '';
    message(question, 'user');
    const response = message('Researching sources…', 'assistant');
    response.article.dataset.loading = 'true';
    const current = revision, pending = new AbortController(); controller = pending; send.disabled = true;
    try {
      const result = await api.complianceChat({ ...context, question, history: history.slice(-12) }, { signal: pending.signal });
      if (current !== revision) return;
      renderRichText(response.bubble, result.answer, result.evidence ?? []);
      addSources(response.article, result.evidence); bottom();
      history.push({ role: 'user', content: question }, { role: 'assistant', content: result.answer });
    } catch (error) {
      if (current === revision) {
        response.bubble.textContent = error.message; response.article.dataset.error = 'true';
        if (!input.value) input.value = question;
      }
    } finally {
      response.article.removeAttribute('data-loading');
      if (controller === pending) {
        controller = null; send.disabled = false;
        if (!element.hidden) input.focus({ preventScroll: true });
      }
    }
  });
  return {
    open(finding, state, routeId = null) {
      previousFocus = document.activeElement;
      controller?.abort(); controller = null; revision++; history = [];
      context = state.context?.contextToken ? { analysisId: state.context.analysisId,
        contextToken: state.context.contextToken, findingId: finding.id } :
        { finding, routeReport: state.report, cargoText: state.cargoText, documentReferences: state.documentReferences };
      if (routeId) context.routeId = routeId;
      element.querySelector('[data-role="topic"]').textContent = finding.title;
      messages.replaceChildren(); input.value = ''; send.disabled = false;
      const intro = message('I can help explain this issue, the information you need and possible next steps. What would you like to know?', 'assistant');
      const summary = document.createElement('details'); summary.className = 'compliance-chat__issue-summary';
      const label = document.createElement('summary'); label.textContent = 'View issue summary';
      const body = document.createElement('div'); body.className = 'compliance-chat__bubble';
      renderRichText(body, finding.explanation, finding.evidence ?? []);
      addSources(body, finding.evidence);
      summary.append(label, body); intro.article.append(summary);
      element.hidden = false; messages.scrollTop = 0; input.focus({ preventScroll: true });
    }, close
  };
}
