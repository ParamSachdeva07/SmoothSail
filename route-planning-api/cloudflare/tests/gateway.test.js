import test from 'node:test';
import assert from 'node:assert/strict';
import { handleRequest } from '../src/gateway.js';

const env = { ALLOWED_ORIGINS: '*' };
const request = (path, init = {}) => new Request(`https://tideline.example${path}`, init);
const unavailable = () => { throw new Error('should not reach the container'); };

test('congestion has the same public JSON/CORS contract as routes', async () => {
  const preflight = await handleRequest(request('/api/port-congestion', { method: 'OPTIONS', headers: {
    Origin: 'https://frontend.example', 'Access-Control-Request-Method': 'POST',
    'Access-Control-Request-Headers': 'content-type'
  } }), env, unavailable);
  assert.equal(preflight.status, 204);
  const response = await handleRequest(request('/port-congestion', { method: 'POST',
    body: JSON.stringify({ portIds: ['NLRTM'] }), headers: { 'Content-Type': 'application/json' }
  }), env, async forwarded => {
    assert.equal(new URL(forwarded.url).pathname, '/port-congestion');
    return Response.json({ assessments: [] });
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
});

test('research has no gateway deadline but still forwards caller cancellation', async t => {
  const deadlines = [];
  t.mock.method(AbortSignal, 'timeout', ms => {
    deadlines.push(ms);
    return new AbortController().signal;
  });
  const controller = new AbortController();
  await handleRequest(request('/api/port-congestion', { method: 'POST',
    body: '{"portIds":["NLRTM"]}', headers: { 'Content-Type': 'application/json' },
    signal: controller.signal
  }), env, async forwarded => {
    assert.deepEqual(deadlines, []);
    assert.equal(forwarded.signal.aborted, false);
    controller.abort();
    assert.equal(forwarded.signal.aborted, true);
    return Response.json({ assessments: [] });
  });
  await handleRequest(request('/health'), env, async () => Response.json({ ok: true }));
  assert.deepEqual(deadlines, [180000]);
});

test('JSON preflights work from unrelated origins without starting a container', async () => {
  for (const origin of ['http://localhost:3000', 'https://frontend.example', 'https://preview.example']) {
    const r = await handleRequest(request('/api/routes', { method: 'OPTIONS', headers: {
      Origin: origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type',
    } }), env, unavailable);
    assert.equal(r.status, 204);
    assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
    assert.equal(r.headers.get('Access-Control-Allow-Credentials'), null);
  }
});

test('POST forwards JSON unchanged and strips private/browser headers', async () => {
  const body = JSON.stringify({ origin: 'NLRTM', destination: 'SGSIN' });
  const r = await handleRequest(request('/api/routes', { method: 'POST', body, headers: {
    'Content-Type': 'application/json', Cookie: 'private=value', Authorization: 'Bearer private',
    'X-Tideline-Internal-Token': 'private',
  } }), env, async forwarded => {
    assert.equal(new URL(forwarded.url).pathname, '/routes');
    assert.equal(await forwarded.text(), body);
    for (const h of ['cookie', 'authorization', 'x-tideline-internal-token']) assert.equal(forwarded.headers.get(h), null);
    return Response.json({ routes: [] }, { headers: { 'Server-Timing': 'calculation;dur=120' } });
  });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('Server-Timing'), 'calculation;dur=120');
  assert.match(r.headers.get('Access-Control-Expose-Headers'), /Server-Timing/);
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
});

test('query parameters and backend validation statuses are retained', async () => {
  const r = await handleRequest(request('/ports/nearby?longitude=invalid'), env, async forwarded => {
    assert.equal(new URL(forwarded.url).search, '?longitude=invalid');
    return Response.json({ detail: 'invalid longitude' }, { status: 422 });
  });
  assert.equal(r.status, 422);
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
});

test('private and unknown paths stay inaccessible, including API aliases', async () => {
  for (const path of ['/internal/refresh', '/api/internal/refresh', '/internal/refresh-compliance', '/api/internal/refresh-compliance', '/admin', '/api/api/internal/refresh']) {
    const r = await handleRequest(request(path, { method: 'POST' }), env, unavailable);
    assert.equal(r.status, 404);
    assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  }
});

test('analysis NDJSON streams unchanged with CORS and uploads retain their multipart boundary', async () => {
  const body = '{"routeRequest":{"origin":"NLRTM","destination":"SGSIN"},"cargoText":"cargo"}';
  const stream = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{"type":"started"}\n')); c.close(); } });
  const r = await handleRequest(request('/voyages/analyse', { method: 'POST', body, headers: { 'Content-Type': 'application/json' } }),
    env, async forwarded => {
      assert.equal(await forwarded.text(), body);
      return new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson' } });
    });
  assert.match(r.headers.get('Content-Type'), /ndjson/);
  assert.equal(await r.text(), '{"type":"started"}\n');
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  const form = new FormData(); form.append('file', new Blob(['Cargo']), 'cargo.txt');
  const upload = await handleRequest(request('/documents/extract', { method: 'POST', body: form }), env, async forwarded => {
    assert.match(forwarded.headers.get('Content-Type'), /multipart\/form-data; boundary=/);
    assert.match(await forwarded.text(), /Cargo/);
    return Response.json({ stored: false });
  });
  assert.equal(upload.status, 200);
});

test('CORS also wraps method errors and container failures', async () => {
  const method = await handleRequest(request('/routes'), env, unavailable);
  assert.equal(method.status, 405);
  const failure = await handleRequest(request('/health'), env, unavailable);
  assert.equal(failure.status, 503);
  assert.equal(failure.headers.get('Access-Control-Allow-Origin'), '*');
  assert.equal((await failure.text()).includes('should not reach'), false);
});

test('provisioning responses remain JSON with retry guidance and CORS', async () => {
  const failure = await handleRequest(request('/health'), env,
    async () => new Response('There is no Container instance available at this time.', { status: 503 }));
  assert.equal(failure.status, 503);
  assert.equal(failure.headers.get('Retry-After'), '5');
  assert.equal(failure.headers.get('Access-Control-Allow-Origin'), '*');
  assert.equal((await failure.json()).error.code, 'service_unavailable');
});

test('optional exact origin allowlist rejects other origins and varies cache keys', async () => {
  const settings = { ALLOWED_ORIGINS: 'https://one.example, https://two.example' };
  const denied = await handleRequest(request('/health', { headers: { Origin: 'https://one.example.evil.example' } }), settings, unavailable);
  assert.equal(denied.status, 403);
  assert.equal(denied.headers.get('Access-Control-Allow-Origin'), null);
  const allowed = await handleRequest(request('/health', { headers: { Origin: 'https://two.example' } }), settings, async () => Response.json({ ok: true }));
  assert.equal(allowed.headers.get('Access-Control-Allow-Origin'), 'https://two.example');
  assert.match(allowed.headers.get('Vary'), /Origin/);
});

test('body limit counts UTF-8 bytes even without Content-Length', async () => {
  const r = await handleRequest(request('/routes', { method: 'POST', body: 'é'.repeat(5000), headers: { 'Content-Type': 'application/json' } }), env, unavailable);
  assert.equal(r.status, 413);
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
});

test('unsupported preflight headers and non-JSON inputs are rejected', async () => {
  const preflight = await handleRequest(request('/routes', { method: 'OPTIONS', headers: {
    'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'X-Tideline-Internal-Token',
  } }), env, unavailable);
  assert.equal(preflight.status, 400);
  const post = await handleRequest(request('/routes', { method: 'POST', body: '{}' }), env, unavailable);
  assert.equal(post.status, 415);
});
