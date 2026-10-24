export const API_BASE_URL = (import.meta.env?.VITE_ROUTE_API_BASE_URL ||
  'https://tideline-api.paramsachdeva81.workers.dev').replace(/\/+$/, '');

export function createApiClient(baseUrl = API_BASE_URL, fetcher = globalThis.fetch) {
  async function request(path, { signal, body, timeoutMs = 190_000 } = {}) {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), timeoutMs);
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
      clearTimeout(timer);
    }
  }
  return {
    getPorts: (options = {}) => request('/ports?limit=50', { timeoutMs: 60_000, ...options }),
    planRoutes: (input, options = {}) => request('/routes', { ...options, body: input })
  };
}

export const api = createApiClient();
