import { DEFAULT_WAVE_RAMP, waveColor } from './waves.js';

// Native-resolution, premultiplied RGBA. Filtering changes only the display;
// numeric sampling still uses the untouched forecast grid.
export function renderWaveFrame(grid, values, ramp = DEFAULT_WAVE_RAMP) {
  const { columns: width, rows: height } = grid;
  const wrap = grid.bounds[2] - grid.bounds[0] >= 359.99;
  const period = wrap ? width - 1 : width;
  const input = new Float32Array(width * height * 4), horizontal = new Float32Array(input.length);
  const pixels = new Uint8Array(input.length);
  for (let y = 0; y < height; y++) for (let x = 0; x < period; x++) {
    const value = values[y * width + x];
    if (!Number.isFinite(value) || value < 0) continue;
    const c = waveColor(value, ramp), i = (y * width + x) * 4, alpha = c[3] / 255;
    input[i] = c[0] * alpha; input[i + 1] = c[1] * alpha; input[i + 2] = c[2] * alpha; input[i + 3] = c[3];
  }
  // A small separable Gaussian softens edges without expanding the image
  // ninefold. GPU linear filtering supplies subpixel scaling while zooming.
  const weights = [0.006, 0.061, 0.242, 0.382, 0.242, 0.061, 0.006];
  for (let y = 0; y < height; y++) for (let x = 0; x < period; x++) {
    const to = (y * width + x) * 4;
    for (let k = -3; k <= 3; k++) {
      const sx = wrap ? (x + k + period) % period : x + k;
      if (sx < 0 || sx >= period) continue;
      const from = (y * width + sx) * 4, weight = weights[k + 3];
      for (let c = 0; c < 4; c++) horizontal[to + c] += input[from + c] * weight;
    }
  }
  for (let y = 0; y < height; y++) for (let x = 0; x < period; x++) {
    const to = (y * width + x) * 4;
    const edge = Math.min(1, y / 2, (height - 1 - y) / 2, wrap ? 1 : x / 2, wrap ? 1 : (width - 1 - x) / 2);
    for (let c = 0; c < 4; c++) {
      let value = 0;
      for (let k = -3; k <= 3; k++) {
        if (y + k >= 0 && y + k < height) value += horizontal[((y + k) * width + x) * 4 + c] * weights[k + 3];
      }
      pixels[to + c] = Math.round(value * edge);
    }
  }
  if (wrap) for (let y = 0; y < height; y++) {
    const start = y * width * 4;
    pixels.set(pixels.subarray(start, start + 4), start + (width - 1) * 4);
  }
  return { width, height, pixels };
}

export function waveQuad(bounds, width, height) {
  const [west, south, east, north] = bounds;
  const mercatorY = lat => (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2;
  const left = (west + 180) / 360, right = (east + 180) / 360, top = mercatorY(north), bottom = mercatorY(south);
  const u0 = 0.5 / width, u1 = 1 - u0, v0 = 0.5 / height, v1 = 1 - v0;
  return new Float32Array([left, top, u0, v0, left, bottom, u0, v1, right, top, u1, v0, right, bottom, u1, v1]);
}
