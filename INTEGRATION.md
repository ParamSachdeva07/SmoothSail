# INTEGRATION.md

Handoff for merging this front end with the `tideline` MVP backend.

Written from the current code on 2026-10-24. **`README.md`, `AUDIT.md` and `AUDIT-MVP.md` are all stale** — `README.md` describes a globe-only prototype ("white dots on pure black"), and both audits predate this front end. Trust this file and the source; treat those three as history.

---

## 1. Stack and how to run it

| | |
|---|---|
| Language | Vanilla JavaScript, ES modules. **No framework, no TypeScript, no JSX.** |
| Map renderer | `mapbox-gl` `^3.17.0` (the only runtime dependency) |
| Build | `vite` `^6.4.1` (the only dev dependency) |
| Entry | `index.html` → `src/main.js` |
| Static assets | `public/` (served at `/`), per `vite.config.js` |

```bash
npm install
cp .env.example .env.local     # then paste your own Mapbox public token
npm run dev                    # Vite dev server, --host 0.0.0.0
npm run build                  # production build to dist/
npm run preview                # serve the build
npm run data:generate          # regenerate land-dot GeoJSON (slow, rarely needed)
```

- No tests, no linter, no typecheck. `npm test` does not exist.
- `vite.config.js` sets `publicDir: 'public'`, `server.fs.allow: ['.']`, `build.chunkSizeWarningLimit: 900`.
- The build emits a ~1.9 MB JS bundle (Mapbox GL) and warns about chunk size. Expected.

### Framework mismatch — read before planning the merge

This repo and the MVP do not share a stack. Per `AUDIT-MVP.md`, the MVP is **Next.js 16 / React 19 / TypeScript**, `output: 'export'`, rendering with **MapLibre**. This front end is **vanilla JS / Vite / Mapbox GL**. Merging means one of:

1. Port these four screens into React components in the MVP (recommended — the MVP has the real logic, this has the UI).
2. Keep this shell and import the MVP's framework-free `src/lib/*` modules (they are plain TS and have no React or map dependency).

Option 2 also means picking one map library. Mapbox GL needs a token; MapLibre does not.

---

## 2. The four-screen flow

Screens are plain factory functions returning `{ element, showGlobe, enter?, leave? }`. `src/main.js` constructs all four, appends them to `#app`, and wires navigation.

| # | Screen | File | Entered by |
|---|---|---|---|
| 1 | Landing | `src/app/screens/landing.js` | initial `router.go('landing')`; "Back to globe" on screen 2 |
| 2 | Search | `src/app/screens/search.js` | ~240px of cumulative downward wheel on screen 1 (`landing.handleWheel`, listener in `main.js`) |
| 3 | Route comparison | `src/app/screens/compare.js` | form submit on screen 2 (`onSubmit`) |
| 4 | Route detail (flat map) | `src/app/screens/detail.js` | "View route" on a card (`onViewRoute`) |
| 5 | Deep-dive / compliance | **does not exist** | — |

### Router — `src/app/router.js`

- `createRouter({ root, screens })` → `{ go(id, payload), current }`.
- `go()` sets `data-active` on each screen element (CSS cross-fades at `--transition-speed`), calls `enter(payload)` on the incoming screen and `leave()` on the outgoing one.
- Sets `root.dataset.screen` and `root.dataset.globe` (`'on'`/`'off'` from `screen.showGlobe`) — screens 1–2 sit over the live globe, screens 3–4 hide it.
- **Unknown ids are a silent no-op** (`if (!screens[id]) return`). This is why `router.go('deepdive')` does nothing today.
- `leave()` is supported but no screen implements it.

### Navigation that currently dead-ends

`main.js` routes these to `'deepdive'`, which is not registered:

- Screen 3 → "Select this route"
- Screen 4 → "More info", "Choose this route"

They set `selectedRouteId` correctly, then nothing happens. The buttons look live but aren't.

---

## 3. `src/tokens.css` — single source of design truth

Loaded first in `src/main.js`, before every other stylesheet. **All 56 tokens are defined on `:root` in this one file.**

