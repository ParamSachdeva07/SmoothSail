# SmoothSail prototype audit

Audit date: 2026-10-24. Scope: files currently present in the project root, excluding `node_modules/` and `dist/`. This was a read-only inspection; no application code, data, dependencies, or build artifacts were changed.

## Executive finding

The checked-in prototype is a focused dot-matrix globe demo, not yet an ocean-freight product UI. The current DOM contains a full-screen globe, a live status region, and a two-part footer hint (`index.html:10-16`). There is **no left panel, SmoothSail wordmark, From/To/Date input, submit button, form state, validation, port list, route result, compliance alert, cost/risk comparison, or freight API integration** in the inspected files.

## 1. Stack and structure

### Stack

| Area | Current implementation | Evidence |
|---|---|---|
| Application | Vanilla HTML, CSS, and browser ES modules; no React/Vue/Svelte component framework | `index.html:1-17`, `src/main.js:1-4` |
| Renderer/map engine | Mapbox GL JS, declared as `^3.17.0`; lockfile currently resolves `3.33.0` | `package.json:12-14`, `package-lock.json:908-919` |
| Bundler/dev server | Vite, declared as `^6.4.1`; lockfile currently resolves `6.4.5` | `package.json:15-17`, `package-lock.json:1062-1081` |
| Data preparation | A standalone Node ES-module script using only Node built-ins | `scripts/generate-dots.mjs:1-9` |
| Configuration | One shared JavaScript object consumed by both browser renderer and data generator | `src/settings.js:1-26`, `scripts/generate-dots.mjs:4` |
| Tests/lint/type checking | None configured | `package.json:6-17` |

Package scripts are:

- `npm run data:generate`: regenerates all precomputed dot GeoJSON files (`package.json:6-8`).
- `npm run dev`: starts Vite on all interfaces (`package.json:8`).
- `npm run build`: creates a production Vite build (`package.json:9`).
- `npm run preview`: serves the production build on all interfaces (`package.json:10`).

Vite uses `public/` as the public directory, permits filesystem access only to the project, and raises its chunk-size warning threshold to 900 kB (`vite.config.js:3-13`).

### File tree and responsibilities

```text
.
├── .env.example                         Mapbox public-token template.
├── .env.local                           Ignored local environment file; contents not audited.
├── .gitignore                           Ignores dependencies, builds, masks and local env files.
├── README.md                            Setup and architecture notes; materially stale in places.
├── assets/
│   ├── land-mask-0.05deg.bin            25,920,000-byte cached global land mask used at generation time.
│   ├── natural-earth-attribution.txt    Natural Earth provenance/public-domain note.
│   ├── natural-earth-land.geojson       10 m Natural Earth physical land polygons (~10.2 MB).
│   └── world-map.jpg                    Legacy 540×360 raster reference; unused by runtime/generator.
├── index.html                           Single-page shell: globe, status and footer hint.
├── package-lock.json                    Exact dependency graph.
├── package.json                         Metadata, scripts and direct dependencies.
├── public/data/
│   ├── dots-overview.geojson            Precomputed overview points.
│   ├── dots-global.geojson              Precomputed global points.
│   ├── dots-regional.geojson            Precomputed regional points.
│   ├── dots-detailed.geojson            Precomputed detailed points.
│   └── dots-finest.geojson              Precomputed finest points.
├── scripts/generate-dots.mjs            Natural Earth → binary mask → five point datasets pipeline.
├── src/
│   ├── globe.css                        Canvas cursor/focus and initialization background.
│   ├── main.js                          Mapbox setup, LOD layers, interactions and auto-rotation.
│   └── settings.js                      Palette, camera, interaction and LOD constants.
├── style.css                            Global page, status and footer-hint styling.
└── vite.config.js                       Vite public directory, server access and warning threshold.
```

`.env.local` is excluded by `.gitignore`; `.env.example` is explicitly retained (`.gitignore:4-6`). The expected variable is `VITE_MAPBOX_ACCESS_TOKEN` (`.env.example:1-3`, `src/main.js:6`).

## 2. Globe implementation

### Rendering and projection

