import test from 'node:test';
import assert from 'node:assert/strict';
import { createWaveFrameCache } from '../src/globe/wave-cache.js';

function fixture() {
  const frames = new Map(), requests = [], states = [];
  const grid = { frames: Array.from({ length: 40 }, (_, i) => ({ values: [i] })) };
  const worker = { postMessage: message => requests.push(message), terminate() { this.terminated = true; } };
  const layer = { has: i => frames.has(i), put: (i, data) => frames.set(i, data), trim: keep => {
    for (const i of frames.keys()) if (!keep.has(i)) frames.delete(i);
  } };
  const cache = createWaveFrameCache(grid, { worker, layer, onReady: () => states.push(cache.ready()), onError: () => states.push('error') });
  const finish = () => worker.onmessage({ data: { index: requests.at(-1).index, pixels: new Uint8Array(4) } });
  return { cache, worker, requests, states, frames, finish };
}

test('wave frames are reused across forecast boundaries and prepared ahead of playback', () => {
  const f = fixture();
  f.cache.update({ a: 0, b: 0, mix: 0 }, true); f.finish();
  assert.equal(f.cache.ready(), true);
  assert.equal(f.requests.at(-1).index, 1);
  f.finish(); f.finish();
  const count = f.requests.length;
  for (let i = 0; i < 60; i++) f.cache.update({ a: 0, b: 1, mix: i / 60 }, true);
  assert.equal(f.cache.ready(), true);
  assert.equal(f.requests.filter(r => r.index === 0).length, 1);
  assert.equal(f.requests.filter(r => r.index === 1).length, 1);
  assert.ok(f.requests.length <= count + 1);
  f.finish();
  f.cache.update({ a: 1, b: 1, mix: 0 }, true);
  assert.equal(f.cache.ready(), true);
  f.cache.update({ a: 1, b: 2, mix: 0.1 }, true);
  assert.equal(f.cache.ready(), true, 'exact frame boundaries must not hide a prepared texture');
  assert.ok(f.frames.size <= 5);
  f.cache.destroy(); assert.equal(f.worker.terminated, true);
});

test('rapid seeks skip old work, and hidden layers stop requesting textures', () => {
  const f = fixture();
  f.cache.update({ a: 0, b: 1, mix: 0.5 }, true);
  f.cache.update({ a: 10, b: 11, mix: 0.5 }, true);
  f.cache.update({ a: 30, b: 31, mix: 0.5 }, true);
  assert.equal(f.requests.length, 1);
  f.finish();
  assert.equal(f.requests.at(-1).index, 30);
  assert.equal(f.frames.has(0), false);
  f.finish(); f.finish();
  assert.equal(f.cache.ready(), true);
  f.cache.update({ a: 30, b: 31, mix: 0.5 }, false);
  const count = f.requests.length;
  f.finish(); assert.equal(f.requests.length, count);
  f.cache.update(null, true); assert.equal(f.cache.ready(), false);
  assert.equal(f.frames.size, 0);
});
