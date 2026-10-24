// Fade-only screen router. No slide, no parallax — 250ms cross-fade and the
// previous screen is simply hidden.

export function createRouter({ root, screens }) {
  let current = null;

  function go(id, payload) {
    if (current === id || !screens[id]) return;
    for (const [screenId, screen] of Object.entries(screens)) {
      const active = screenId === id;
      screen.element.dataset.active = String(active);
      if (active) screen.enter?.(payload);
      else if (screenId === current) screen.leave?.();
    }
    current = id;
    root.dataset.screen = id;
    // Screens 1-2 sit over the globe; later screens replace it entirely.
    root.dataset.globe = screens[id].showGlobe ? 'on' : 'off';
  }

  return { go, get current() { return current; } };
}
