import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { formatEvidenceMarkers } from '../data/compliance.js';
import { evidenceTarget } from '../data/evidence.js';

/** Shared safe formatting for agent prose in chat and port explanations. */
export function renderRichText(element, text, evidence = [], { inline = false } = {}) {
  const targets = evidence.map(source => evidenceTarget(source));
  const downloads = new Set(targets.filter(target => target?.download)
    .map(target => new URL(target.href, document.baseURI).href));
  const cited = formatEvidenceMarkers(String(text ?? ''), evidence).replace(/\[(\d+(?:,\s*\d+)*)\]/g, (marker, group) => {
    const indexes = group.split(/,\s*/).map(Number);
    if (!indexes.every(index => targets[index - 1])) return marker;
    return indexes.map(index => {
      return `[\\[${index}\\]](${targets[index - 1].href.replaceAll(')', '%29')})`;
    }).join(' ');
  });
  const html = (inline ? marked.parseInline : marked.parse)(cited, { breaks: true, gfm: true, async: false });
  element.classList.add('rich-text');
  element.innerHTML = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'blockquote', 'pre', 'code', 'a', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
    ALLOWED_ATTR: ['href', 'title', 'start'], ALLOW_DATA_ATTR: false
  });
  for (const link of element.querySelectorAll('a')) {
    try {
      const url = new URL(link.getAttribute('href'), document.baseURI);
      if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Unsupported link');
      link.href = url.href;
      if (downloads.has(url.href)) { link.download = ''; link.title = 'Download stored source document'; }
      else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      const citation = /^\[(\d+)\]$/.exec(link.textContent);
      if (citation) {
        const index = Number(citation[1]), source = evidence[index - 1], target = targets[index - 1];
        if (source && target && new URL(target.href, document.baseURI).href === url.href) {
          link.classList.add('citation-pill');
          link.setAttribute('aria-label', `${target.download ? 'Download source' : 'Open source'} ${index}: ${source.title || 'Reference'}`);
          link.title = `${source.title || 'Reference'}${target.download ? ' · Download document' : ' · Open source'}`;
        }
      }
    } catch { link.replaceWith(document.createTextNode(link.textContent)); }
  }
  for (const table of element.querySelectorAll('table')) {
    const scroll = document.createElement('div'); scroll.className = 'chat-table';
    table.replaceWith(scroll); scroll.append(table);
  }
}
