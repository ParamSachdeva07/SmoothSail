import { enhanceAlertCard } from './alert-presentation.js';
import { formattedText, sourceList } from './issue-content.js';
export { evidenceLink } from './issue-content.js';
import { CATEGORY_NAMES, readableInputLabel } from '../data/compliance.js';
import { createCongestionCard } from './port-congestion.js';
import { issueLevel } from '../data/congestion.js';

function node(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className || ''; element.textContent = text || '';
  return element;
}

export function findingDisclosure(finding, onLearnMore) {
  const details = node('details', 'congestion-card__issue');
  details.dataset.issueId = finding.id;
  details.dataset.category = CATEGORY_NAMES[finding.category] || 'Voyage compliance';
  const needsReview = !finding.demo && ['needs_input', 'unverified'].includes(finding.status);
  details.dataset.level = needsReview ? 'info' : finding.severity === 'red' ? 'high' : finding.severity === 'yellow' ? 'mild' : 'info';
  const summary = node('summary', 'congestion-card__level');
  summary.setAttribute('aria-label', finding.title);
  summary.append(node('span', 'congestion-dot'), document.createTextNode(finding.title));
  const body = node('div', 'congestion-card__details');
  body.append(formattedText('congestion-card__summary', finding.explanation, finding.evidence));
  const statusLabels = { needs_input: 'Needs details', unverified: 'Not verified', estimated: 'Estimated', confirmed: 'Confirmed' };
  body.append(node('p', 'congestion-card__meta port-alert__status', statusLabels[finding.status] || finding.status));
  if (finding.recommendedAction) body.append(node('h4', 'congestion-card__eyebrow', 'Recommended action'),
    formattedText('port-alert__recommendation', finding.recommendedAction, finding.evidence));
  if (finding.cost) {
    const basis = { vessel_voyage: 'Whole-vessel voyage', port_call: 'Port call', cargo_shipment: 'Cargo shipment', container_day: 'Container per day' };
    body.append(node('h4', 'congestion-card__eyebrow', 'Estimated cost'), node('p', 'compliance-cost',
      `${new Intl.NumberFormat('en-GB', { style: 'currency', currency: finding.cost.currency }).format(finding.cost.amount)} · ${basis[finding.cost.basis] || readableInputLabel(finding.cost.basis)}`));
  }
  if (finding.cost?.assumptions?.length) {
    const list = node('ul', 'port-alert__requirements');
    for (const assumption of finding.cost.assumptions) { const item = node('li'); item.append(formattedText('', assumption)); list.append(item); }
    body.append(list);
  }
  if (finding.missingInputs?.length) {
    body.append(node('h4', 'congestion-card__eyebrow', 'Details needed'));
    const list = node('ul', 'port-alert__requirements');
    for (const value of finding.missingInputs) { const item = node('li'); item.append(formattedText('', readableInputLabel(value))); list.append(item); }
    body.append(list);
  }
  if (finding.evidence?.length) body.append(node('h4', 'congestion-card__eyebrow', 'Sources'), sourceList(finding.evidence));
  if (onLearnMore && !finding.demo) {
    const button = node('button', 'button button--primary port-alert__ask', 'Ask');
    button.type = 'button'; button.addEventListener('click', () => onLearnMore(finding));
    const actions = node('footer', 'port-alert__actions'); actions.append(button);
    body.append(actions);
  }
  details.append(summary, body); return details;
}

export function createPortIssuesCard(port, assessment, findings, onReroute, onLearnMore) {
  const card = issueLevel(assessment) ? createCongestionCard(port, assessment, onReroute) : node('section', 'congestion-card');
  let list = card.querySelector('.congestion-card__issues');
  if (!list) {
    card.append(node('p', 'congestion-card__eyebrow', 'Voyage checks'), node('h3', 'congestion-card__title', port.name));
    list = node('ul', 'congestion-card__issues'); card.append(list);
  }
  for (const finding of findings) {
    const item = node('li'); item.append(findingDisclosure(finding, onLearnMore)); list.append(item);
  }
  return enhanceAlertCard(card);
}
