// Display interpolation only. Unknown samples never become zero-height waves.
const smoothstep = (x) => { const t = Math.max(0, Math.min(1, x)); return t * t * (3 - 2 * t); };
const mercator = (lat) => Math.asinh(Math.tan(lat * Math.PI / 180));
export const DEFAULT_WAVE_RAMP = [
  [0, 126, 176, 191, 70], [1, 105, 170, 180, 95], [2, 151, 186, 168, 120],
  [3, 210, 187, 134, 145], [4, 214, 150, 123, 165], [6, 183, 112, 126, 180]
];
export function validWaveGrid(grid) {
  return grid?.projection === 'mercator' && grid.rowOrder === 'north_to_south' && grid.units === 'm' &&
    grid.columns >= 2 && grid.rows >= 2 && Array.isArray(grid.bounds) && grid.bounds.length === 4 &&
    grid.bounds.every(Number.isFinite) && grid.bounds[0] < grid.bounds[2] && grid.bounds[1] < grid.bounds[3] &&
    Array.isArray(grid.frames) && grid.frames.length > 0 && grid.frames.every((frame, i) =>
      Number.isFinite(frame.hour) && (!i || frame.hour > grid.frames[i - 1].hour) &&
      Array.isArray(frame.values) && frame.values.length === grid.columns * grid.rows);
}
export function framePair(grid, hour) {
  if (!grid || !Number.isFinite(hour)) return null;
  const frames = grid.frames;
  if (hour < frames[0].hour || hour > frames.at(-1).hour) return null;
  const upper = frames.findIndex((frame) => frame.hour >= hour);
  if (frames[upper].hour === hour) return { a: upper, b: upper, mix: 0 };
  return { a: upper - 1, b: upper, mix: (hour - frames[upper - 1].hour) / (frames[upper].hour - frames[upper - 1].hour) };
}
export function bilinear(values, columns, rows, x, y) {
  if (x < 0 || y < 0 || x > columns - 1 || y > rows - 1) return null;
  const left = Math.min(columns - 2, Math.floor(x)), top = Math.min(rows - 2, Math.floor(y));
  const fx = x - left, fy = y - top;
  const indices = [top * columns + left, top * columns + left + 1, (top + 1) * columns + left, (top + 1) * columns + left + 1];
  const weights = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy];
  let value = 0;
  for (let i = 0; i < 4; i++) {
    if (weights[i] <= 1e-10) continue;
    if (!Number.isFinite(values[indices[i]])) return null;
    value += values[indices[i]] * weights[i];
  }
  return value;
}
export function waveAt(grid, hour, [longitude, latitude]) {
  const pair = framePair(grid, hour);
  if (!pair) return null;
  const [w, s, e, n] = grid.bounds;
  if (longitude < w || longitude > e || latitude < s || latitude > n) return null;
  const x = (longitude - w) / (e - w) * (grid.columns - 1);
  const y = (mercator(n) - mercator(latitude)) / (mercator(n) - mercator(s)) * (grid.rows - 1);
  const a = bilinear(grid.frames[pair.a].values, grid.columns, grid.rows, x, y);
  const b = bilinear(grid.frames[pair.b].values, grid.columns, grid.rows, x, y);
  return a === null || b === null ? null : a + (b - a) * pair.mix;
}

// Only supported interpolation cells seed the display raster. The separate
// blur below rounds their coverage boundary without modifying the source grid.
function supportMask(valid, columns, rows) {
  const width = columns - 1, height = rows - 1;
  const quads = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = y * columns + x;
    quads[y * width + x] = valid[i] && valid[i + 1] && valid[i + columns] && valid[i + columns + 1] ? 1 : 0;
  }
  return (x, y) => quads[Math.min(height - 1, Math.floor(y)) * width + Math.min(width - 1, Math.floor(x))];
}
export function waveColor(value, ramp = DEFAULT_WAVE_RAMP) {
  if (!Number.isFinite(value)) return [0, 0, 0, 0];
  let upper = ramp.findIndex((stop) => stop[0] >= value);
  if (upper < 0) upper = ramp.length - 1;
  const b = ramp[upper], a = ramp[Math.max(0, upper - 1)];
  const f = a[0] === b[0] ? 0 : Math.min(1, Math.max(0, (value - a[0]) / (b[0] - a[0])));
  return a.slice(1).map((v, i) => v + (b[i + 1] - v) * f);
}

