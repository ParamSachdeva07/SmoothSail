import test from 'node:test';
import assert from 'node:assert/strict';
import { createWaveGpuLayer } from '../src/globe/wave-gpu.js';

test('GPU playback reuses textures, hides correctly, and recovers from context loss', () => {
  const handlers = new Map();
  let uploads = 0, draws = 0, deleted = 0, repaints = 0;
  const gl = {
    createShader: () => ({}), shaderSource() {}, compileShader() {}, getShaderParameter: () => true, deleteShader() {},
    createProgram: () => ({}), attachShader() {}, linkProgram() {}, getProgramParameter: () => true, getUniformLocation: () => ({}),
    getParameter: () => null, createVertexArray: () => ({}), bindVertexArray() {}, createBuffer: () => ({}), bindBuffer() {}, bufferData() {},
    getAttribLocation: () => 0, enableVertexAttribArray() {}, vertexAttribPointer() {}, createTexture: () => ({}), bindTexture() {},
    texParameteri() {}, pixelStorei() {}, texImage2D() { uploads++; }, useProgram() {}, uniformMatrix4fv() {}, activeTexture() {},
    uniform1i() {}, uniform1f() {}, drawArrays() { draws++; }, deleteTexture() { deleted++; }, deleteBuffer() {}, deleteVertexArray() {}, deleteProgram() {}
  };
  const map = { getBounds: () => ({ getWest: () => -90, getEast: () => 90 }), on: (name, fn) => handlers.set(name, fn), off: name => handlers.delete(name), triggerRepaint: () => repaints++ };
  const layer = createWaveGpuLayer({ bounds: [-180, -60, 180, 60], columns: 2, rows: 2 });
  layer.onAdd(map, gl);
  for (const index of [0, 1, 2]) layer.put(index, { width: 2, height: 2, pixels: new Uint8Array(16) });
  for (let i = 0; i < 60; i++) { layer.show({ a: 0, b: 1, mix: i / 60 }, true); layer.render(gl, []); }
  assert.equal(uploads, 2, '60 animation frames must not cause 60 texture uploads');
  assert.equal(draws, 60);
  layer.show({ a: 1, b: 2, mix: 0.2 }, true); layer.render(gl, []);
  assert.equal(uploads, 3, 'reuse the shared forecast frame at interval boundaries');
  layer.show({ a: 1, b: 2, mix: 0.2 }, false); layer.render(gl, []); assert.equal(draws, 61);
  layer.show({ a: 2, b: 2, mix: 0 }, true); layer.render(gl, []);
  const idle = repaints;
  layer.show({ a: 2, b: 2, mix: 0 }, true); assert.equal(repaints, idle);
  layer.trim(new Set([2])); assert.equal(deleted, 2);
  handlers.get('webglcontextlost')(); layer.render(gl, []); assert.equal(draws, 62);
  handlers.get('webglcontextrestored')(); layer.render(gl, []); assert.equal(uploads, 4);
  layer.onRemove(); assert.equal(deleted, 3); assert.equal(handlers.size, 0);
});
