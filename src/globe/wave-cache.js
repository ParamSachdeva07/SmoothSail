// Bounded, latest-first work: rapid seeks cannot enqueue an entire voyage.
export function createWaveFrameCache(grid, { worker, layer, onReady, onError }) {
  let pair = null, active = false, busy = false;
  function wanted() {
    if (!pair) return [];
    return [...new Set([pair.a, pair.b, pair.b + 1, pair.b + 2, pair.a - 1])].filter(i => i >= 0 && i < grid.frames.length);
  }
  function pump() {
    if (!active || busy) return;
    const index = wanted().find(i => !layer.has(i));
    if (index === undefined) return;
    busy = true;
    worker.postMessage({ type: 'render', index, values: grid.frames[index].values });
  }
  worker.onmessage = ({ data }) => {
    busy = false;
    if (data.error) { active = false; onError(); return; }
    if (wanted().includes(data.index)) layer.put(data.index, data);
    layer.trim(new Set(wanted()));
    onReady(); pump();
  };
  worker.onerror = () => { active = false; busy = false; onError(); };
  return {
    update(nextPair, nextActive) { pair = nextPair; active = nextActive; layer.trim(new Set(wanted())); pump(); },
    ready() { return Boolean(pair && layer.has(pair.a) && layer.has(pair.b)); },
    destroy() { active = false; worker.terminate(); }
  };
}
