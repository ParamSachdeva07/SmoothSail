import { createCongestionCard } from './port-congestion.js';
import { issueLevel } from '../data/congestion.js';

function node(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className || ''; element.textContent = text || '';
  return element;
}

export function evidenceLink(evidence) {
  if (!evidence.url) return node('p', 'congestion-card__meta',
    `${evidence.title}${evidence.pageOrSection ? ` · ${evidence.pageOrSection}` : ''}`);
  try {
    const url = new URL(evidence.url);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const link = node('a', 'congestion-card__source', evidence.title || url.hostname);
    link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  } catch { return null; }
}

export function findingDisclosure(finding, onLearnMore) {
  const details = node('details', 'congestion-card__issue');
  details.dataset.issueId = finding.id;
  const needsReview = ['needs_input', 'unverified'].includes(finding.status);
  details.dataset.level = needsReview ? 'info' : finding.severity === 'red' ? 'high' : finding.severity === 'yellow' ? 'mild' : 'info';
  const summary = node('summary', 'congestion-card__level');
  summary.setAttribute('aria-label', finding.title);
  summary.append(node('span', 'congestion-dot'), document.createTextNode(finding.title));
  const body = node('div', 'congestion-card__details');
  body.append(node('p', 'congestion-card__summary', finding.explanation));
  const statusLabels = { needs_input: 'Needs details', unverified: 'Not verified', estimated: 'Estimated', confirmed: 'Confirmed' };
  body.append(node('p', 'congestion-card__meta', statusLabels[finding.status] || finding.status));
  if (finding.recommendedAction) body.append(node('p', '', finding.recommendedAction));
  if (finding.cost) body.append(node('p', 'compliance-cost',
    `${new Intl.NumberFormat('en-GB', { style: 'currency', currency: finding.cost.currency }).format(finding.cost.amount)} · ${finding.cost.basis.replaceAll('_', ' ')}`));
  if (finding.cost?.assumptions?.length) body.append(node('p', 'congestion-card__meta', finding.cost.assumptions.join(' ')));
  if (finding.missingInputs?.length) body.append(node('p', 'congestion-card__meta', `Needed: ${finding.missingInputs.join(', ')}`));
  for (const evidence of finding.evidence ?? []) {
    const link = evidenceLink(evidence); if (link) body.append(link);
  }
  if (onLearnMore) {
    const button = node('button', 'congestion-card__reroute', 'Learn more');
    button.type = 'button'; button.addEventListener('click', () => onLearnMore(finding));
    body.append(button);
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
  return card;
}
