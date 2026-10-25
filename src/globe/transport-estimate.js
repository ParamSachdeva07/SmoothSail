import { transferCostLabel } from '../data/reroute.js';
import { sourceList } from './issue-content.js';

export function transportEstimate(transfer) {
  const block = document.createElement('section'); block.className = 'transfer-estimate';
  if (!transfer) return block;
  const add = (tag, text, className = '') => {
    const el = document.createElement(tag); el.textContent = text; el.className = className; block.append(el); return el;
  };
  add('h4', 'Additional ground transport', 'congestion-card__eyebrow');
  add('p', transferCostLabel(transfer), 'transfer-estimate__cost');
  add('p', `${transfer.originPortId} → ${transfer.destinationPortId}`);
  if (transfer.status === 'estimated') add('p', `${transfer.distanceKm} km · ${transfer.drivingHours} h driving · one-way road scenario`);
  add('p', transfer.note || 'Arrange a local carrier quote.', 'congestion-card__meta');
  const details = add('details', '', 'transfer-estimate__assumptions');
  const summary = document.createElement('summary'); summary.textContent = 'Basis and exclusions'; details.append(summary);
  const list = document.createElement('ul');
  for (const assumption of transfer.assumptions || []) { const li = document.createElement('li'); li.textContent = assumption; list.append(li); }
  details.append(list);
  const air = document.createElement('p'); air.textContent = `Air: ${transfer.air?.reason || 'Requires a cargo-specific quote.'}`; details.append(air);
  if (transfer.sources?.length) details.append(sourceList(transfer.sources));
  return block;
}
