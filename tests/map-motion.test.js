import test from 'node:test';
import assert from 'node:assert/strict';
import { wheelZoomDelta, createSmoothZoom } from '../src/globe/smooth-zoom.js';
import { createSeaContours } from '../src/globe/sea-contours.js';

test('wheel units are normalized, pinch is usable, and large inputs are bounded', () => {
  assert.equal(wheelZoomDelta({ deltaY: 16, deltaMode: 0 }, 800), wheelZoomDelta({ deltaY: 1, deltaMode: 1 }, 800));
  assert.equal(wheelZoomDelta({ deltaY: 1, deltaMode: 2 }, 800), -0.4);
  assert.equal(wheelZoomDelta({ deltaY: -10000, deltaMode: 0 }, 800), 0.4);
  assert.equal(wheelZoomDelta({ deltaY: -2, deltaMode: 0, ctrlKey: true }, 800), 0.02);
});

test('zoom accumulates smoothly, reverses immediately, anchors the pointer and respects bounds', () => {
  const listeners = new Map(), handlers = new Map(), calls = [];
  let current = 3, disabled = false, anchor;
  const canvas = { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name),
    getBoundingClientRect: () => ({ left: 10, top: 20, height: 800 }) };
  const map = { getCanvas: () => canvas, scrollZoom: { disable: () => { disabled = true; } },
    getMinZoom: () => 2, getMaxZoom: () => 8, getZoom: () => current,
    on: (name, fn) => handlers.set(name, fn), off: name => handlers.delete(name),
    unproject: point => { anchor = point; return [12, 50]; },
    easeTo: options => { if (calls.length) handlers.get('zoomend')?.(); calls.push(options); } };
  const motion = { matches: false };
  const zoom = createSmoothZoom(map, { reducedMotion: motion });
  assert.equal(disabled, true);
  const wheel = deltaY => listeners.get('wheel')({ deltaY, deltaMode: 0, clientX: 110, clientY: 220, preventDefault() {} });
  wheel(-100); wheel(-100); wheel(-100);
  assert.deepEqual(calls.map(c => c.zoom), [3.25, 3.5, 3.75]);
  assert.deepEqual(anchor, [100, 200]);
  assert.deepEqual(calls[0].around, [12, 50]);
  current = 3.3; wheel(100);
  assert.equal(calls.at(-1).zoom, 3.05);
  zoom.zoomBy(-100); assert.equal(calls.at(-1).zoom, 2);
  zoom.zoomBy(100); assert.equal(calls.at(-1).zoom, 8);
  motion.matches = true; zoom.zoomBy(-1); assert.equal(calls.at(-1).duration, 0);
  zoom.destroy(); assert.equal(listeners.size, 0); assert.equal(handlers.size, 0);
});

test('contour worker coalesces seeks and rejects stale frames without a work backlog', async t => {
  const original = globalThis.Worker;
  const messages = [], output = [];
  let worker;
  globalThis.Worker = class {
    constructor() { worker = this; }
    postMessage(message) { messages.push(message); }
    terminate() { this.terminated = true; }
    reply(message) { this.onmessage({ data: { ...message, features: { type: 'FeatureCollection', features: [] } } }); }
  };
  t.after(() => { if (original === undefined) delete globalThis.Worker; else globalThis.Worker = original; });
  const grid = { columns: 2, rows: 2, bounds: [0, 0, 1, 1], frames: [0, 6, 12].map(hour => ({ hour, values: [4, 5, 6, 7] })) };
  const contours = createSeaContours(grid, data => output.push(data));
  t.after(() => contours.destroy());
  contours.setHour(1); contours.setActive(true);
  const first = messages.at(-1);
  contours.setHour(2, true); contours.setHour(3, true);
  assert.equal(messages.length, 2); // metadata + a single in-flight calculation
  assert.equal(first.frames.length, 2);
  worker.reply(first);
  assert.equal(output.length, 0);
  await new Promise(resolve => setTimeout(resolve, 95));
  assert.equal(messages.length, 3);
  assert.equal(messages.at(-1).hour, 3);
  worker.reply(messages.at(-1));
  assert.equal(output.length, 1);
  contours.setHour(13, true); assert.equal(output.at(-1), null);
  contours.setActive(false); contours.setHour(4);
  assert.equal(messages.length, 3);
  contours.destroy(); assert.equal(worker.terminated, true);
});
