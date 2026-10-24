// Screen 1 — Landing.
// Wordmark top-left, one line of service description, the shared auto-rotating
// globe behind. Nothing else. The globe keeps its existing behaviour: it spins
// until dragged, and only resumes at full-globe zoom.

import { cssDurationMs } from '../../settings.js';

export function createLandingScreen({ getGlobe, onAdvance }) {
  const element = document.createElement('section');
  element.className = 'screen landing';
  element.id = 'screen-landing';
  element.innerHTML = `
    <header class="landing__identity">
      <h1 class="wordmark">SmoothSail</h1>
      <div class="landing__rule"></div>
      <p class="lede">Ocean freight routing, voyage cost and compliance screening — from one port pair and a departure date.</p>
    </header>

    <p class="landing__scroll-cue mono-label">Scroll to plan a shipment</p>

    <p class="landing__footer mono-label">
      <span>SmoothSail / Ocean freight</span>
      <span>Drag to rotate · Scroll to zoom</span>
    </p>
  `;

  // Scrolling past the fold reveals the search panel (screen 2). The wheel is
  // listened for on the app root (main.js) because the globe canvas sits above
  // this overlay and keeps its own scroll-to-zoom untouched.
  let wheelTravel = 0;

  function handleWheel(deltaY) {
    wheelTravel = deltaY > 0 ? wheelTravel + deltaY : 0;
    if (wheelTravel > 240) {
      wheelTravel = 0;
      onAdvance?.();
    }
  }

  return {
    element,
    showGlobe: true,
    handleWheel,
    enter() {
      wheelTravel = 0;
      // Returning to the landing restores the ambient full-globe view.
      const globe = getGlobe();
      globe?.map.easeTo({ center: [15, 12], zoom: 1, duration: cssDurationMs('--camera-reset-duration', 900) });
      globe?.map.once('moveend', () => globe.resumeAutoRotate());
    }
  };
}