// Blur premultiplied display colours across coverage edges. Numeric sampling
// remains strict in waveAt(); this small visual halo is clipped by the map's
// independent coastline mask. Three box passes approximate a Gaussian filter.
function softenRaster(tiles, scale, wrap) {
  const width = tiles.reduce((sum, tile) => sum + tile.width - 1, 0) + (wrap ? 0 : 1);
  const height = tiles[0].height, radius = Math.max(1, Math.round(scale * 0.65));
  const size = width * height * 4, divisor = radius * 2 + 1;
  const input = new Float32Array(size), horizontal = new Float32Array(size), output = new Float32Array(size);
  const sx = (x) => wrap ? ((x % width) + width) % width : x;
  for (let frame = 0; frame < 2; frame++) {
    input.fill(0);
    let start = 0;
    for (const tile of tiles) {
      const pixels = tile.pixels[frame];
      for (let y = 0; y < height; y++) for (let x = 0; x < tile.width; x++) {
        const gx = sx(start + x);
        if (gx >= width) continue;
        const from = (y * tile.width + x) * 4, to = (y * width + gx) * 4, alpha = pixels[from + 3];
        input[to] = pixels[from] * alpha / 255;
        input[to + 1] = pixels[from + 1] * alpha / 255;
        input[to + 2] = pixels[from + 2] * alpha / 255;
        input[to + 3] = alpha;
      }
      start += tile.width - 1;
    }
    let source = input;
    for (let pass = 0; pass < 3; pass++) {
      for (let y = 0; y < height; y++) for (let c = 0; c < 4; c++) {
        let sum = 0;
        for (let k = -radius; k <= radius; k++) {
          const x = sx(k);
          if (x >= 0 && x < width) sum += source[(y * width + x) * 4 + c];
        }
        for (let x = 0; x < width; x++) {
          horizontal[(y * width + x) * 4 + c] = sum / divisor;
          const remove = sx(x - radius), add = sx(x + radius + 1);
          if (remove >= 0 && remove < width) sum -= source[(y * width + remove) * 4 + c];
          if (add >= 0 && add < width) sum += source[(y * width + add) * 4 + c];
        }
      }
      for (let x = 0; x < width; x++) for (let c = 0; c < 4; c++) {
        let sum = 0;
        for (let y = 0; y <= Math.min(radius, height - 1); y++) sum += horizontal[(y * width + x) * 4 + c];
        for (let y = 0; y < height; y++) {
          output[(y * width + x) * 4 + c] = Math.max(0, sum / divisor);
          const remove = y - radius, add = y + radius + 1;
          if (remove >= 0) sum -= horizontal[(remove * width + x) * 4 + c];
          if (add < height) sum += horizontal[(add * width + x) * 4 + c];
        }
      }
      source = output;
    }
    start = 0;
    for (const tile of tiles) {
      const pixels = tile.pixels[frame];
      for (let y = 0; y < height; y++) for (let x = 0; x < tile.width; x++) {
        const from = (y * width + sx(start + x)) * 4, to = (y * tile.width + x) * 4, alpha = output[from + 3];
        for (let c = 0; c < 3; c++) pixels[to + c] = alpha >= 0.5 ? output[from + c] * 255 / alpha : 0;
        const gx = sx(start + x);
        const boundary = wrap ? Math.min(y, height - 1 - y) : Math.min(gx, width - 1 - gx, y, height - 1 - y);
        pixels[to + 3] = alpha * smoothstep(boundary / scale);
      }
      start += tile.width - 1;
    }
  }
}
export function renderWavePair(grid, pair, { scale = Math.max(1, Math.min(4, Math.ceil(2160 / grid.columns))), ramp = DEFAULT_WAVE_RAMP } = {}) {
  const a = grid.frames[pair.a].values, b = grid.frames[pair.b].values;
  const valid = a.map((v, i) => Number.isFinite(v) && v >= 0 && Number.isFinite(b[i]) && b[i] >= 0);
  const wrapLongitude = grid.bounds[2] - grid.bounds[0] >= 359.99;
  const support = supportMask(valid, grid.columns, grid.rows);
  const maskedA = a.map((v, i) => valid[i] ? v : NaN), maskedB = b.map((v, i) => valid[i] ? v : NaN);
  const [west, south, east, north] = grid.bounds;
  // Keep each texture quad below 180° to avoid image-source date-line ambiguity.
  const count = Math.max(1, Math.ceil((east - west) / 120));
  const tiles = Array.from({ length: count }, (_, index) => {
    const first = Math.round(index * (grid.columns - 1) / count), last = Math.round((index + 1) * (grid.columns - 1) / count);
    const width = (last - first) * scale + 1, height = (grid.rows - 1) * scale + 1;
    const pixels = [new Uint8ClampedArray(width * height * 4), new Uint8ClampedArray(width * height * 4)];
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const gx = first + x / scale, gy = y / scale;
      const va = bilinear(maskedA, grid.columns, grid.rows, gx, gy);
      if (va === null) continue;
      const boundary = wrapLongitude ? Math.min(gy, grid.rows - 1 - gy) : Math.min(gx, gy, grid.columns - 1 - gx, grid.rows - 1 - gy);
      const edge = support(gx, gy) * smoothstep(boundary / 4);
      if (!edge) continue;
      const vb = bilinear(maskedB, grid.columns, grid.rows, gx, gy);
      for (const [frame, value] of [[0, va], [1, vb]]) {
        const color = waveColor(value, ramp), offset = (y * width + x) * 4;
        pixels[frame].set([color[0], color[1], color[2], color[3] * edge], offset);
      }
    }
    const w = west + (east - west) * first / (grid.columns - 1), e = west + (east - west) * last / (grid.columns - 1);
    return { width, height, pixels, coordinates: [[w, north], [e, north], [e, south], [w, south]] };
  });
  softenRaster(tiles, scale, wrapLongitude);
  return tiles;
}