- The globe is rendered by **Mapbox GL JS using WebGL**, not Canvas 2D, Three.js, p5.js, or d3-geo. Land dots are Mapbox `circle` layers backed by GeoJSON point sources (`src/main.js:90-126`).
- Both the initial style and the map explicitly select Mapbox's `globe` projection (`src/main.js:24-35`).
- The map starts at longitude `15`, latitude `12`, zoom `1.25`, pitch `0`, and bearing `0` (`src/settings.js:9-11`, `src/main.js:36-41`).
- Rear-hemisphere hiding and globe projection are handled by Mapbox. There is no custom back-face-culling code.

### Land source and resolution

- Geography is Natural Earth **1:10m physical land**, stored as GeoJSON. The source URL is the `ne_10m_land.geojson` file in the Natural Earth repository (`scripts/generate-dots.mjs:7-8`, `assets/natural-earth-attribution.txt:1-4`).
- The local source is a `FeatureCollection` named `ne_10m_land`, with 11 land features: 10 `MultiPolygon` and one `Polygon` (`assets/natural-earth-land.geojson:1`).
- It contains land/coastline only. Country boundaries are not present (`assets/natural-earth-attribution.txt:3`).
- `assets/world-map.jpg` is not referenced anywhere in the runtime or generator. The README also says the previous raster reference is unused (`README.md:5-6`).

### Dot generation

Generation is offline/precomputed, not performed in the browser:

1. Polygon and multipolygon rings are flattened into a ring list (`scripts/generate-dots.mjs:29-42`).
2. A scanline fill rasterizes all rings into a 0.05° binary mask. Each latitude row collects edge crossings, sorts them, and fills alternating crossing pairs (`scripts/generate-dots.mjs:44-84`).
3. Point membership is then an O(1) lookup into that cached mask, not a runtime geometric point-in-polygon test (`scripts/generate-dots.mjs:87-91`).
4. Each density level uses staggered latitude rows. For nominal spacing `s`:

   ```js
   latitudeStep = s
   longitudeStep ≈ s / max(0.35, cos(latitude))
   rowOffset = oddRow ? exactLongitudeStep / 2 : 0
   ```

   Columns are rounded to divide 360° exactly, and seam points at ±180° are skipped (`scripts/generate-dots.mjs:93-108`). This is a latitude/longitude-derived, alternately staggered spherical grid—not a Fibonacci sphere and not screen-space sampling.
5. Matching mask cells become GeoJSON `Point` features with five-decimal coordinates (`scripts/generate-dots.mjs:106-117`).

Current precomputed levels are:

| Level | Nominal spacing | Base radius | Fade stops | Point count | GeoJSON size |
|---|---:|---:|---|---:|---:|
| overview | 1.25° | 1.30 px | `[0.9, 1.0, 1.5, 2.05]` | 8,407 | 819,058 B |
| global | 0.75° | 1.28 px | `[1.4, 2.05, 2.65, 3.25]` | 23,308 | 2,270,179 B |
| regional | 0.47° | 1.26 px | `[2.55, 3.2, 3.8, 4.4]` | 59,399 | 5,795,837 B |
| detailed | 0.31° | 1.24 px | `[3.7, 4.4, 5.0, 5.6]` | 136,514 | 13,336,473 B |
| finest | 0.235° | 1.22 px | `[4.9, 5.6, 6.5, 7.0]` | 237,632 | 23,448,140 B |

Level constants are defined in `src/settings.js:18-24`; each generated dataset is a one-line GeoJSON `FeatureCollection` (`public/data/dots-overview.geojson:1`, `public/data/dots-global.geojson:1`, `public/data/dots-regional.geojson:1`, `public/data/dots-detailed.geojson:1`, `public/data/dots-finest.geojson:1`). Total precomputed payload is 465,260 points and 45,669,687 bytes (~43.6 MiB) before HTTP compression and in-memory expansion.

### Zoom response and level of detail

Dot spacing does not recompute in the browser. Each level is a separate precomputed dataset. A zoom handler loops over the five settings and permanently adds a level once the current zoom plus `0.8` reaches that level's first fade stop (`src/main.js:77-78`, `src/main.js:129-133`). This prefetch offset reduces but does not eliminate late-source popping.

For a level with base radius `r` and fade array `[z0,z1,z2,z3]`, Mapbox linearly interpolates radius as:

```text
z0                 → 1.12r
(z1 + z2) / 2      → 1.00r
z3                 → 0.88r
```

The exact expression is `src/main.js:110-115`. Opacity crossfades from `0` at `z0`, to `1` at `z1`, stays `1` through `z2`, then falls to `0` at `z3` (`src/main.js:116-122`). Layers exist only from `z0` through `z3 + 0.01` (`src/main.js:102-107`).

