import { renderRichText } from '../app/rich-text.js';
import { icon } from '../app/icons.js';

/** Two-level presentation over existing live finding content, never demo alerts. */
export function enhanceAlertCard(card) {
  const list = card.querySelector('.congestion-card__issues');
  const refresh = (target = card) => target.classList.toggle('has-active-issue', Boolean(target.querySelector('details.congestion-card__issue[open]')));
  for (const details of list.querySelectorAll(':scope > li > details.congestion-card__issue')) {
    if (details.dataset.presentationReady) continue;
    const summary = details.querySelector(':scope > summary');
    const body = details.querySelector(':scope > .congestion-card__details');
    if (!summary || !body) continue;
    details.dataset.presentationReady = 'true';
    const title = summary.textContent.trim();
    const level = details.dataset.level || card.dataset.level || 'info';
    const meta = document.createElement('span'); meta.className = 'port-alert__meta mono-label';
    const severity = document.createElement('span'); severity.className = 'port-alert__severity';
    severity.textContent = level === 'high' ? 'High' : level === 'mild' ? 'Medium' : 'Review';
    const category = document.createElement('span'); category.textContent = details.dataset.category || 'Port congestion';
    meta.append(severity, category);
    const heading = document.createElement('span'); heading.className = 'port-alert__title'; renderRichText(heading, title, [], { inline: true });
    const arrow = document.createElement('span'); arrow.className = 'port-alert__arrow'; arrow.innerHTML = icon('arrow-right');
    summary.replaceChildren(meta, heading, arrow);
    summary.setAttribute('aria-label', heading.textContent);
    const back = document.createElement('button'); back.type = 'button'; back.className = 'port-alert__back';
    back.innerHTML = `${icon('arrow-left')}<span>Back to port alerts</span>`;
    back.addEventListener('click', () => { details.open = false; refresh(details.closest('.congestion-card')); summary.focus(); });
    const detailTitle = document.createElement('h3'); detailTitle.className = 'port-alert__detail-title'; renderRichText(detailTitle, title, [], { inline: true });
    const detailMeta = meta.cloneNode(true);
    body.prepend(back, detailMeta, detailTitle);
    details.addEventListener('toggle', () => {
      const currentCard = details.closest('.congestion-card');
      if (!currentCard) return;
      if (details.open) for (const other of currentCard.querySelectorAll('details.congestion-card__issue[open]')) if (other !== details) other.open = false;
      refresh(currentCard);
    });
  }
  refresh();
  return card;
}
