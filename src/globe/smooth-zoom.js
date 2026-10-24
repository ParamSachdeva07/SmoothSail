// Use one retargetable camera ease for mouse wheels and trackpads. The map still
// owns projection, bounds and rendering; touch pinch keeps its native handler.
export function wheelZoomDelta(event, height, sensitivity = 1) {
  const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1);
  const scaled = pixels * (event.ctrlKey ? 4 : 1);
  return -Math.max(-160, Math.min(160, scaled)) * 0.0025 * sensitivity;
}

export function createSmoothZoom(map, { sensitivity = 1, reducedMotion = matchMedia('(prefers-reduced-motion: reduce)') } = {}) {
  const canvas = map.getCanvas();
  let target = null, direction = 0, lastInput = -Infinity, retargeting = false;
  map.scrollZoom.disable();
  const reset = () => { target = null; direction = 0; };
  function zoom(delta, around) {
    if (!delta) return;
    const now = performance.now();
    // Reverse immediately instead of making the user scroll through queued zoom.
    const continuing = target !== null && now - lastInput < 250 && direction === Math.sign(delta);
    target = Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), (continuing ? target : map.getZoom()) + delta));
    direction = Math.sign(delta); lastInput = now;
    retargeting = true;
    try {
      map.easeTo({ zoom: target, ...(around ? { around } : {}), duration: reducedMotion.matches ? 0 : 260,
        easing: t => 1 - (1 - t) ** 3 });
    } finally { retargeting = false; }
  }
  function wheel(event) {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    zoom(wheelZoomDelta(event, rect.height, sensitivity), map.unproject([event.clientX - rect.left, event.clientY - rect.top]));
  }
  canvas.addEventListener('wheel', wheel, { passive: false });
  const ended = () => { if (!retargeting) reset(); };
  map.on('dragstart', reset);
  map.on('zoomend', ended);
  return {
    zoomBy: delta => zoom(delta),
    reset,
    destroy() { canvas.removeEventListener('wheel', wheel); map.off('dragstart', reset); map.off('zoomend', ended); }
  };
}
