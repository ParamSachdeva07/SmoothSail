import { highSeasAtHour } from './hazards.js';

let grid;
self.onmessage = ({ data }) => {
  if (data.type === 'init') { grid = data.grid; return; }
  if (data.frames) grid.frames = data.frames;
  try {
    self.postMessage({ key: data.key, revision: data.revision, hour: data.hour, features: highSeasAtHour(grid, data.hour) });
  } catch {
    self.postMessage({ key: data.key, revision: data.revision, hour: data.hour, error: true });
  }
};
