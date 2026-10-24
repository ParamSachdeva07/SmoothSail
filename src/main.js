// SmoothSail — application entry.
// The globe engine lives in src/globe/globe.js (maths unchanged from the
// audited prototype); this file owns the shared globe stage and the screens.

// NOTE: the prototype's ../style.css is superseded by tokens.css + app/app.css
// and is intentionally no longer loaded. The file is left in place untouched.
import './tokens.css';
import './app/app.css';
import { createGlobe } from './globe/globe.js';
import { createRouter } from './app/router.js';
import { createLandingScreen } from './app/screens/landing.js';
import { createSearchScreen } from './app/screens/search.js';
import { createCompareScreen } from './app/screens/compare.js';
import { createDetailScreen } from './app/screens/detail.js';
import { api } from './api/client.js';
import { setReport, findRoute } from './data/routes.js';

const root = document.getElementById('app');

// --- Shared globe stage, persistent across screens 1-2 -------------------
const stage = document.createElement('div');
stage.className = 'globe-stage';
stage.innerHTML = `
  <div id="globe" aria-label="Interactive dot matrix globe"></div>
  <p class="status" id="status" role="status" aria-live="polite"></p>
`;
root.append(stage);

const statusElement = stage.querySelector('#status');
const globe = createGlobe({
  container: stage.querySelector('#globe'),
  onStatus: (message) => { statusElement.textContent = message; }
});
const getGlobe = () => globe;

// --- Screens -------------------------------------------------------------
const landing = createLandingScreen({
  getGlobe,
  onAdvance: () => router.go('search')
});

const search = createSearchScreen({
  getGlobe,
  onBack: () => router.go('landing'),
  onSubmit: async (input, signal) => {
    const report = await api.planRoutes(input, { signal });
    if (signal.aborted) return;
    setReport(report);
    router.go('compare');
  }
});

let selectedRouteId = null;
function openRoute(id) {
  if (!findRoute(id)) return;
  selectedRouteId = id;
  router.go('detail');
}

const compare = createCompareScreen({
  onBack: () => router.go('search'),
  onViewRoute: openRoute,
  onSelectRoute: openRoute
});

const detail = createDetailScreen({
  getSelectedRouteId: () => selectedRouteId,
  onBack: () => router.go('compare')
});

const screens = { landing, search, compare, detail };
for (const screen of Object.values(screens)) root.append(screen.element);

const router = createRouter({ root, screens });
router.go('landing');

// A downward gesture past the fold advances from the landing to the search
// panel. The globe keeps its own wheel-to-zoom behaviour.
root.addEventListener('wheel', (event) => {
  if (router.current !== 'landing') return;
  landing.handleWheel(event.deltaY);
}, { passive: true });
