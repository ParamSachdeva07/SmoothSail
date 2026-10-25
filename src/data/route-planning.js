import { api } from '../api/client.js';

function notifyResearch(state) {
  for (const listener of state.listeners) {
    try { listener(state); }
    catch (error) {
      // A view error must not terminate the independent research stream.
      console.error('Could not render voyage research update:', error);
    }
  }
}

// Research belongs to the submitted journey. Opening the map only consumes it.
export function createRoutePlanner(planRoutes, researchPorts) {
  const researchByReport = new WeakMap();

  return {
    async calculate(input, { signal } = {}) {
      signal?.throwIfAborted();
      const ports = [input.origin, input.destination];
      const research = Promise.resolve().then(() => researchPorts(ports)).catch(() => []);
      const report = await planRoutes(input, { signal });
      signal?.throwIfAborted();
      researchByReport.set(report, research);
      return report;
    },
    getCongestion(report) {
      return researchByReport.get(report) ?? Promise.resolve([]);
    }
  };
}

/** The stream outlives search-screen navigation; a new journey cancels the old one. */
export function createAnalysisPlanner(analyse, researchDetails) {
  const states = new WeakMap();
  let active = null;
  let detailController = null;
  return {
    calculate(input, { signal, cargoText = '', documentReferences = [] } = {}) {
      signal?.throwIfAborted();
      active?.abort(); detailController?.abort();
      const controller = new AbortController(); active = controller;
      const state = { report: null, routeInput: structuredClone(input), cargoText, documentReferences, findings: [], checks: {}, congestion: [],
        complete: false, listeners: new Set(), error: null, detailsVersion: 0, detailsPending: false };
      state.contextReady = new Promise(resolve => { state.resolveContext = resolve; });
      const publish = () => notifyResearch(state);
      return new Promise((resolve, reject) => {
        const abort = () => controller.abort();
        signal?.addEventListener('abort', abort, { once: true });
        analyse({ routeRequest: input, cargoText, documentReferences }, { signal: controller.signal,
          onEvent(event) {
            if (controller.signal.aborted) return;
            if (event.type === 'route_report') {
              state.report = event.report; states.set(event.report, state);
              signal?.removeEventListener('abort', abort);
              resolve(event.report);
            }
            if (event.type === 'assessment' && (!state.detailsVersion || event.category === 'congestion')) {
              state.checks[event.category] = event;
              state.findings = Object.values(state.checks).flatMap(check => check.findings ?? []);
              if (event.category === 'congestion') state.congestion = event.assessments ?? [];
            }
            if (event.type === 'context_ready') { state.context = event; state.resolveContext(event); }
            if (event.type === 'complete' && !state.detailsPending) state.complete = true;
            if (event.type === 'error') {
              state.error = event.message; state.complete = true;
              if (!state.report) reject(new Error(event.message));
            }
            publish();
          }
        }).then(() => {
          if (!state.complete && !state.detailsPending) { state.complete = true; state.error = 'The analysis stream ended before every check completed.'; publish(); }
          if (!state.report) reject(new Error(state.error || 'No route report was returned.'));
        }).catch(error => {
          state.error = controller.signal.aborted ? 'Analysis cancelled.' : error.message;
          state.complete = true; publish();
          if (!state.report) reject(error);
        }).finally(() => { signal?.removeEventListener('abort', abort); if (!state.context) state.resolveContext(null); });
      });
    },
    async researchDetails(report, { cargoText = '', documentReferences = [], imoNumber = '' } = {}) {
      const state = states.get(report);
      if (!state || !researchDetails || (!state.detailsKey && !cargoText.trim() && !imoNumber && !documentReferences.length)) return;
      const key = JSON.stringify({ cargoText, documentReferences, imoNumber });
      if (state.detailsKey === key) return;
      const context = state.context ?? await state.contextReady;
      if (!context) throw new Error('Voyage research context is unavailable. Calculate routes again.');
      if (active?.signal.aborted) throw new Error('This voyage has been replaced. Calculate routes again.');
      detailController?.abort();
      const controller = new AbortController(); detailController = controller;
      state.detailsVersion++; const version = state.detailsVersion;
      state.cargoText = cargoText; state.documentReferences = documentReferences;
      state.detailsPending = true; state.complete = false; state.error = null;
      for (const category of ['security', 'environment', 'trade', 'sanctions', 'dangerous_goods']) delete state.checks[category];
      const publish = () => {
        state.findings = Object.values(state.checks).flatMap(check => check.findings ?? []);
        notifyResearch(state);
      };
      publish();
      return new Promise((resolve, reject) => {
        researchDetails({ analysisId: context.analysisId, contextToken: context.contextToken, cargoText, documentReferences,
          vessel: imoNumber ? { imoNumber } : null }, { signal: controller.signal, onEvent(event) {
            if (controller.signal.aborted || version !== state.detailsVersion) return;
            if (event.type === 'context_ready') { state.context = event; state.detailsKey = key; resolve(); }
            if (event.type === 'assessment') state.checks[event.category] = event;
            if (event.type === 'complete') { state.detailsPending = false; state.complete = true; }
            if (event.type === 'error') { state.error = event.message; reject(new Error(event.message)); }
            publish();
          }
        }).then(() => {
          if (version !== state.detailsVersion) return;
          state.detailsPending = false; state.complete = true; publish(); resolve();
        }).catch(error => {
          if (version !== state.detailsVersion) return;
          state.detailsPending = false; state.complete = true; state.error = error.message; publish(); reject(error);
        });
      });
    },
    getState: report => states.get(report),
    subscribe(report, listener) {
      const state = states.get(report);
      if (!state) return () => {};
      state.listeners.add(listener); notifyResearch({ ...state, listeners: new Set([listener]) });
      return () => state.listeners.delete(listener);
    },
    getCongestion: report => Promise.resolve(states.get(report)?.congestion ?? [])
  };
}

export const routePlanner = createAnalysisPlanner((input, options) => api.analyseVoyage(input, options), (input, options) => api.researchDetails(input, options));
