import { api } from '../api/client.js';

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
export function createAnalysisPlanner(analyse) {
  const states = new WeakMap();
  let active = null;
  return {
    calculate(input, { signal, cargoText = '', documentReferences = [] } = {}) {
      signal?.throwIfAborted();
      active?.abort();
      const controller = new AbortController(); active = controller;
      const state = { report: null, cargoText, documentReferences, findings: [], checks: {}, congestion: [],
        complete: false, listeners: new Set(), error: null };
      const publish = () => state.listeners.forEach(listener => listener(state));
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
            if (event.type === 'assessment') {
              state.checks[event.category] = event;
              state.findings = Object.values(state.checks).flatMap(check => check.findings ?? []);
              if (event.category === 'congestion') state.congestion = event.assessments ?? [];
            }
            if (event.type === 'context_ready') state.context = event;
            if (event.type === 'complete') state.complete = true;
            if (event.type === 'error') {
              state.error = event.message; state.complete = true;
              if (!state.report) reject(new Error(event.message));
            }
            publish();
          }
        }).then(() => {
          if (!state.complete) { state.complete = true; state.error = 'The analysis stream ended before every check completed.'; publish(); }
          if (!state.report) reject(new Error(state.error || 'No route report was returned.'));
        }).catch(error => {
          state.error = controller.signal.aborted ? 'Analysis cancelled.' : error.message;
          state.complete = true; publish();
          if (!state.report) reject(error);
        }).finally(() => signal?.removeEventListener('abort', abort));
      });
    },
    getState: report => states.get(report),
    subscribe(report, listener) {
      const state = states.get(report);
      if (!state) return () => {};
      state.listeners.add(listener); listener(state);
      return () => state.listeners.delete(listener);
    },
    getCongestion: report => Promise.resolve(states.get(report)?.congestion ?? [])
  };
}

export const routePlanner = createAnalysisPlanner((input, options) => api.analyseVoyage(input, options));
