export const COMPLIANCE_CATEGORIES = ['security', 'environment', 'trade', 'sanctions', 'dangerous_goods', 'congestion'];
export const CATEGORY_NAMES = { security: 'Security & insurance', environment: 'Environment', trade: 'Tariffs & documents',
  sanctions: 'Sanctions & vessel', dangerous_goods: 'Dangerous goods', congestion: 'Congestion' };

export function findingsForPort(findings, routeId, portId) {
  const seen = new Set();
  return (findings ?? []).filter(f => {
    if (seen.has(f.id) || !f.scope?.routeIds?.includes(routeId) || !f.scope?.portIds?.includes(portId)) return false;
    const supportedAlert = ['yellow', 'red'].includes(f.severity) && ['confirmed', 'estimated'].includes(f.status)
      && f.evidence?.some(e => e.authority === 'official');
    const informationGap = ['needs_input', 'unverified'].includes(f.status);
    if (!supportedAlert && !informationGap) return false;
    seen.add(f.id); return true;
  });
}

export function categoryProgress(state, category) {
  const check = state?.checks?.[category];
  const status = check?.status || (state?.complete ? 'unavailable' : 'researching');
  const labels = { unavailable: 'Unavailable', researching: 'Researching' };
  const phase = ['completed', 'needs_input', 'not_applicable'].includes(status) ? 'done' : status;
  const label = phase === 'done' ? 'Research complete' : !check && state?.error ? 'Interrupted' :
    check?.reason === 'not_configured' ? 'Not configured' : labels[status] || 'Returned';
  return { category, name: CATEGORY_NAMES[category], status, phase, label,
    description: [check?.summary, ...(check?.coverageNotes ?? [])].filter(Boolean).join(' ') };
}

export function coverageSummary(state) {
  if (!state) return 'Compliance unavailable';
  const checks = Object.values(state.checks);
  const finished = checks.length;
  const gaps = checks.filter(c => ['unavailable', 'needs_input'].includes(c.status)).length;
  if (state.error) return `${finished}/6 checks returned · interrupted`;
  return `${finished}/6 checks ${state.complete ? 'returned' : 'returned · researching…'}${gaps ? ` · ${gaps} need data` : ''}`;
}
export function formatEvidenceMarkers(answer, evidence = []) {
  const numbers = new Map(evidence.map((source, index) => [source.id, index + 1]));
  return answer.replace(/\[([^\]\n]+)\]/g, (marker, contents) => {
    const ids = contents.split(/[,;]\s*/).map(id => id.trim());
    return ids.every(id => numbers.has(id)) ? `[${ids.map(id => numbers.get(id)).join(', ')}]` : marker;
  });
}
