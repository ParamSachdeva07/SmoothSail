import test from 'node:test';
import assert from 'node:assert/strict';
import { evidenceTarget } from '../src/data/evidence.js';

const path = '/compliance/documents/0123456789abcdef01234567/download';
test('Mongo references download the original through the configured API, ahead of the publisher link', () => {
  const source = { downloadPath: path, url: 'https://publisher.example/rules', authority: 'official' };
  assert.deepEqual(evidenceTarget(source, '/local-api/'), { href: `/local-api${path}`, download: true });
  assert.deepEqual(evidenceTarget(source, 'https://api.example/api'), { href: `https://api.example/api${path}`, download: true });
});

test('web citations stay links; uploads and arbitrary download paths cannot masquerade as stored originals', () => {
  const url = 'https://publisher.example/rules';
  assert.deepEqual(evidenceTarget({ url }), { href: url, download: false });
  assert.equal(evidenceTarget({ authority: 'user_document', documentId: 'upload1', downloadPath: path }), null);
  for (const downloadPath of ['https://evil.example/file', '//evil.example/file', '/internal/refresh', path + '?url=evil']) {
    assert.deepEqual(evidenceTarget({ url, downloadPath }), { href: url, download: false });
  }
  assert.equal(evidenceTarget({ url: 'javascript:alert(1)' }), null);
});
