export const API_BASE_URL = (import.meta.env?.VITE_ROUTE_API_BASE_URL ||
  'https://tideline-api.paramsachdeva81.workers.dev').replace(/\/+$/, '');

export function createApiClient(baseUrl = API_BASE_URL, fetcher = globalThis.fetch) {
  async function request(path, { signal, body, timeoutMs = 190_000 } = {}) {
    const timeout = new AbortController();
    const timer = timeoutMs == null ? null : setTimeout(() => timeout.abort(), timeoutMs);
    const combined = signal ? AbortSignal.any([signal, timeout.signal]) : timeout.signal;
    try {
      const response = await fetcher(`${baseUrl.replace(/\/+$/, '')}${path}`, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        credentials: 'omit',
        signal: combined,
        ...(body ? { body: JSON.stringify(body) } : {})
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const message = payload?.error?.message ||
          (typeof payload?.detail === 'string' ? payload.detail : null);
        throw new Error(message || (response.status === 503
          ? 'The routing service is starting. Please try again in a moment.'
          : `The routing service could not complete this request (${response.status}). Please try again.`));
      }
      if (!payload) throw new Error('The routing service returned an unreadable response. Please try again.');
      return payload;
    } catch (error) {
      if (signal?.aborted) throw new DOMException('Search cancelled', 'AbortError');
      if (timeout.signal.aborted) throw new Error('The routing request timed out. Please try again.');
      if (error instanceof TypeError) throw new Error('Could not reach the routing service. Check your connection and try again.');
      throw error;
    } finally {
      if (timer != null) clearTimeout(timer);
    }
  }
  const client = {
    getPorts: (options = {}) => request('/ports?limit=50', { timeoutMs: 60_000, ...options }),
    planRoutes: (input, options = {}) => request('/routes', { ...options, body: input }),
    previewReroute: (input, options = {}) => request('/routes/reroute', { ...options, body: input }),
    getPortCongestion: (portIds, options = {}) => request('/port-congestion', {
      timeoutMs: null, ...options, body: { portIds }
    }),
    async analyseVoyage(input, { signal, onEvent, path = '/voyages/analyse' } = {}) {
      const response = await fetcher(`${baseUrl.replace(/\/+$/, '')}${path}`, {
        method: 'POST', credentials: 'omit', signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input)
      });
      if (!response.ok || !response.body) throw new Error('Voyage analysis is unavailable. Please try again.');
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let fragments = [];
      try {
        while (true) {
          const { value, done } = await reader.read();
          // Split only NEW bytes. Re-scanning a 45 MB partial line per chunk is quadratic.
          const lines = decoder.decode(value, { stream: !done }).split('\n');
          if (lines.length === 1) fragments.push(lines[0]);
          else {
            const first = fragments.join('') + lines.shift(); fragments = [];
            if (first.trim()) onEvent?.(JSON.parse(first));
            const tail = lines.pop();
            for (const line of lines) if (line.trim()) onEvent?.(JSON.parse(line));
            if (tail) fragments.push(tail);
          }
          if (done && fragments.length) {
            const tail = fragments.join('');
            if (tail.trim()) onEvent?.(JSON.parse(tail));
          }
          if (done) break;
        }
      } finally { reader.releaseLock(); }
    },
    async extractDocument(file, { signal } = {}) {
      const body = new FormData(); body.append('file', file);
      const response = await fetcher(`${baseUrl.replace(/\/+$/, '')}/documents/extract`, {
        method: 'POST', credentials: 'omit', body, signal
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'Could not read this document.');
      return result;
    },
    researchDetails: (input, options = {}) => client.analyseVoyage(input, { ...options, path: '/voyages/details' }),
    createVoyageChecklist: (body, options = {}) => request('/voyages/checklist', { timeoutMs: null, ...options, body }),
    async exportVoyageChecklist(body, { signal, format = 'pdf' } = {}) {
      const bundle = format === 'bundle';
      const response = await fetcher(`${baseUrl.replace(/\/+$/, '')}/voyages/checklist/${bundle ? 'bundle' : 'pdf'}`, {
        method: 'POST', credentials: 'omit', signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(result?.error?.message || 'Could not export the checklist. Please try again.');
      }
      const type = bundle ? 'application/zip' : 'application/pdf';
      if (!response.headers.get('content-type')?.includes(type)) throw new Error(`The export did not return a ${bundle ? 'ZIP package' : 'PDF'}.`);
      return response.blob();
    },
    complianceChat: (body, options = {}) => request('/compliance/chat', { timeoutMs: null, ...options, body })
  };
  return client;
}

export const api = createApiClient();
