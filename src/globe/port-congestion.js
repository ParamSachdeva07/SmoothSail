import { formattedText, sourceList } from './issue-content.js';
import { issueLevel } from '../data/congestion.js';
import { transportEstimate } from './transport-estimate.js';

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function sourceLink(source) {
  try {
    const url = new URL(source?.url);
    if (!['https:', 'http:'].includes(url.protocol)) return null;
    const link = node('a', 'congestion-card__source', source.title || url.hostname);
    link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  } catch { return null; }
}

function dateLabel(value) {
  const when = new Date(value);
  return Number.isFinite(when.getTime()) ? when.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'
  }) + ' UTC' : 'Date unavailable';
}

export function createCongestionCard(port, assessment, onReroute) {
  const card = node('section', 'congestion-card');
  card.setAttribute('aria-label', `${port.name} port congestion`);
  card.dataset.level = assessment.level;
  card.append(node('p', 'congestion-card__eyebrow', 'Port conditions'),
    node('h3', 'congestion-card__title', port.name));
  const list = node('ul', 'congestion-card__issues');
  const item = node('li');
  const disclosure = node('details', 'congestion-card__issue');
  disclosure.dataset.issueId = 'congestion';
  const level = node('summary', 'congestion-card__level');
  level.append(node('span', 'congestion-dot'), document.createTextNode(
    assessment.level === 'high' ? 'High congestion' : 'Mild congestion'));
  const body = node('div', 'congestion-card__details');
  body.append(formattedText('congestion-card__summary', assessment.summary));
  body.append(node('p', 'congestion-card__meta',
    `${assessment.basis === 'measured' ? 'Measured conditions' : 'Reported conditions'} · ${dateLabel(assessment.evidenceAsOf)}`));
  const alt = assessment.alternativePort;
  const alternative = node('div', 'congestion-card__alternative');
  alternative.append(node('p', 'congestion-card__eyebrow', 'Closest supported alternative'));
  if (alt) {
    alternative.append(node('h4', '', `${alt.name} · ${alt.portId}`),
      ...(Number.isFinite(alt.distanceNm) ? [node('p', '', `${Math.round(alt.distanceNm)} nm away · straight-line distance`)] : []),
      node('p', '', alt.congestionLevel === 'unknown' ? 'Congestion has not been assessed at this alternative.' : `${alt.congestionLevel} reported congestion.`),
      node('p', 'congestion-card__meta', 'Candidate only · service and shipment suitability need checking.'));
    const link = sourceLink(alt.source);
    if (link) alternative.append(link);
    if (alt.onwardTransport) alternative.append(transportEstimate(alt.onwardTransport));
    if (onReroute) {
      const reroute = node('button', 'congestion-card__reroute', 'Reroute');
      reroute.type = 'button';
      reroute.setAttribute('aria-label', `Reroute via ${alt.name}`);
      const status = node('p', 'congestion-card__meta');
      status.setAttribute('role', 'alert');
      reroute.addEventListener('click', async event => {
        event.stopPropagation();
        if (reroute.disabled) return;
        reroute.disabled = true;
        status.textContent = ''; reroute.textContent = 'Calculating alternative…';
        try { await onReroute({ portId: port.code, alternativePort: alt }); reroute.textContent = 'Alternative shown'; }
        catch (error) { status.textContent = error.name === 'AbortError' ? 'Alternative calculation cancelled.' : error.message; reroute.textContent = 'Reroute'; }
        finally { reroute.disabled = false; }
      });
      alternative.append(reroute, status);
    }
  } else alternative.append(node('p', '', 'No other supported port is available.'));
  body.append(alternative);
  {
    const sources = node('div', 'congestion-card__sources');
    sources.append(node('p', 'congestion-card__eyebrow', 'Sources'));
    sources.append(sourceList(assessment.sources ?? []));
    body.append(sources, node('p', 'congestion-card__meta', 'Recent reports · not a forecast for your arrival.'));
  }
  for (const note of assessment.qualityNotes || []) body.append(node('p', 'congestion-card__meta', note));
  disclosure.append(level, body);
  item.append(disclosure);
  list.append(item);
  card.append(list);
  return card;
}

/** One DOM marker per port. Mapbox positions it; no render-loop layout work. */
export function createPortMarker(port, labelText, onOpen, onExpire = () => {}) {
  const element = node('div', 'map-port-marker');
  // Mapbox defaults markers to role=img, which hides nested controls from screen readers.
  element.setAttribute('role', 'group');
  element.setAttribute('aria-label', `${port.name} port`);
  const button = node('button', 'port-issue', '1 issue');
  button.type = 'button'; button.hidden = true;
  button.setAttribute('aria-haspopup', 'dialog');
  button.setAttribute('aria-expanded', 'false');
  const label = node('span', 'map-port-label', labelText);
  element.append(button, label);
  let current = null, expiryTimer = null, issues = [];
  function paint() {
    const congestion = issueLevel(current), count = issues.length + (congestion ? 1 : 0);
    button.hidden = !count;
    button.textContent = `${count} ${count === 1 ? 'alert' : 'alerts'}`;
    button.dataset.level = congestion === 'high' || issues.some(issue => issue.severity === 'red') ? 'high'
      : congestion || issues.some(issue => issue.severity === 'yellow') ? 'mild' : 'info';
    button.setAttribute('aria-label', `${port.name}: ${count} ${count === 1 ? 'issue' : 'issues'}. Show issues`);
  }
  for (const type of ['pointerdown', 'mousedown', 'touchstart', 'dblclick']) {
    button.addEventListener(type, event => event.stopPropagation());
  }
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    if (issueLevel(current) || issues.length) onOpen(current, button);
  });
  return {
    element,
    update(assessment) {
      clearTimeout(expiryTimer);
      current = assessment;
      const level = issueLevel(assessment);
      button.hidden = !level;
      button.dataset.level = level || '';
      button.setAttribute('aria-label', `${port.name}: 1 issue, ${level || 'unknown'} congestion. Show issues`);
      const currentLow = assessment?.level === 'low' && Date.parse(assessment.refreshAfter) > Date.now();
      label.title = level ? `${level} congestion reported` : currentLow
        ? 'Recent reporting indicates low congestion.' : 'Congestion: insufficient recent information.';
      if (level || currentLow) expiryTimer = setTimeout(() => {
        paint();
        label.title = 'Congestion: insufficient recent information.';
        if (button.getAttribute('aria-expanded') === 'true') onExpire();
      }, Math.max(0, Date.parse(assessment.refreshAfter) - Date.now()));
      paint();
    },
    updateIssues(findings) { issues = findings; paint(); },
    destroy() { clearTimeout(expiryTimer); element.remove(); }
  };
}