**Rule: do not add a hardcoded colour, font, size, spacing, radius, border or duration anywhere else.** If a value isn't in `tokens.css`, add it there first and reference it with `var()`. Every stylesheet value in `src/app/app.css` and `src/globe.css` is already a `var()`.

| Group | Tokens |
|---|---|
| Colour | `--bg` `--text` `--text-secondary` `--hairline` `--globe-sphere` `--globe-dots` `--vessel` `--accent-primary` `--accent-secondary` `--accent-tertiary` |
| Type | `--font-display` `--font-ui` `--font-mono` `--font-size-11/13/16/24/40/56` `--tracking-caps` `--tracking-display` |
| Space | `--space-1`…`--space-8` `--gutter` `--gutter-compact` |
| Border | `--border-width` `--border-color` `--radius` |
| Motion | `--transition-speed` `--transition-speed-slow` `--transition-easing` |
| Camera (read by JS) | `--camera-ease-duration` `--camera-reset-duration` `--camera-fit-duration` `--camera-zoom-duration` |
| Component sizing | `--control-height` `--control-height-sm` `--panel-width-search` `--form-width-max` `--panel-width-overlays` `--card-summary-height` `--options-max-height` `--status-width-max` `--rule-width` `--scroll-cue-height` `--legend-line-width` `--swatch-size` `--checkbox-size` `--tag-padding-block` `--focus-offset` |

### JS reads the same tokens

WebGL paint properties and camera calls can't use `var()`, so `src/settings.js` exports:

- `cssToken(name, fallback)` — reads a custom property off `document.documentElement`.
- `cssDurationMs(name, fallback)` — same, parsed to a number of ms.

Both return `fallback` when `document` is undefined (so `scripts/generate-dots.mjs` runs under Node) or the stylesheet hasn't applied. Used by `settings.js`, `globe/flatmap.js`, `globe/globe.js`, `app/screens/landing.js`.

### Two tokens are provisional

- `--font-ui` → `"Helvetica Neue", Helvetica, system-ui, Arial, sans-serif`
- `--font-mono` → `"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace`

Neither typeface is decided. Both are one-line swaps; changing `--font-mono` also means updating the Google Fonts `<link>` in `index.html`.

---

## 4. Components

No props objects in the React sense — each factory takes a config object of callbacks and returns a screen handle.

### Screens

| Component | File | Config in | Returns |
|---|---|---|---|
| `createLandingScreen` | `app/screens/landing.js` | `{ getGlobe, onAdvance }` | `{ element, showGlobe: true, handleWheel(deltaY), enter() }` |
| `createSearchScreen` | `app/screens/search.js` | `{ getGlobe, onBack, onSubmit }` | `{ element, showGlobe: true, enter() }` |
| `createCompareScreen` | `app/screens/compare.js` | `{ onBack, onViewRoute(routeId), onSelectRoute(routeId) }` | `{ element, showGlobe: false }` |
| `createDetailScreen` | `app/screens/detail.js` | `{ getSelectedRouteId, onBack, onMoreInfo, onChoose }` | `{ element, showGlobe: false, enter() }` |

- `getGlobe()` must return the globe handle (or `null`); screens call it lazily, never at construction.
- `getSelectedRouteId()` returns a `RouteOption.id` string; `detail.enter()` resolves it via `findRoute()` and falls back to `ROUTES[0]`.

### Renderers

| Component | File | Config in | Returns / notes |
|---|---|---|---|
| `createGlobe` | `globe/globe.js` | `{ container, onStatus? }` | `{ map, flyToRegion([lon, lat], zoom?), pauseAutoRotate, resumeAutoRotate }`. Returns `null` if no Mapbox token. Rendering maths unchanged from the audited prototype — don't edit casually. |
| `createFlatMap` | `globe/flatmap.js` | `{ container }` | `{ map, ready, resize, destroy, showRoute(route, { origin, destination, vesselAt? }), setAlternates(routes), setOverlay(id, visible), zoomBy(delta) }`. `setOverlay` ids: `'wind'`, `'risk'`, `'alternates'`. |
| `createWindOverlay` | `globe/wind-overlay.js` | `{ map, container, field? }` | `{ mount, unmount, resize }`. `field` must expose `sample(lon, lat) → { u, v, knots }`. |
| `createMockWindField` | `globe/wind-overlay.js` | — | the default placeholder field (see §7) |
| `createRouter` | `app/router.js` | `{ root, screens }` | `{ go, current }` |
| `icon` | `app/icons.js` | `(name, size = 16)` | SVG markup string. Placeholder glyphs on Lucide's grid and names. |

