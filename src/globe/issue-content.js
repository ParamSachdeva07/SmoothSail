import { groupedEvidence } from '../data/compliance.js';
import { renderRichText } from '../app/rich-text.js';
import { evidenceTarget } from '../data/evidence.js';

export function formattedText(className, text, evidence = []) {
  const element = document.createElement('div'); element.className = className;
  renderRichText(element, text, evidence); return element;
}

export function evidenceLink(evidence) {
  const target = evidenceTarget(evidence);
  if (!target) {
    const paragraph = document.createElement('p'); paragraph.className = 'congestion-card__meta';
    paragraph.textContent = `${evidence.title}${evidence.pageOrSection ? ` · ${evidence.pageOrSection}` : ''}`;
    return paragraph;
  }
  const link = document.createElement('a'); link.className = 'congestion-card__source';
  link.textContent = `${evidence.title || 'Source'}${target.download ? ' ↓' : ''}`;
  link.href = target.href;
  if (target.download) {
    link.download = ''; link.title = 'Download stored source document';
  } else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
  return link;
}

export function sourceList(evidence) {
  const list = document.createElement('ul'); list.className = 'port-alert__sources';
  for (const source of groupedEvidence(evidence)) {
    const link = evidenceLink(source);
    if (link) { const item = document.createElement('li'); item.append(link); list.append(item); }
  }
  return list;
}