Therefore the prototype provides genuine coastline LOD rather than merely scaling one texture. However, each level is generated independently, so dots do not retain identity or morph into children; overlapping grids crossfade. This can produce subtle repatterning/shimmer, and a slow first-time source load can still appear late.

### Auto-rotation

- Auto-rotation is enabled at `2` longitude degrees per second (`src/settings.js:15-17`). A full revolution therefore takes approximately 180 seconds.
- The camera center longitude decreases, which makes the globe rotate eastward/west-to-east (`src/main.js:180-184`). Longitude is wrapped into `[-180,180)` (`src/main.js:187-189`).
- The loop is driven from Mapbox's `render` event. It reads `performance.now()`, caps one frame's elapsed time at 50 ms, and calls `map.setCenter()` every active frame (`src/main.js:167-185`). Motion is constant-speed; there is no rotation easing.
- `mousedown`, `touchstart`, or `zoomstart` disables auto-rotation immediately (`src/main.js:135-151`). It stays disabled after interaction.
- Rotation resumes only when zoom is at or below `minZoom + 0.02`, either on `zoomend` or an outward wheel event at minimum zoom (`src/main.js:143-165`, `src/settings.js:7,17`).
- `map.isMoving()` suppresses the auto loop during Mapbox movement/inertia (`src/main.js:167-170`).

### Interaction

- Dragging is implemented through Mapbox `dragPan`, which rotates the globe in globe projection. It is configured with linearity `0.85`, maximum speed `1200`, and deceleration `1400 / 0.92 ≈ 1521.74` (`src/main.js:51-56`, `src/settings.js:12-14`).
- Zoom is constrained to `1–6.5` (`src/settings.js:7-8`, `src/main.js:37-39`).
- Wheel zoom uses rates `1/450` and `1/100` derived from `zoomSensitivity: 1` (`src/main.js:60-62`, `src/settings.js:13`). Mapbox's wheel zoom retains its default pointer anchor.
- Touch pinch explicitly uses `{ around: 'center' }`; touch rotation is disabled (`src/main.js:58-59`). Pinch therefore zooms to the center, not the fingers' geographic anchor.
- Double-click zoom, box zoom, and all keyboard controls are disabled (`src/main.js:63-65`).
- `touch-action: none` and `overscroll-behavior: contain` keep gestures inside the globe (`style.css:30-36`).

### Surface, atmosphere, antialiasing and pixel ratio

- The style's background layer makes the globe/ocean blue `#0800ff`; dots are green `#0cfd03` (`src/main.js:24-32`, `src/settings.js:4-6`).
- Mapbox fog uses the same blue for low/high atmosphere, white space, zero horizon blend, and zero stars. The result is a hard blue globe against white rather than an edge glow (`src/main.js:67-76`).
- There is no explicit Mapbox `antialias` option. Circle-edge antialiasing and device-pixel-ratio canvas sizing are left to Mapbox/browser defaults; there is no custom DPR cap or retina logic (`src/main.js:21-48`).
- Dots are map-aligned and map-scaled, so their distribution foreshortens at the limb (`src/main.js:123-124`).
- `src/globe.css:1-6` still forces a black initialization/resize background behind the white-space WebGL result; this can create a black flash and contradicts the current palette.

### Performance characteristics

- Dot generation and land classification are correctly kept out of the frame loop. Zoom events perform only a five-item settings scan and add missing sources once (`src/main.js:90-100`, `src/main.js:129-133`).
- Once added, sources are never removed. At high zoom all 465,260 GeoJSON points remain loaded, even though most layers are outside their active zoom range.
- The browser must download/parse up to ~43.6 MiB of raw GeoJSON. GeoJSON object expansion, worker tiling and GPU buffers will consume substantially more memory than the files themselves.
- Continuous auto-rotation deliberately prevents the renderer from becoming idle: every active frame calls `getCenter()` and `setCenter()` (`src/main.js:167-184`). This is simple but carries ongoing CPU/GPU and battery cost.
- During crossfade, Mapbox may draw two large circle layers simultaneously. No explicit performance budget, reduced-motion path, mobile density reduction, viewport filtering, or FPS adaptation exists.
- `loadedLevels` is updated before `addSource()`/`addLayer()` succeeds (`src/main.js:90-102`). A synchronous failure after insertion into the set would prevent retrying that level.