### Expected data shapes per component

- `showRoute(route, …)` needs `route.coordinates` (`[lon, lat][]`) and optional `route.stops[].coordinates`; `origin`/`destination` are `Port` objects.
- `compare.js` renders the whole `ROUTES` array and reads `label`, `name`, `durationHours`, `distanceNm`, `speedKnots`, `cost.totalUsd`, `co2Tonnes`, `fuelTonnes`, `risk`, `tags`, `summary`.
- `detail.js` reads `label`, `name`, `durationHours`, `distanceNm`, `cost.totalUsd`, plus `coordinates`/`stops`.

---

## 5. Data contract — and where it may NOT match the MVP

**This is the section most likely to bite.** Everything below was written against `AUDIT-MVP.md`'s *prose description* of the MVP's types. **The MVP source is not on this machine and `src/lib/types.ts` was never read.** Field names were inferred. Verify each one against the real `types.ts` before wiring.

### `Port` — `src/data/ports.js`

```js
{ id: 'ningbo', name: 'Ningbo-Zhoushan', country: 'China',
  code: 'CNNGB', coordinates: [121.95, 29.87] }   // [lon, lat], sea-side approach
```

Exports: `PORTS` (34 entries), `findPort(id)`, `searchPorts(query)` (substring over `name + country + code`).

⚠️ **Discrepancies to check**

- **Field names are guesses.** `AUDIT-MVP.md` says "id/name/country/UN-LOCODE/approach coordinate" but never names the fields. `code` could be `locode`; `coordinates` could be `approach`, or split `lat`/`lon`.
- **The 34 ports here are my list, not the MVP's 34.** They overlap but are almost certainly not identical. **Replace this file wholesale with the MVP's `PORTS` export** rather than reconciling.
- **Port ids are load-bearing in the MVP.** `AUDIT-MVP.md` §5.2/§2.3 says `compliance.ts` keys ECA detection off literal `Port.id` strings (`rotterdam`, `hamburg`, `antwerp`, `felixstowe`, `new-york`, `los-angeles`, `houston`, `vancouver`, `marseille`, `piraeus`, `istanbul`). Mine match those spellings, but ids I invented (`ningbo`, `jebel-ali`, `valparaiso`, …) may not match the MVP's.
- **Coordinates must snap to a connected sea-lane node.** Mine are hand-typed approximations, never validated against the network. The MVP's own approach coordinates are (mean snap 6.1 nm, worst 18.2 nm).

### `VoyageInput` — `src/data/shipment.js`

```js
toVoyageInput() → {
  origin, destination,        // full Port objects, not ids
  departure: '2026-11-23',    // YYYY-MM-DD
  speed: 18, vessel: 'container', priority: 'balanced',
  avoidSuez: false, avoidPanama: false
}
```

This matches `AUDIT-MVP.md` §6 field-for-field, including the MVP's own defaults. **Lowest-risk shape of the three.**

⚠️ **Discrepancies to check**

- `priority` is hardcoded `'balanced'` — the UI never sets it. The MVP accepts `'balanced' | 'fastest' | 'eco'`.
- **The three cards are not three priorities.** Screen 3 shows Fastest / Cheapest / Lowest risk, but the MVP returns up to 3 `RouteOption`s from **one** `planRoutes()` call (shortest, canal-free alternative, slow-steaming). Rough mapping: Fastest ≈ the primary corridor, Cheapest ≈ the slow-steaming variant, Lowest risk ≈ the canal-avoiding alternative. **Do not call `planRoutes()` three times.**
- The MVP only emits the canal-free alternative if the primary used Suez/Panama **and** the detour is >50 nm longer, and only emits slow steaming as a third. A Pacific or Atlantic pair yields **2 options**, so screen 3 must tolerate fewer than three cards. It currently assumes three.
- `shipment` carries extra demo fields the MVP has no concept of: `cargo`, `letterOfCredit`. Keep them front-end-side.
- `shipment` is a **mutable module singleton**, not state passed through the router. Screen 2 writes to it directly.

