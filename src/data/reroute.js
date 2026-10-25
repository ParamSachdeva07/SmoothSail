export function rerouteRequest(report, route, change, originalInput = {}) {
  if (![report.origin, report.destination].includes(change.portId)) throw new Error('This port does not belong to the selected voyage.');
  const alternative = change.alternativePort?.portId;
  if (!/^[A-Z]{2}[A-Z0-9]{3}$/.test(alternative || '') || [report.origin, report.destination].includes(alternative)) {
    throw new Error('Choose a different supported alternative port.');
  }
  return { original: { ...originalInput, origin: report.origin, destination: report.destination, departureTime: report.departureTime },
    affectedPortId: change.portId, alternativePortId: alternative, strategy: route.strategy };
}

export function transferCostLabel(transfer) {
  const cost = transfer?.cost;
  if (!cost || !Number.isFinite(cost.low) || !Number.isFinite(cost.high)) return 'Transfer quote needed';
  const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: cost.currency, maximumFractionDigits: 0 }).format(value);
  return `${money(cost.low)}–${money(cost.high)} per 40-foot container`;
}
