import { renderWaveFrame } from './wave-texture.js';
let grid, ramp;
self.onmessage = ({ data }) => {
  if (data.type === 'init') { grid = data.grid; ramp = data.ramp; return; }
  try {
    const frame = renderWaveFrame(grid, data.values, ramp);
    self.postMessage({ index: data.index, ...frame }, [frame.pixels.buffer]);
  } catch { self.postMessage({ index: data.index, error: true }); }
};