### `RouteOption` — `src/data/routes.js`

Exports `ROUTES` (3 entries), `findRoute(id)`, `COST_ASSUMPTIONS`, and formatters `formatDuration`, `formatNm`, `formatUsd`, `arrivalDate`.

| Field | Source | Status |
|---|---|---|
| `id`, `name`, `coordinates`, `distanceNm`, `durationHours`, `passages`, `maxWave`, `meanWind`, `forecastSamples`, `weatherCoverage` | mirrors MVP | names inferred, verify |
| `fuelTonnes`, `co2Tonnes`, `days` | computed with the MVP's formulas | **name mismatch likely** |
| `speedKnots` | — | **MVP input calls it `speed`** |
| `label`, `risk`, `tags`, `summary`, `cost`, `costInputs`, `stops`, `vessel` | front end only | **no MVP equivalent** |

Fuel and CO₂ use the MVP's documented model: `days × base × (speed/18)³` with base `58/32/45` t-day for container/bulk/tanker, then `× 3.114` tank-to-wake.

⚠️ **Discrepancies to check**

- **`fuelTonnes` / `co2Tonnes` field names are a guess.** `AUDIT-MVP.md` cites the formulas but not the property names — likely `fuel` / `co2`.
- **`speedKnots` vs `speed`.** `VoyageInput` uses `speed`; my `RouteOption` uses `speedKnots`. Pick one.
- **Nulls are not handled.** `AUDIT-MVP.md` §5.9 is emphatic that missing observations stay `null` and must render as `—`/"Unavailable", never `0`. `maxWave` and `meanWind` are **always numbers here**, and `compare.js` renders them unconditionally. **Real data will produce `null` and the cards will print `null`.** Fix before wiring.
- **`name` is hand-written here.** The MVP derives it from traversed passage tags and falls back to `"Direct ocean passage"` for most ocean routes (§5.2). My names ("Suez Canal transit", "Cape of Good Hope") will be replaced by that generic string for many pairs.
- **`id` values `'fastest' | 'cheapest' | 'lowest-risk'` are mine.** `main.js` defaults `selectedRouteId = 'fastest'` and `findRoute()` looks these up. The MVP's ids/ordering are unknown. **Fix this before swapping** or selection silently falls back to `ROUTES[0]`.
- **`label`, `risk`, `tags`, `summary` have no backend source.** The MVP has no risk model. These must be derived front-end-side from real fields, or the cards lose their differentiators.
- `coordinates` here are ~25 hand-typed waypoints per route. The MVP's come from Dijkstra over 9,681 nodes and are longitude-unwrapped for the antimeridian. The flat map draws whatever it's given — no change needed, but expect far denser geometry.
- `stops` (bunkering calls) is a front-end invention; the MVP models a single leg with no transshipment.

---

## 6. The single swap point

### ⚠️ `planRoutes()` does not exist in this repo

There is no function by that name and nothing calls one. Routes are a **static array built at module load** in `src/data/routes.js`. The "single swap point" is that module's exports, not an existing call site.

Per `AUDIT-MVP.md` §6 the real signature is:

```ts
planRoutes(network: MaritimeNetwork, input: VoyageInput, marine?: MarinePoint[]): RouteOption[]
```

### What to replace

| Export | Currently | Must become |
|---|---|---|
| `ROUTES` | static array of 3, built by `makeRoute()` at import time | result of `planRoutes(network, toVoyageInput(shipment), marine)` |
| `findRoute(id)` | `ROUTES.find(r => r.id === id)` | same, over the live result |

### Consumers to keep working