### Extensibility for freight features

The Mapbox foundation can support the planned overlays without replacing the renderer:

| Feature | Feasibility | What is missing |
|---|---|---|
| Route arcs | Good | Generate a densified great-circle GeoJSON `LineString`, add source and `line` layer; no route model exists now. |
| Port markers | Good | Add port GeoJSON and circle/symbol layers; no port dataset, icons or selection state exists. |
| Vessel glyph | Good | Use a Mapbox symbol layer/custom image/marker and update bearing/position; no asset or vessel state exists. |
| Ocean-area overlays | Good | Data layers can render over the blue background; careful layer ordering and contrast rules will be needed. |
| Fly camera to coordinates | Native capability | Call Mapbox `flyTo`/`easeTo`; no product-level camera API exists. The map is exposed only in development as `window.__dotGlobeMap` (`src/main.js:49`). |
| Country borders later | Technically straightforward | Add boundary GeoJSON/vector tiles and a line layer. Current Natural Earth file explicitly contains no borders (`assets/natural-earth-attribution.txt:3`). |

## 3. Styling

### Approach

Styling is plain global CSS: `style.css` is linked from the HTML (`index.html:8`), Mapbox's vendor CSS and `src/globe.css` are imported from JavaScript (`src/main.js:1-3`). There are no CSS modules, Tailwind, CSS-in-JS, scoped component styles, or CSS custom properties.

### De facto design tokens

#### Colour

| Token/value | Usage | Notes |
|---|---|---|
| `#0800ff` | Globe/ocean and low/high fog | Highly saturated blue; `src/settings.js:5`, `src/main.js:70-73`. |
| `#0cfd03` | All land dots | Highly saturated green; `src/settings.js:4`, `src/main.js:109`. |
| `#ffffff` | Page, shell, map container, Mapbox space | Duplicated in CSS and JS rather than shared; `style.css:11,25,33`, `src/settings.js:6`. |
| `#444444` | Base document text | `style.css:12`. |
| `rgba(68,68,68,0.82)` | Status/error copy | `style.css:56`. |
| `rgba(68,68,68,0.68)` | Bottom hint | Small 10/8 px copy may have marginal contrast after alpha blending; `style.css:76-89`. |
| `#000000` | HTML browser theme colour and initialization canvas background | Conflicts with the white screen and can flash during initialization; `index.html:6`, `src/globe.css:1-6`. |
| `rgba(255,255,255,0.35)` | Canvas focus outline | Low contrast against the white outer screen and only conditionally visible over blue; `src/globe.css:16-18`. |

The style-layer id remains `black-background` although it now renders blue (`src/main.js:28-32`), another naming inconsistency.

#### Typography

| Property | Value | Location |
|---|---|---|
| Font stack | `Inter, "Helvetica Neue", Helvetica, Arial, sans-serif` | `style.css:13,77` |
| Status size/line height | `13px / 1.6` | `style.css:57-58` |
| Hint size/line height | `10px / 1.2` | `style.css:77` |
| Mobile hint size | `8px` at `≤520px` | `style.css:86-89` |
| Status letter spacing | `0.025em` | `style.css:60` |
| Hint letter spacing | `0.16em`; mobile `0.11em` | `style.css:78,89` |

No font file or webfont stylesheet is loaded. `Inter` appears only if installed on the user's system; otherwise the design falls back to Helvetica/Arial (`index.html:3-9`, `style.css:13`).

#### Spacing, sizing and placement

| Value | Usage |
|---|---|
| `0` | Global margin, hint margin, absolute map inset (`style.css:9,32,75`). |
| `100%` | Root/body/shell width and height (`style.css:7-8,22-23`). |
| `320px` | Minimum shell height (`style.css:24`). |
| `50%` + `translate(-50%,-50%)` | Status centering (`style.css:53-55`). |
| `min(440px, calc(100vw - 40px))` | Status width (`style.css:54`). |
| `3.7%` horizontal / `3.5%` bottom | Footer-hint inset (`style.css:71`). |
| `1rem` | Gap between footer labels (`style.css:74`). |
| `1px` / `-3px` | Focus outline and inset offset (`src/globe.css:17-18`). |
| `2` | Overlay z-index for status and hint (`style.css:51,70`). |

There are no authored border radii, borders, shadows, gradients, or CSS transitions. Mapbox style fading is explicitly disabled with `fadeDuration: 0` (`src/main.js:46`); LOD changes remain smooth because circle paint properties use zoom interpolation, not a CSS transition.

