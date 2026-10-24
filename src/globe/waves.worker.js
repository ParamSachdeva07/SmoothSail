import { renderWavePair } from './waves.js';
import { highSeasFeatures } from './hazards.js';
let grid, ramp;
const hazardFrames = new Map();
self.onmessage = ({ data }) => {
  if (data.type === 'init') { grid = data.grid; ramp = data.ramp; hazardFrames.clear(); return; }
  try {
    const tiles = renderWavePair(grid, data.pair, { ramp });
    const hazards = [data.pair.a, data.pair.b].map(index => {
      if (!hazardFrames.has(index)) hazardFrames.set(index, highSeasFeatures(grid, index));
      return hazardFrames.get(index);
    });
    while (hazardFrames.size > 4) hazardFrames.delete(hazardFrames.keys().next().value);
    self.postMessage({ key: data.key, tiles, hazards }, tiles.flatMap((tile) => tile.pixels.map((pixels) => pixels.buffer)));
  } catch { self.postMessage({ key: data.key, error: true }); }
};
