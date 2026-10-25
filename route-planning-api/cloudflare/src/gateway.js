const READ_PATHS = new Set(['/health', '/ports', '/ports/nearby', '/data-status', '/compliance/data-status', '/route-schema', '/docs', '/openapi.json']);
const POST_PATHS = new Set(['/routes', '/routes/reroute', '/port-congestion', '/voyages/analyse', '/voyages/details', '/documents/extract', '/compliance/chat', '/voyages/checklist', '/voyages/checklist/pdf', '/voyages/checklist/bundle']);
const MAX_BODY_BYTES = 8192;

function error(code, message, status) {
  return Response.json({ error: { code, message } }, { status });
}

function serviceUnavailable() {
  const response = error('service_unavailable', 'The routing container is starting or unavailable. Try again shortly.', 503);
  response.headers.set('Retry-After', '5');
  return response;
}

function cors(response, origin, allowedOrigins) {
  const headers = new Headers(response.headers);
  headers.set('Cache-Control', 'no-store');
  headers.delete('Access-Control-Allow-Credentials');
  headers.delete('Access-Control-Allow-Origin');
  if (allowedOrigins === '*') headers.set('Access-Control-Allow-Origin', '*');
  else {
    headers.append('Vary', 'Origin');
    if (origin && allowedOrigins.split(',').map(x => x.trim()).includes(origin)) {
      headers.set('Access-Control-Allow-Origin', origin);
    }
  }
  headers.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  headers.set('Access-Control-Allow-Headers', 'Content-Type');
  headers.set('Access-Control-Expose-Headers', 'Server-Timing, Retry-After, Content-Disposition');
  headers.set('Access-Control-Max-Age', '86400');
  return new Response(response.body, { status: response.status, headers });
}

async function limitedBody(request, limit = MAX_BODY_BYTES) {
  if (Number(request.headers.get('content-length')) > limit) return null;
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks = [];
  let length = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
  return body;
}

export async function handleRequest(request, env, forward) {
  const origin = request.headers.get('Origin');
  const allowedOrigins = env.ALLOWED_ORIGINS || '*';
  const finish = response => cors(response, origin, allowedOrigins);
  if (origin && allowedOrigins !== '*' && !allowedOrigins.split(',').map(x => x.trim()).includes(origin)) {
    return finish(error('origin_not_allowed', 'This frontend origin is not allowed.', 403));
  }
  const url = new URL(request.url);
  if (url.pathname.startsWith('/api/')) url.pathname = url.pathname.slice(4);
  const download = /^\/compliance\/documents\/[0-9a-f]{24}\/download$/.test(url.pathname);
  const method = POST_PATHS.has(url.pathname) ? 'POST' : READ_PATHS.has(url.pathname) || download ? 'GET' : null;
  if (!method) return finish(error('not_found', 'Use /docs to see the route API.', 404));
  if (request.method === 'OPTIONS') {
    const requested = request.headers.get('Access-Control-Request-Method');
    const headers = (request.headers.get('Access-Control-Request-Headers') || '').toLowerCase().split(',').map(x => x.trim()).filter(Boolean);
    if ((requested && requested !== method) || headers.some(x => x !== 'content-type')) {
      return finish(error('preflight_not_allowed', 'This method or header is not supported.', 400));
    }
    return finish(new Response(null, { status: 204 }));
  }
  if (request.method !== method) return finish(error('method_not_allowed', `Use ${method} for this endpoint.`, 405));
  try {
    let body;
    const contentType = request.headers.get('content-type') || '';
    if (method === 'POST') {
      const upload = url.pathname === '/documents/extract';
      if (upload ? !contentType.toLowerCase().startsWith('multipart/form-data;') : contentType.split(';')[0].trim().toLowerCase() !== 'application/json') {
        return finish(error('unsupported_media_type', upload ? 'Send multipart/form-data.' : 'Send application/json.', 415));
      }
      const limit = upload ? 11 * 1024 * 1024 : url.pathname === '/compliance/chat' ? 16 * 1024 * 1024
        : ['/voyages/analyse', '/voyages/details'].includes(url.pathname) ? 2 * 1024 * 1024 : ['/voyages/checklist/pdf', '/voyages/checklist/bundle'].includes(url.pathname) ? 2 * 1024 * 1024 : MAX_BODY_BYTES;
      body = await limitedBody(request, limit);
      if (body === null) return finish(error('request_too_large', 'Input exceeds this endpoint’s size limit.', 413));
    }
    // The upstream target is a bound container, never a caller-controlled URL.
    // Do not forward cookies, authorization or internal refresh headers.
    const response = await forward(new Request(url, {
      method, body,
      headers: { Accept: download ? 'application/octet-stream' : ['/voyages/analyse', '/voyages/details'].includes(url.pathname) ? 'application/x-ndjson' : 'application/json', ...(method === 'POST' ? { 'Content-Type': contentType } : {}) },
      signal: ['/port-congestion', '/voyages/analyse', '/voyages/details', '/compliance/chat', '/voyages/checklist'].includes(url.pathname) ? request.signal
        : AbortSignal.any([request.signal, AbortSignal.timeout(180000)]),
    }));
    // The Containers SDK can return a plain-text 503 while provisioning.
    // Keep failures parseable by frontends that consume the JSON API.
    if (response.status >= 500 && !response.headers.get('content-type')?.includes('application/json')) {
      await response.body?.cancel();
      return finish(serviceUnavailable());
    }
    return finish(response);
  } catch {
    return finish(serviceUnavailable());
  }
}
