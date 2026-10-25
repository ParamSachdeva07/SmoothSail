/** Keep exports independent of the short-lived research context and the large route report. */
export const checklistItems = result => [...(result?.actions || []), ...(result?.documents || [])];

export function toggleAllChecklistItems(result, checked) {
  const ids = checklistItems(result).map(item => item.id);
  const all = ids.length > 0 && ids.every(id => checked.has(id));
  for (const id of ids) all ? checked.delete(id) : checked.add(id);
  return !all;
}

export function checklistExportSnapshot(result) {
  const sources = rows => (rows || []).map(source => Object.fromEntries([
    'id', 'title', 'url', 'documentId', 'downloadPath', 'pageOrSection', 'retrievedAt',
    'publishedAt', 'effectiveFrom', 'effectiveTo', 'sourceVersion', 'authority'
  ].filter(key => source[key] !== undefined).map(key => [key, source[key]])));
  const base = item => ({ id: item.id, title: item.title, portIds: item.portIds || [],
    missingInputs: item.missingInputs || [], evidence: sources(item.evidence) });
  return {
    id: result.id, routeId: result.routeId, generatedAt: result.generatedAt,
    voyage: { origin: result.voyage.origin, destination: result.voyage.destination, departureTime: result.voyage.departureTime ?? null },
    route: { strategy: result.route.strategy || '', eta: result.route.eta ?? null },
    actions: result.actions.map(item => ({ ...base(item), category: item.category, status: item.status,
      action: item.action, explanation: item.explanation || '', origin: item.origin || 'specialist_recommendation' })),
    documents: result.documents.map(item => ({ ...base(item), applicability: item.applicability,
      purpose: item.purpose, provider: item.provider || '', timing: item.timing || '',
      obtainInstructions: item.obtainInstructions || '', actionIds: item.actionIds,
      downloadAssets: (item.downloadAssets || []).map(asset => ({ title: asset.title, kind: asset.kind, evidence: sources([asset.evidence])[0] })) })),
    coverage: result.coverage.map(check => ({ category: check.category, status: check.status,
      summary: check.summary, notes: check.notes || [] })),
    partial: result.partial, researchStatus: result.researchStatus, researchGaps: result.researchGaps || [],
    demo: result.demo === true
  };
}

export function checklistExportInput(context, result, checked, notes) {
  const ids = new Set(checklistItems(result).map(item => item.id));
  return { analysisId: context.analysisId, contextToken: context.contextToken, routeId: result.routeId,
    checklistId: result.id, snapshot: checklistExportSnapshot(result),
    checkedItemIds: [...checked].filter(id => ids.has(id)),
    itemNotes: Object.fromEntries(Object.entries(notes).filter(([id, note]) => ids.has(id) && note.trim())) };
}

/** Research belongs to a voyage/route session, not the dialog's visibility. */
export function curateChecklist(session, input, fetchChecklist, onUpdate = () => {}) {
  if (session.pending) return session.pending;
  const request = { ...input };
  session.error = null;
  const notify = () => { try { onUpdate(); } catch (error) { console.error('Could not display checklist update:', error); } };
  session.pending = Promise.resolve().then(async () => {
    try {
      const preview = await fetchChecklist({ ...request, research: false });
      if (!session.result) { session.result = preview; notify(); }
      session.result = await fetchChecklist(request);
    } catch (error) {
      session.error = error.message || 'Checklist research is unavailable. Refresh to retry.';
    } finally {
      session.pending = null;
      notify();
    }
    return session.result;
  });
  notify();
  return session.pending;
}