- `app/screens/compare.js` — imports `ROUTES` at module scope, renders all of them once in `innerHTML`.
- `app/screens/detail.js` — imports `ROUTES` and `findRoute`, calls both inside `enter()`.
- `main.js` — holds `selectedRouteId`, defaulting to `'fastest'`.

### Blockers before it's a drop-in

1. **It's synchronous today.** `ROUTES` is a const available at import. Real planning is async (fetching a 746 KB network GeoJSON + forecasts, then Dijkstra). `compare.js` builds its markup at construction time, so it needs a loading state and a re-render, or `createCompareScreen` must take routes as an argument instead of importing them.
2. **`cost` and `risk` won't come back.** The MVP has no monetary or risk model at all. Either compute them front-end-side from `COST_ASSUMPTIONS` (keep `buildCost()`), or strip those fields from the cards.
3. **Route count varies** (2 or 3) — see §5.
4. **Null weather fields** — see §5.
5. **Route ids** — see §5.
6. **Where it runs.** `AUDIT-MVP.md` §5.4/§6 flags that routing is main-thread and ~1.6 MB of GeoJSON downloads before the first plan. Moving `planRoutes` server-side means dropping the MVP's `output: 'export'`.

---

## 7. Real vs placeholder

### Real

| Thing | Where | Notes |
|---|---|---|
| Land geometry | `public/data/dots-*.geojson` | Natural Earth 1:10m land, rasterised to a 0.05° mask by `scripts/generate-dots.mjs`. 7 levels, ~47 MB total. |
| Globe renderer | `src/globe/globe.js` | Real Mapbox GL globe projection, LOD crossfade, drag/zoom/auto-rotation |
| Flat map renderer | `src/globe/flatmap.js` | Real equirectangular projection; pan clamped to content bounds; `ResizeObserver` wired |
| Voyage physics | `src/data/routes.js` | Fuel/CO₂ use the MVP's real documented model and constants |
| Port names, countries, LOCODEs | `src/data/ports.js` | Real identifiers (but see §5 on ids and coordinates) |

### Placeholder — every item

| # | Thing | Where | What's fake |
|---|---|---|---|
| 1 | **Route geometry** | `routes.js` `SUEZ_COORDINATES`, `CAPE_COORDINATES` | ~25 hand-typed waypoints per corridor. Not routed, not validated against any sea lane. |
| 2 | **Route metrics** | `routes.js` `ROUTES` | `distanceNm` and `speedKnots` are hand-chosen; everything else is derived from them. Not computed from geometry. |
| 3 | **All costs** | `routes.js` `COST_ASSUMPTIONS`, `buildCost()` | Bunker price, vessel day rate, ETS price, canal fees, war-risk premiums, delay provisions — all invented. The MVP has **no** monetary model. Labelled "demo figure" in the UI. |
| 4 | **Risk / compliance status** | `routes.js` `risk`, `tags` | Hand-authored. No sanctions, no war-risk feed, no JWC areas. |
| 5 | **Route summaries** | `routes.js` `summary` | Hand-written prose with the demo numbers baked into the sentences. **Will go stale the moment real numbers arrive.** |
| 6 | **Wind field** | `wind-overlay.js` `createMockWindField()` | Synthetic 4° grid from sine waves (trades, westerlies, calm belts). Swap target: implement `sample(lon, lat) → { u, v, knots }` over real Open-Meteo samples. |
| 7 | **Conflict zones** | `flatmap.js` `riskGrid()` | Three hardcoded lat/lon boxes over the Red Sea / Bab al-Mandab / Gulf of Aden. |
| 8 | **Vessel position** | `flatmap.js` `alongRoute()` | 38% along the polyline by planar length. No AIS. The MVP has a real AIS feed. |
| 9 | **Bunkering stops** | `routes.js` `stops` | Singapore and Durban, invented. |
| 10 | **Shipment + cargo** | `shipment.js` | Fabric rolls, 1 × 40ft, 18,500 kg, departing 23 Nov 2026 — fixed demo values. |
| 11 | **Letter of credit** | `shipment.js` `letterOfCredit` | `LC-4471-NB` and its dates are invented, for a screen 5 that doesn't exist. |
| 12 | **Port coordinates** | `ports.js` | Approximated by hand (see §5). |
| 13 | **Icons** | `app/icons.js` | Hand-drawn SVG paths on Lucide's grid, named to match Lucide, pending the real dependency. |
| 14 | **"Placeholder data"** label | `detail.js` overlay panel | Correctly tells the user overlays are fake. Remove when they aren't. |

