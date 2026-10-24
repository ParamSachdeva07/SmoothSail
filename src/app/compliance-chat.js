import { api } from '../api/client.js';
import { evidenceLink } from '../globe/port-issues.js';
import { formatEvidenceMarkers } from '../data/compliance.js';

export function createComplianceChat(container) {
  const element = document.createElement('aside');
  element.className = 'compliance-chat'; element.hidden = true;
  element.setAttribute('aria-label', 'Compliance research chat');
  element.innerHTML = `<header><span>Ask about this issue</span><button type="button" aria-label="Close compliance chat">×</button></header>
    <p class="mono-label" data-role="topic"></p><div class="compliance-chat__messages" role="log" aria-live="polite"></div>
    <form><label class="sr-only" for="compliance-question">Your question</label><input id="compliance-question" placeholder="Ask a follow-up…" maxlength="4000" required><button type="submit">Ask</button></form>`;
  container.append(element);
  const messages = element.querySelector('[role="log"]'), input = element.querySelector('input');
  let context = null, controller = null, revision = 0, history = [];
  function message(text, role) {
    const paragraph = document.createElement('p'); paragraph.textContent = text;
    paragraph.className = `compliance-chat__${role}`; messages.append(paragraph); messages.scrollTop = messages.scrollHeight;
    return paragraph;
  }
  function close() { element.hidden = true; controller?.abort(); revision++; }
  element.querySelector('header button').addEventListener('click', close);
  element.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  element.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault(); if (!context || !input.value.trim() || controller) return;
    const question = input.value.trim(); input.value = '';
    message(question, 'user'); const response = message('Researching sources…', 'assistant');
    const current = revision, pending = new AbortController(); controller = pending;
    element.querySelector('[type="submit"]').disabled = true;
    try {
      const result = await api.complianceChat({ ...context, question, history: history.slice(-12) }, { signal: pending.signal });
      if (current !== revision) return;
      response.textContent = formatEvidenceMarkers(result.answer, result.evidence);
      for (const [index, evidence] of (result.evidence ?? []).entries()) {
        const link = evidenceLink({ ...evidence, title: `[${index + 1}] ${evidence.title}` }); if (link) messages.append(link);
      }
      messages.scrollTop = messages.scrollHeight;
      history.push({ role: 'user', content: question }, { role: 'assistant', content: result.answer });
    } catch (error) { if (current === revision) response.textContent = error.message; }
    finally {
      if (controller === pending) controller = null;
      element.querySelector('[type="submit"]').disabled = false;
    }
  });
  return {
    open(finding, state) {
      controller?.abort(); controller = null; revision++; history = [];
      context = state.context?.contextToken ? { analysisId: state.context.analysisId,
        contextToken: state.context.contextToken, findingId: finding.id } :
        { finding, routeReport: state.report, cargoText: state.cargoText, documentReferences: state.documentReferences };
      element.querySelector('[data-role="topic"]').textContent = finding.title;
      messages.replaceChildren(); message(finding.explanation, 'assistant');
      element.hidden = false; input.focus();
    }, close
  };
}
