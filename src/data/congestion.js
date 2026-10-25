import { api } from '../api/client.js';

// A level alone cannot create an alert: it must be current and supported by evidence.
export function issueLevel(assessment, now = Date.now()) {
  if (assessment?.demo) return assessment.display?.showBadge && ['mild', 'high'].includes(assessment.level)
    ? assessment.level : null;
  if (!['mild', 'high'].includes(assessment?.level) || !assessment?.display?.showBadge ||
      assessment.researchStatus !== 'completed' || !assessment.sources?.length ||
      !Number.isFinite(Date.parse(assessment.evidenceAsOf)) ||
      Date.parse(assessment.evidenceAsOf) > now ||
      now - Date.parse(assessment.evidenceAsOf) > Math.min(168, assessment.evidenceWindowHours || 72) * 3600_000 ||
      !(Date.parse(assessment.refreshAfter) > now)) return null;
  return assessment.level;
}

export function createCongestionLookup(fetcher, clock = Date.now) {
  const cache = new Map(), pending = new Map();
  return async (portIds) => {
    const ids = [...new Set(portIds)];
    if (!ids.length || ids.length > 2 || ids.some(id => !/^[A-Z]{2}[A-Z0-9]{3}$/.test(id))) return [];
    const key = ids.join(':');
    if (cache.get(key)?.until > clock()) return cache.get(key).assessments;
    if (!pending.has(key)) {
      const task = Promise.resolve().then(() => fetcher(ids)).then(({ assessments }) => {
        const valid = (assessments ?? []).filter(a => ids.includes(a.portId));
        cache.set(key, { assessments: valid, until: Math.min(clock() + 30 * 60_000,
          ...valid.map(a => Date.parse(a.refreshAfter) || clock()), valid.length === ids.length ? Infinity : clock()) });
        while (cache.size > 100) cache.delete(cache.keys().next().value);
        return valid;
      }).catch(() => {
        // A deployment without this endpoint, network failure, or timeout never creates an alert.
        const until = clock() + 60_000;
        const unavailable = ids.map(portId => ({ portId, level: 'unknown', researchStatus: 'unavailable',
          refreshAfter: new Date(until).toISOString(), sources: [], display: { showBadge: false } }));
        cache.set(key, { assessments: unavailable, until });
        return unavailable;
      }).finally(() => pending.delete(key));
      pending.set(key, task);
    }
    return pending.get(key);
  };
}

export const getPortCongestion = createCongestionLookup(ids => api.getPortCongestion(ids));