---

## 8. Environment variables

**Names only — never commit values.**

| Variable | Used by | Required |
|---|---|---|
| `VITE_MAPBOX_ACCESS_TOKEN` | `src/globe/globe.js`, `src/globe/flatmap.js` (via `import.meta.env`) | **Yes** — both maps return `null` without it and the globe shows an error message |

That is the only variable this repo reads.

From `AUDIT-MVP.md`, the MVP side adds (verify against its own `.env.example`):

- `AISSTREAM_API_KEY` — server-side only, never `NEXT_PUBLIC_`
- `NEXT_PUBLIC_AIS_GATEWAY_URL` — baked in at build time

**Rules**

- Each person keeps their own `.env.local`, created from `.env.example`.
- `.env.local` and `.env` are in `.gitignore` and **must stay there**.
- Mapbox public tokens are visible in the browser — restrict by origin and scope.
- `AUDIT-MVP.md` §5.1 reports a **live AISStream key committed in the MVP folder's `.env.local`**. Treat it as compromised and rotate it before merging anything.

---

## 9. Known issues and cleanup

### Confirmed dead code

- **`style.css` (repo root) is dead.** Verified: nothing imports it. `index.html` doesn't link it; the only two references in the repo are comments in `src/main.js` and `src/tokens.css` saying it's superseded. It also **conflicts** with the current palette — `#ffffff` ×3 (vs `--bg` `#FAFAFA`), `#444444`, two `rgba(68,68,68,…)` greys, and the only `Inter` reference left. Safe to delete.

### Incomplete / not wired

| Issue | Where |
|---|---|
| **Screen 5 doesn't exist.** `router.go('deepdive')` is a silent no-op, so "Select this route", "More info" and "Choose this route" all dead-end. | `main.js`, `router.js` |
| **No loading, error or empty states anywhere.** Routes are synchronous constants; nothing handles a failed fetch. | all screens |
| **Three cards are assumed.** Screen 3 maps over `ROUTES` with no handling for 2 (or 1). | `compare.js` |
| **No null handling for weather fields** — real `null`s will render as `null`. | `compare.js` |
| **`selectedRouteId` defaults to `'fastest'`** before the user picks anything. | `main.js` |
| **`leave()` is supported by the router but no screen implements it** — nothing pauses or tears down on exit. | all screens |
| **`shipment` is a mutable module singleton**, written directly by screen 2. No validation on submit. | `shipment.js`, `search.js` |
| **Search form ignores most of its own state** — only `originId`, `destinationId` and `departure` are read; cargo fields are display-only. | `search.js` |
| **Stale comment**: `main.js` says "Screens 4 and 5 are not built yet". Screen 4 exists. | `main.js:48` |
| **`package.json` is still named `dot-matrix-globe`**, version `1.0.0`. | `package.json` |

### Quality gates

- No tests, no ESLint, no typecheck, no CI. The MVP ships 7 `node:assert` scripts — **keep those on merge**, especially `test-routing.ts` (Suez avoidance, antimeridian, fuel/CO₂ exponents).
- No accessibility pass on the new screens. Keyboard map controls are disabled in `globe.js` with no replacement.

### Performance

- Globe loads up to ~43 MB of raw GeoJSON across 5 LOD levels and never releases them; the flat map adds ~4.5 MB more. Fine on desktop, heavy on mobile.
- Auto-rotation renders continuously and does not honour `prefers-reduced-motion`. The wind overlay does.

### Attribution

- `app.css` hides empty Mapbox control containers on screen 4 and carries the credit as text instead ("Map Mapbox · Land Natural Earth 1:10m"). Keep an equivalent credit visible wherever these maps end up — it's a licence condition for both Mapbox and Natural Earth.
