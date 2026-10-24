import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SETTINGS } from '../src/settings.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_PATH = resolve(ROOT, 'assets/natural-earth-land.geojson');
const SOURCE_URL = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson';
const OUTPUT_DIR = resolve(ROOT, 'public/data');

const MASK_RESOLUTION = 0.05;
const MASK_COLUMNS = Math.round(360 / MASK_RESOLUTION);
const MASK_ROWS = Math.round(180 / MASK_RESOLUTION);
const MASK_PATH = resolve(ROOT, 'assets/land-mask-0.05deg.bin');

async function getSource() {
  try {
    return await readFile(SOURCE_PATH, 'utf8');
  } catch {
    console.log('Downloading Natural Earth 1:10m land geometry…');
    const response = await fetch(SOURCE_URL);
    if (!response.ok) throw new Error(`Natural Earth download failed: HTTP ${response.status}`);
    const source = await response.text();
    await writeFile(SOURCE_PATH, source);
    return source;
  }
}

function getRings(geojson) {
  const rings = [];
  for (const feature of geojson.features ?? []) {
    const geometry = feature.geometry;
    if (!geometry) continue;
    const list = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
    for (const polygon of list) {
      for (const ring of polygon) {
        if (ring?.length > 2) rings.push(ring);
      }
    }
  }
  return rings;
}

async function readOrBuildMask(rings) {
  try {
    const mask = await readFile(MASK_PATH);
    if (mask.length === MASK_COLUMNS * MASK_ROWS) return mask;
  } catch {
    // Build the mask from the source polygon rings on first run.
  }

  console.log(`Rasterizing land rings at ${MASK_RESOLUTION}°…`);
  const scanlines = Array.from({ length: MASK_ROWS }, () => []);
  for (const ring of rings) {
    for (let index = 0; index < ring.length - 1; index += 1) {
      const [x1, y1] = ring[index];
      const [x2, y2] = ring[index + 1];
      if (y1 === y2) continue;
      const first = Math.max(0, Math.ceil((Math.min(y1, y2) + 90) / MASK_RESOLUTION - 0.5));
      const afterLast = Math.min(MASK_ROWS, Math.ceil((Math.max(y1, y2) + 90) / MASK_RESOLUTION - 0.5));
      const edge = { x1, y1, x2, y2 };
      for (let row = first; row < afterLast; row += 1) scanlines[row].push(edge);
    }
  }

  const mask = Buffer.alloc(MASK_COLUMNS * MASK_ROWS);
  for (let row = 0; row < MASK_ROWS; row += 1) {
    const latitude = -90 + (row + 0.5) * MASK_RESOLUTION;
    const crossings = [];
    for (const edge of scanlines[row]) {
      if ((edge.y1 <= latitude && latitude < edge.y2) || (edge.y2 <= latitude && latitude < edge.y1)) {
        crossings.push(edge.x1 + ((latitude - edge.y1) / (edge.y2 - edge.y1)) * (edge.x2 - edge.x1));
      }
    }
    crossings.sort((a, b) => a - b);
    for (let index = 0; index + 1 < crossings.length; index += 2) {
      const first = Math.max(0, Math.ceil((crossings[index] + 180) / MASK_RESOLUTION - 0.5));
      const afterLast = Math.min(MASK_COLUMNS, Math.ceil((crossings[index + 1] + 180) / MASK_RESOLUTION - 0.5));
      mask.fill(1, row * MASK_COLUMNS + first, row * MASK_COLUMNS + afterLast);
    }
  }
  await writeFile(MASK_PATH, mask);
  console.log(`Cached binary land mask (${(mask.length / 1024 / 1024).toFixed(1)} MiB).`);
  return mask;
}

function isLand(mask, lon, lat) {
  const column = Math.max(0, Math.min(MASK_COLUMNS - 1, Math.floor((lon + 180) / MASK_RESOLUTION)));
  const row = Math.max(0, Math.min(MASK_ROWS - 1, Math.floor((lat + 90) / MASK_RESOLUTION)));
  return mask[row * MASK_COLUMNS + column] !== 0;
}

function generateLevel(level, mask) {
  const step = level.spacing;
  const points = [];
  let row = 0;
  // Half-cell offsets avoid sampling duplicate ±180° seam points and center the lattice.
  for (let lat = -90 + step / 2; lat < 90; lat += step, row += 1) {
    const lonStep = step / Math.max(0.35, Math.cos((lat * Math.PI) / 180));
    const columns = Math.max(1, Math.round(360 / lonStep));
    const exactLonStep = 360 / columns;
    const offset = row % 2 ? exactLonStep / 2 : 0;
    for (let column = 0; column < columns; column += 1) {
      const lon = -180 + offset + column * exactLonStep;
      if (lon <= -180 + 1e-8 || lon >= 180 - 1e-8) continue;
      if (isLand(mask, lon, lat)) points.push([Number(lon.toFixed(5)), Number(lat.toFixed(5))]);
    }
  }
  return {
    type: 'FeatureCollection',
    name: `natural-earth-land-dots-${level.id}`,
    features: points.map(([longitude, latitude]) => ({
      type: 'Feature',
      properties: null,
      geometry: { type: 'Point', coordinates: [longitude, latitude] }
    }))
  };
}

// Flat (equirectangular) lattice: equal longitude and latitude steps, no
// row stagger and no 1 / cos(latitude) widening. Under plate carrée a degree
// of longitude is the same number of pixels at every latitude, so this is
// what keeps dot spacing uniform from the equator to the high latitudes.
// Land membership uses the identical cached mask as the globe levels.
function generateFlatLevel(level, mask) {
  const step = level.spacing;
  const columns = Math.round(360 / step);
  const rows = Math.round(180 / step);
  const points = [];
  for (let row = 0; row < rows; row += 1) {
    const lat = -90 + (row + 0.5) * step;
    for (let column = 0; column < columns; column += 1) {
      const lon = -180 + (column + 0.5) * step;
      if (isLand(mask, lon, lat)) points.push([Number(lon.toFixed(5)), Number(lat.toFixed(5))]);
    }
  }
  return {
    type: 'FeatureCollection',
    name: `natural-earth-land-dots-${level.id}`,
    features: points.map(([longitude, latitude]) => ({
      type: 'Feature',
      properties: null,
      geometry: { type: 'Point', coordinates: [longitude, latitude] }
    }))
  };
}

async function main() {
  await mkdir(OUTPUT_DIR, { recursive: true });
  const geojson = JSON.parse(await getSource());
  const rings = getRings(geojson);
  const mask = await readOrBuildMask(rings);
  for (const level of SETTINGS.levels) {
    const collection = generateLevel(level, mask);
    const outputPath = resolve(OUTPUT_DIR, `dots-${level.id}.geojson`);
    await writeFile(outputPath, `${JSON.stringify(collection)}\n`);
    console.log(`${level.id}: ${collection.features.length.toLocaleString()} land dots (${level.spacing}° nominal spacing)`);
  }
  for (const level of SETTINGS.flatLevels) {
    const collection = generateFlatLevel(level, mask);
    const outputPath = resolve(OUTPUT_DIR, `dots-${level.id}.geojson`);
    await writeFile(outputPath, `${JSON.stringify(collection)}\n`);
    console.log(`${level.id}: ${collection.features.length.toLocaleString()} land dots (${level.spacing}° uniform lattice)`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