### Layout and responsive behavior

- The page is a full-viewport, overflow-hidden shell with an absolutely positioned map filling it (`style.css:5-36`).
- Status content overlays the center. The footer hint is an absolute flex row along the bottom (`style.css:50-83`).
- The only responsive rule reduces footer text from 10 px to 8 px below 520 px (`style.css:86-90`).
- No left panel exists, so there is no desktop/mobile form layout, drawer behavior, stacking breakpoint, or route-results layout to assess.

## 4. UI components

This is not componentized code. The effective UI elements are:

| Element | Props/state/logic | Evidence |
|---|---|---|
| Full-screen shell | Static `<main>` with an accessible label | `index.html:11` |
| Globe mount | Static `<div id="globe">`; Mapbox injects canvas and interaction DOM | `index.html:12`, `src/main.js:7,21-48` |
| Status region | `role="status"`, `aria-live="polite"`; text is set for missing/rejected tokens and cleared on load | `index.html:13`, `src/main.js:14-15,67-68,82-86,191-193` |
| Footer label | Static “DOT MATRIX / EARTH” plus interaction instructions | `index.html:14` |

There is no SmoothSail wordmark, input component, date picker, button, footer navigation, form props/state, validation, or submission handler.

Icons are not project assets. Mapbox may inject its provider logo/control assets through its library CSS, but all four Mapbox control containers are hidden with `display:none !important` (`style.css:43-48`). The map is still configured with `attributionControl: true` (`src/main.js:42`), so the code and CSS contradict each other.

### Accessibility gaps

- Keyboard map control is explicitly disabled, with no equivalent controls (`src/main.js:63-65`).
- All interactions are pointer/touch gestures; there are no accessible zoom/rotate buttons.
- Auto-rotation has no visible pause control and does not respect `prefers-reduced-motion` (`src/main.js:135-185`).
- The globe container has an ARIA label, but the visualization communicates no data semantics to assistive technology (`index.html:11-13`).
- The white focus ring is poorly suited to the white screen (`src/globe.css:16-18`).
- Footer instructions are 10 px desktop and 8 px mobile, below comfortable reading sizes (`style.css:77,86-89`).
- Provider attribution/logo are visually suppressed, creating a likely licensing/compliance problem as well as removing source transparency (`style.css:43-48`, `README.md:5`).
- There are no form labels, field errors, focus order, date semantics or validation to audit because the freight form is absent.

## 5. State and data

Current mutable state is limited to:

- The `map` instance (`src/main.js:9`).
- A `Set` of loaded LOD ids (`src/main.js:10`).
- Auto-rotation timestamp and enabled flag (`src/main.js:11-12`).
- Camera/source/layer state held internally by Mapbox.

There are no From, To, or Date values anywhere in the DOM or JavaScript; nothing happens on submit because there is no form or submit event. There are no mock quotes, costs, ETAs, risks, compliance rules, vessel records, routes, ports, port autocomplete data, or freight APIs.

Runtime data calls are:

- Local `/data/dots-<level>.geojson` fetches initiated by Mapbox as levels are added (`src/main.js:90-100`).
- Mapbox GL JS's own token/session/telemetry requests, implicit in the library and public access token setup (`src/main.js:6,17,22`).

Generation-time data behavior is separate: if the local Natural Earth file is missing, the script downloads it from GitHub (`scripts/generate-dots.mjs:16-26`). Because the file currently exists, generation can use the local copy.

## 6. Assessment

### Solid and reusable as-is

- Mapbox's globe/camera/gesture foundation is a strong fit for route arcs, ports, vessel positions and camera flights (`src/main.js:21-65`).
- Natural Earth 10 m land provides appropriately detailed coastlines for a polished global freight view (`scripts/generate-dots.mjs:7-8`).
- Offline mask generation keeps expensive geometry classification out of runtime (`scripts/generate-dots.mjs:44-91`).
- Five precomputed LODs and zoom-interpolated radius/opacity give real progressive detail with a small, understandable control surface (`src/settings.js:18-24`, `src/main.js:102-125`).
- Token error messages and `.env` hygiene are reasonable prototype safeguards (`src/main.js:14-18,82-86`, `.gitignore:4-6`).
- Auto-rotation behavior is explicit and product-appropriate: start ambient motion, yield to interaction, resume only at full-globe zoom (`src/main.js:135-185`).

