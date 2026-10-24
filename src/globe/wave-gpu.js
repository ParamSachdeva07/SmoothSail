import { waveQuad } from './wave-texture.js';

const vertex = `#version 300 es
in vec2 a_position;
in vec2 a_uv;
uniform mat4 u_matrix;
out vec2 v_uv;
void main() { v_uv = a_uv; gl_Position = u_matrix * vec4(a_position, 0.0, 1.0); }`;
const fragment = `#version 300 es
precision highp float;
uniform sampler2D u_a;
uniform sampler2D u_b;
uniform float u_mix;
in vec2 v_uv;
out vec4 color;
void main() {
  vec4 a = texture(u_a, v_uv), b = texture(u_b, v_uv);
  if (u_mix > 0.0 && u_mix < 1.0 && min(a.a, b.a) < 0.001) discard;
  color = mix(a, b, u_mix);
}`;

export function createWaveGpuLayer(grid, onError = () => {}) {
  let map, gl, program, buffer, vao, uniforms, pair = null, shown = false, lost = false;
  const frames = new Map(), textures = new Map();
  function compile(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { gl.deleteShader(shader); throw new Error('Wave shader compilation failed'); }
    return shader;
  }
  function initialize() {
    const vs = compile(gl.VERTEX_SHADER, vertex), fs = compile(gl.FRAGMENT_SHADER, fragment);
    program = gl.createProgram(); gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
    gl.deleteShader(vs); gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Wave shader linking failed');
    uniforms = Object.fromEntries(['u_matrix', 'u_a', 'u_b', 'u_mix'].map(name => [name, gl.getUniformLocation(program, name)]));
    const previousVao = gl.getParameter(gl.VERTEX_ARRAY_BINDING), previousBuffer = gl.getParameter(gl.ARRAY_BUFFER_BINDING);
    vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, waveQuad(grid.bounds, grid.columns, grid.rows), gl.STATIC_DRAW);
    for (const [name, offset] of [['a_position', 0], ['a_uv', 8]]) {
      const location = gl.getAttribLocation(program, name);
      gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 16, offset);
    }
    gl.bindVertexArray(previousVao); gl.bindBuffer(gl.ARRAY_BUFFER, previousBuffer);
  }
  function texture(index) {
    if (textures.has(index)) return textures.get(index);
    const frame = frames.get(index), t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, frame.width, frame.height, 0, gl.RGBA, gl.UNSIGNED_BYTE, frame.pixels);
    textures.set(index, t);
    return t;
  }
  const contextLost = () => { lost = true; textures.clear(); };
  const contextRestored = () => {
    try { initialize(); lost = false; map.triggerRepaint(); } catch { onError(); }
  };
  return {
    id: 'voyage-waves', type: 'custom', renderingMode: '2d',
    onAdd(nextMap, context) {
      map = nextMap; gl = context;
      try { initialize(); } catch { lost = true; onError(); }
      map.on('webglcontextlost', contextLost); map.on('webglcontextrestored', contextRestored);
    },
    put(index, frame) { frames.set(index, frame); },
    has(index) { return frames.has(index); },
    trim(keep) {
      for (const index of frames.keys()) if (!keep.has(index)) {
        frames.delete(index);
        if (textures.has(index) && !lost) gl.deleteTexture(textures.get(index));
        textures.delete(index);
      }
    },
    show(nextPair, visible) {
      const changed = shown !== visible || pair?.a !== nextPair?.a || pair?.b !== nextPair?.b || pair?.mix !== nextPair?.mix;
      pair = nextPair; shown = visible;
      if (changed) map?.triggerRepaint();
    },
    render(context, matrix) {
      if (!shown || !pair || lost || !frames.has(pair.a) || !frames.has(pair.b)) return;
      const previousVao = gl.getParameter(gl.VERTEX_ARRAY_BINDING);
      gl.useProgram(program); gl.bindVertexArray(vao);
      gl.uniformMatrix4fv(uniforms.u_matrix, false, matrix);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texture(pair.a));
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texture(pair.b));
      gl.uniform1i(uniforms.u_a, 0); gl.uniform1i(uniforms.u_b, 1); gl.uniform1f(uniforms.u_mix, pair.mix);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.bindVertexArray(previousVao);
    },
    onRemove() {
      map.off('webglcontextlost', contextLost); map.off('webglcontextrestored', contextRestored);
      if (!lost) { textures.forEach(t => gl.deleteTexture(t)); gl.deleteBuffer(buffer); gl.deleteVertexArray(vao); gl.deleteProgram(program); }
      frames.clear(); textures.clear();
    }
  };
}