### Refactor before building more

1. **Introduce product structure.** Split map creation, camera controls, dot-LOD management, route overlays, search/form state, and results into modules. `src/main.js` currently owns every runtime responsibility (`src/main.js:1-193`).
2. **Create a genuine token system.** Move palette, typography, spacing and motion values into CSS custom properties/shared constants. White and typography values are duplicated across files (`style.css:5-89`, `src/settings.js:4-6`).
3. **Resolve source/attribution compliance.** Do not hide the Mapbox control containers; provide required Mapbox and Natural Earth attribution in a deliberate footer (`style.css:43-48`, `assets/natural-earth-attribution.txt:1-4`).
4. **Design a data-overlay API.** Add named layer/source factories and stable layer ordering before adding routes, ports, risks and vessels. Current layers are appended ad hoc (`src/main.js:90-126`).
5. **Define product state.** Add an explicit route-search state model, validation schema, request lifecycle and result model before connecting APIs. None exists now.
6. **Budget and tile the dot data.** Raw GeoJSON is acceptable for a demo but expensive as the product accumulates overlays. Consider vector tiles, viewport-aware loading, lower mobile densities, or worker-prepared binary data.
7. **Add lifecycle and error handling.** Provide retryable source loading, user-visible data errors, map teardown and tests. `loadedLevels` can block retry after a failed addition (`src/main.js:90-100`).
8. **Add accessible controls and reduced motion.** Gesture-only navigation and continuous animation are not sufficient for production (`src/main.js:63-65,135-185`).
9. **Update documentation.** README claims white dots on black, no ocean/atmosphere, auto-rotation off, and old spacing values; all are inconsistent with current code (`README.md:3,23,26` versus `src/settings.js:4-24` and `src/main.js:70-76`).

### Visually default/generic elements

- The page has no SmoothSail identity; “DOT MATRIX / EARTH” reads as a technical demo label rather than a freight product (`index.html:14`).
- The system-font fallback, tiny uppercase footer, wide tracking and two neon primary colours look like an unthemed visualization prototype, not a deliberate logistics interface (`style.css:13,68-89`, `src/settings.js:4-6`).
- There is no hierarchy beyond globe + footer: no search task, selected route, result summary, risk status, legend or information architecture (`index.html:10-16`).
- Browser/system Mapbox interaction behavior is mostly unstyled; there are no authored controls, states, loading skeletons or empty/error compositions.
- The blue sphere/green dots are distinctive, but no semantic visual language maps colour, line style or size to cost, time, risk, compliance or vessel status.

### Risks and bugs observed (not fixed)

- **Context mismatch:** the requested freight form and product features are absent from the inspected project.
- **Attribution hidden:** CSS hides all Mapbox control containers despite `attributionControl: true` and README's claim that attribution is retained (`style.css:43-48`, `src/main.js:42`, `README.md:5`).
- **Palette flash/inconsistency:** theme colour and initialization background are black while the actual screen is white (`index.html:6`, `src/globe.css:1-6`, `style.css:11-33`).
- **Stale documentation:** current visual and interaction settings disagree with README (`README.md:3,23,26`).
- **Heavy client data:** up to 465,260 points/~43.6 MiB raw GeoJSON accumulate in memory.
- **Continuous rendering:** idle auto-spin keeps CPU/GPU active and has no reduced-motion escape (`src/main.js:135-185`).
- **LOD late-load risk:** a new source is only requested 0.8 zoom units early; slow connections can expose a missing layer before parsing completes (`src/main.js:77-78,129-133`).
- **Independent grids:** crossfading unrelated samples can shimmer rather than morph cleanly.
- **Retry weakness:** `loadedLevels` is marked before source/layer addition succeeds (`src/main.js:90-102`).
- **Limited error UX:** only token 401/403 errors reach the status region; data/WebGL errors remain console-only (`src/main.js:82-87`).
- **Keyboard/accessibility:** keyboard map controls are disabled and there are no replacement controls (`src/main.js:63-65`).
- **No automated quality gates:** no test, lint, formatting, type-checking or accessibility scripts exist (`package.json:6-17`).
- **Unpinned declared ranges:** `^3.17.0` and `^6.4.1` allow future compatible upgrades; the lockfile currently resolves significantly newer Mapbox `3.33.0` (`package.json:12-17`, `package-lock.json:908-919`).
