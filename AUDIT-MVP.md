# AUDIT-MVP.md — "SmoothSail" MVP (ships as `tideline`)

**Audit date:** 2026-10-24 · **Method:** static read-only inspection (`ls`, `cat`, `grep`, `python3` on bundled data). Nothing was installed, built, or run. Every claim below cites a file and line.

> **Headline:** this is a competent, genuinely working **ocean voyage planner and live-map visualiser**. It is *not* a freight booking/compliance/tracking platform. Of the intended feature set, route planning and weather-aware comparison are real; **cost, canal fees, ETS, war-risk/insurance, sanctions, dangerous-goods screening, customs filings, shipment tracking, and change-driven "action required" alerts do not exist in any form** — not stubbed, not mocked, absent. The code is unusually honest about this (the README and in-app notes disclaim almost everything it does not do); the gap is between the *product brief* and the MVP, not between the MVP and its own documentation.

---

## 1. Overview

### 1.1 What it does, from a user's point of view

The app opens on a five-step onboarding wizard ("What brings you to Tideline?") where the user picks a role — **shipper** or **vessel operator** — then enters cargo or vessel details, confirms a departure and arrival port from a dropdown of **34 hardcoded major ports**, a departure date, and a routing priority (`src/components/RoleOnboarding.tsx:27`, `src/lib/onboarding.ts:33-39`). Pressing *Plan my shipment / voyage* computes a shortest sea route with Dijkstra over a bundled 4,109-feature global sea-lane network, then switches to a full-screen MapLibre ocean map showing the chosen corridor, up to two alternatives (a canal-free route and a slow-steaming variant), live AIS vessel positions, animated ocean-current streaks, wave/wind forecast samples, historical AIS density, and global port-activity dots (`src/lib/routing.ts:159-198`, `src/components/OceanMap.tsx:111`). A bottom bar shows **distance (nm), transit estimate, fuel (t), CO₂ (t)**; a "Details" dialog opens a route-comparison table plus a sea-level chart and port-call counts; a "Safety & compliance" dialog runs a five-to-seven-item IMO screening (MARPOL sulphur, ECA exposure, passage planning, routeing, EEXI/CII); a bell icon opens three generic "Voyage advisories"; and the voyage can be saved to `localStorage` or exported as GeoJSON/CSV (`src/components/Dashboard.tsx:278`, `:290`, `:292`, `:235-253`). There is no account, no server, no booking, no shipment that exists after the plan is made.

### 1.2 Stack

| | |
|---|---|
| Language | TypeScript 5.9.3 (`strict: true`, `tsconfig.json:7`), ESM, TSX |
| Framework | **Next.js 16.4.2 / React 19.3.0** App Router (`package.json:28-30`) |
| Rendering mode | **Static export** — `output: 'export'`, `trailingSlash: true` (`next.config.ts:4-5`). No API routes, no server components doing I/O, no SSR. Everything runs in the browser. |
| Map | `maplibre-gl ^6.15.0`, self-hosted style/fonts/worker (`public/fonts/map/`, `public/vendor/maplibre/worker.mjs`) — no map token |
| Icons | `lucide-react ^1.60.0` |
| Realtime | `ws ^8.22.0` (server→AISStream), `mqtt ^5.16.1` (browser→Fintraffic) |
| Styling | 7 hand-written global CSS files, ~449 lines, no CSS modules / Tailwind (`src/app/*.css`) |
| Dev deps | `eslint ^9.39.5`, `eslint-config-next 16.4.2`, `tsx ^4.20.6`, `@types/node ^22`, `@types/react ~19.3.0` |
| Runtime | Node **>= 22.13.0** (`package.json:39`), `.nvmrc` = `22` |
| Tests | 7 plain `node:assert` scripts, no test framework |

**Scripts** (`package.json:5-18`):

```
dev              node scripts/dev.mjs          # Next dev (0.0.0.0:3000) + AIS gateway (127.0.0.1:3001) together
dev:ui           next dev --hostname 0.0.0.0   # UI only
build            next build                    # static export -> out/
start            node scripts/dev.mjs --production  # serves out/ + gateway
ais:gateway      node --env-file-if-exists=.env.local server/ais-gateway.mjs
lint             eslint src scripts server
typecheck        tsc --noEmit
test:routing | test:motion | test:ais | test:compliance | test:vessels | test:onboarding
```

**How to run** (per `README.md:7-13`, not executed): `nvm use` → `npm install` → `npm run dev` → http://localhost:3000. `npm start` requires a prior `npm run build`: `scripts/serve.mjs:7` throws `'Run npm run build before starting the production server.'` if `out/index.html` is missing, and **`out/` does not currently exist** in this folder. `node_modules/` **is** present (324 entries), `.next/dev` exists from a dev run on 23 Oct.

### 1.3 File tree (excluding `node_modules`, `.next`)

```
AGENTS.md                              Agent instructions — mostly STALE Expo content (see §5.8)
README.md                              94 lines; architecture + data-provenance contract. Accurate (see §4)
LICENSE                                MIT
package.json / package-lock.json       deps + scripts
next.config.ts                         static export, unoptimized images, turbopack root
tsconfig.json                          strict, paths @/* -> ./src/*
eslint.config.mjs                      next core-web-vitals + typescript
.nvmrc                                 22
.env.example                           documented env template
.env.local                             *** CONTAINS A LIVE 40-CHAR AISSTREAM API KEY *** (§5.1)
.gitignore                             ignores .env*.local (contradicts README:60)
next-env.d.ts                          generated

src/app/
  layout.tsx                 20   root html/body, metadata, imports all 7 stylesheets
  page.tsx                    5   renders <Dashboard/>; the app's ONLY route
  globals.css                34   app shell, topbar, map chrome (very long minified-style lines)
  clarity.css               215   vessel cards, dialogs, typography
  compliance.css             67   compliance dialog
  ocean-overlays.css         88   layer panel, legends, flow controls
  workspace.css              23   setup vs "tracking" (= map) screen
  onboarding.css             22   role wizard

src/components/
  Dashboard.tsx             296   GOD COMPONENT: 30+ useState, all screen/modal state, plan orchestration,
                                  save/export, all 7 dialogs inline
  RoleOnboarding.tsx        111   5-step shipper/operator wizard
  JourneySetup.tsx           54   legacy single-page form + exported <JourneyPorts> (shared port controls)
  PortPicker.tsx             34   searchable dropdown over the 34 hardcoded ports
  OceanMap.tsx              344   MapLibre owner: style, 7 GeoJSON sources, layer visibility, AIS popups
  OceanFlow.tsx             143   canvas particle animation of ocean currents (30/60 fps, geographic trails)
  VoyagePreview.tsx          80   animated "YOUR VOYAGE" marker along the planned route (explicitly labelled preview)
  RouteChooser.tsx           12   route dropdown: name, nm, duration, CO2
  ComplianceDialog.tsx       17   renders screenCompliance() output + 2 numeric inputs
  GlobalAisDialog.tsx        12   AIS gateway setup instructions / status
  Dialog.tsx                 17   <dialog> wrapper, showModal + backdrop close
  OceanColourControl.tsx     14   streak colour-scale selector

src/lib/
  routing.ts                198   Dijkstra + min-heap, graph cache, canal blocking, wave penalty, fuel/CO2 model
  types.ts                   86   Port, VoyageInput, RouteOption, MarinePoint, LayerState, SavedVoyage
  compliance.ts              67   IMO screening (ECA by hardcoded port id), 5-7 checks, source links
  onboarding.ts             123   role models, validation, -> VoyageInput transform, assumption strings
  ocean-data.ts             125   DATA_SOURCES registry, Open-Meteo marine/wind fetch, PortWatch queries
  ocean-field.ts            112   global 15-deg current grid, land mask (ray casting), IDW vector interpolation
  ocean-colours.ts           50   fixed physical colour scales (sea level/wave/temp/current)
  live-vessel-animator.ts    89   tweens AIS reports, incremental GeoJSON diffs, selected-vessel trail
  vessel-motion.ts           36   great-circle interpolation, heading wrap, route playback track
  vessel-popup.ts            45   AIS ship-type decoding + popup HTML
  map-lifecycle.ts           10   readyMap() guard against Fast-Refresh stale map writes
  format.ts                   5   number/duration/date/time helpers

src/hooks/
  useGlobalVessels.ts        79   SSE from local gateway, /status probe, 30-min expiry, visibility pause
  useLiveVessels.ts          92   Fintraffic MQTT over wss + 30 s REST snapshot fallback (Baltic only)
  usePortActivity.ts         41   daily PortWatch calls for origin/destination + global traffic join
  useOceanField.ts           26   current-field lifecycle, 20-min refresh

src/data/ports.ts            47   *** 34 hardcoded ports *** + PASSAGE_NAMES map (13 named passages)

server/
  ais-gateway.mjs           113   Node HTTP+SSE gateway; one shared compressed AISStream WS; origin allowlist;
                                  50k-entry caches; 2 s batching; exponential reconnect; /status + /events
  ais-normalize.mjs          57   AIS message validation/normalisation (position + static/voyage data)

scripts/
  dev.mjs                    11   spawns gateway + next, forwards signals
  serve.mjs                  27   static file server for out/ with path-traversal guard
  refresh-open-data.mjs      19   re-downloads IMF PortWatch port locations -> public/data
  configure-ais-key.mjs      20   writes AISSTREAM_API_KEY from hidden stdin, chmod 600
  generate-onboarding-map.mjs 15  renders onboarding-world.svg from countries.geojson
  test-routing.ts            34   connectivity, Suez avoidance, antimeridian, fuel/CO2 model  [npm script]
  test-compliance.ts         39   ECA triggers, dates, no-false-certification, colour scales  [npm script]
  test-onboarding.ts         58   validation, role transforms, unit handling                  [npm script]
  test-vessels.ts            28   animator trails/selection                                   [npm script]
  test-motion.ts             25   interpolation bounds, land mask, current vectors            [npm script]
  test-ais.mjs               25   AIS normalisation edge cases                                [npm script]
  test-map-lifecycle.ts      36   readyMap guard  *** NO npm script — orphaned (§5.6) ***

public/data/
  maritime-network.geojson   746 KB  4,109 features / 9,681 unique nodes / 15,936 segments (searoute-py)
  countries.geojson          839 KB  Natural Earth land (basemap + land mask)
  portwatch-ports.geojson    389 KB  1,380 IMF PortWatch ports — DISPLAY ONLY, never routed to (§5.3)
  onboarding-world.svg       133 KB  generated flat world backdrop
  reference-metadata.json    197 B   portwatchRetrievedAt 2026-10-20, portCount 1380
  MARITIME-NETWORK-LICENSE   11 KB
public/fonts/, public/vendor/maplibre/, public/icon.svg   self-hosted assets + licences
assets/                      6 PNGs — LEFTOVER EXPO APP ICONS, unreferenced by this app (§5.8)
research/flightradar24/      findings.json (115 L) + visible-motion-measurements.json (596 L) — UI/motion
                             reference investigation; documentation only, not imported by any source file
```

### 1.4 Git

**There is no repository.** `git status` in the project root returns `fatal: not a git repository (or any of the parent directories): .git`, and no `.git` directory exists anywhere in the tree. **Zero commits, zero branches, no history, no blame, no remote.** This was delivered as a plain folder (likely an unzipped archive).

The only chronology available is filesystem mtimes: all source and data files are stamped `22 Oct 12:41` (a single extraction timestamp, so authoring order is unrecoverable), `.next/` is `23 Oct 17:06` (last dev run), `package-lock.json` is `24 Oct 12:38`. Internal date evidence: `src/lib/compliance.ts:3` pins `RULES_VERIFIED_ON = '2026-10-20'` and `public/data/reference-metadata.json` records a PortWatch fetch at `2026-10-20T19:55Z`.

**Merge implication:** there is no branch to merge and no history to preserve. Before any integration work, `git init` and commit this tree as a baseline, then rotate the leaked key (§5.1) — note that `.gitignore:37` already excludes `.env*.local`, so the key will not follow it into git.

---

## 2. Feature inventory

### 2.1 Planning core

| Feature | Status | Files | Notes |
|---|---|---|---|
| Port selection / search | **working** (narrow) | `src/components/PortPicker.tsx:13,26-31`, `src/data/ports.ts:4-39` | Substring match over `name + country + code`; Enter selects first hit, Escape closes, click-outside closes, `role="listbox"`/`aria-selected` present. Footer literally says *"34 major ports · worldwide coverage"*. |
| Port dataset | **partial** | `src/data/ports.ts:4-39`; `public/data/portwatch-ports.geojson` | **Only 34 hardcoded ports are routable**, each with id/name/country/UN-LOCODE/approach coordinate. A 1,380-port IMF PortWatch dataset ships alongside but is used *only* for map dots and port-call counts (`src/lib/ocean-data.ts:101-124`) — it is never offered as a routing endpoint. No geocoding, no inland origin→port leg (the wizard collects origin city/country as free text and discards it, `src/lib/onboarding.ts:10`). |
| Route generation | **working** | `src/lib/routing.ts:15-146` | Builds an undirected graph from the GeoJSON (nodes keyed to 5 dp, longitudes normalised so the antimeridian joins), caches it in a `WeakMap`, then runs **Dijkstra with a hand-written binary min-heap** (`:49-78`). Origin/destination snap to the nearest *connected* node by linear scan (`:82-90`). Arctic passages (`northwest`, `bering`) are always blocked (`:97`). Verified: 9,681 nodes, 15,936 segments. |
| Sea-lane graph | **working** (real data) | `public/data/maritime-network.geojson`, licence file alongside | Eurostat / `searoute-py` open network, 4,109 features. **Only 24 features carry a `passage` tag** — `south_africa`×5, `northwest`×4, `bering`×3, `chili`×3, and exactly **one each** for `suez`, `panama`, `gibraltar`, `malacca`, `babalmandab`, `ormuz`, `bosporus`, `dardanelles`, `sunda`. See §5.2 — this single-segment tagging is load-bearing for canal avoidance, route naming, and ECA screening. |
| Waypoints / geometry | **working** | `src/lib/routing.ts:124-145` | Path reconstructed from predecessors, then **longitude-unwrapped** so dateline routes do not draw a line across the world (asserted in `scripts/test-routing.ts:27`). Comment at `:134` is explicit that endpoints stay on the network because straight connectors could cross land. |
| Distance calculation | **working** | `src/lib/routing.ts:3-9,144` | Haversine, R = 3440.065 nm. Reported distance is recomputed from the **true geometry**, not from the weather-penalised Dijkstra cost — so penalties steer the route without corrupting the number. |
| Port→network truncation | **honest, small** | `src/lib/routing.ts:82-90` | Measured from the shipped data: mean snap distance **6.1 nm**, worst **18.2 nm** (Jebel Ali), then Buenos Aires 15.9, Valparaíso 15.1, Hong Kong 14.6; Hamburg 0.0. So each voyage omits ≈12 nm of approach — negligible against 7,000–10,000 nm legs, and disclaimed ("excluding berth approaches", `README.md:88`). |

### 2.2 Route comparison metrics

| Metric | Status | Files | Notes |
|---|---|---|---|
| Distance | **working** | `src/lib/routing.ts:144`; shown `src/components/Dashboard.tsx:278,290` | Network nautical miles. |
| ETA / transit | **partial** | `src/lib/routing.ts:166` | `durationHours = distanceNm / speed`. Pure sea time — **no canal transit time, no waiting, no berth, no port stay**, stated in the methodology note (`Dashboard.tsx:290`). There is no arrival *timestamp* in the UI: only a `Xd Yh` duration (`src/lib/format.ts:2`). Departure date is used solely to pick forecast hours (`routing.ts:170-176`). |
| Fuel | **working (model)** | `src/lib/routing.ts:164,167` | Cubic speed law: `days × base × (speed/18)³`, base = 58 / 32 / 45 t/day for container / bulk / tanker. Whole-vessel, not per-container. Disclosed in-app and in `README.md:88`; the exponent is asserted in `scripts/test-routing.ts:20`. |
| CO₂ | **working (model)** | `src/lib/routing.ts:181` | `fuel × 3.114` tank-to-wake. Tonnes only. |
| **ETS / carbon cost** | **MISSING** | — | No EU ETS, no FuelEU, no carbon price, no allowance count anywhere. `grep -i` for `ETS`, `price`, `cost`, `USD`, `EUR`, `tariff` across `src/`, `server/`, `scripts/` returns **no monetary value of any kind**. |
| **Monetary cost** | **MISSING** | `src/lib/onboarding.ts:112` | The shipper priority *"Lowest estimated operating cost"* is silently mapped to `priority: 'eco'`, i.e. the slow-steaming option — **a fuel proxy with no currency**. `README.md:19` and the UI (`Dashboard.tsx:278`: *"Indicative route · no freight quote"*) admit this. No freight rate, bunker price, charter cost, or demurrage. |
| **Canal fees** | **MISSING** | — | Explicitly excluded in the methodology note (`Dashboard.tsx:290`) and `README.md:88`. Suez/Panama are pure topology decisions. |
| **War risk / insurance** | **MISSING** | `src/components/ComplianceDialog.tsx:15` | No risk zone geometry, no premium model, no JWC listed areas. The compliance dialog explicitly defers *"cargo, insurance, sanctions, real-time security"* to separate review. The one Red Sea mention is a static advisory card with a "Compare the Cape route" button (`Dashboard.tsx:292`) — it is triggered by `passages.includes('suez')`, not by any security feed. |
| Weather | **working (sampled)** | `src/lib/ocean-data.ts:42-88`; `src/lib/routing.ts:99-105,171-184` | Real Open-Meteo/Copernicus marine + wind. Up to 8 samples per route (`sampleRoute`, `routing.ts:148`) plus a 22-point global grid (`ocean-data.ts:15-20`). **Routing penalty:** nodes within 350 nm of a sample with wave > 2 m get a cost multiplier of `(wave-2)×0.22`, applied **only** when `priority === 'balanced'` (`routing.ts:104,163`). Comparison exposes `maxWave`, `meanWind`, and a `weatherCoverage of forecastSamples` honesty counter. Missing values stay `null` — asserted in `scripts/test-routing.ts:17`. |
| Alternative routes | **working** (max 3) | `src/lib/routing.ts:188-197` | (1) shortest corridor, named from traversed passage tags; (2) a canal-avoiding alternative, **only if** the primary used Suez or Panama *and* the detour is > 50 nm longer; (3) slow steaming at `0.85 × speed` (same geometry). Not a general k-shortest-paths search — a Pacific or Atlantic crossing yields just 2 options. |
| Priority modes | **partial** | `src/components/JourneySetup.tsx:35-39`; `src/lib/routing.ts:163,195` | `balanced` = weather-penalised; `fastest` = shortest, weather ignored; `eco` = selects slow steaming. **`balanced` and `fastest` return identical geometry whenever forecasts are unavailable or seas are below 2 m** — the only difference between them is the penalty. |
| Comparison table | **working** | `src/components/Dashboard.tsx:290` | Rows: distance, transit, speed, fuel, CO₂, max sampled wave, forecast coverage, named passages. Plus a 48-h sea-level sparkline at the destination approach and PortWatch cargo-call counts for both ports. |

### 2.3 Pre-booking compliance

| Check | Status | Files | Notes |
|---|---|---|---|
| MARPOL fuel sulphur | **working (screening)** | `src/lib/compliance.ts:31-38` | Limit 0.10 % inside a detected ECA else 0.50 %; compares the user's declared `sulphurPercent` and flags `attention` when over. An "equivalent system" checkbox downgrades to `review` rather than passing (`:36`) — a deliberately conservative choice, asserted in `scripts/test-compliance.ts:23-24`. |
| ECA detection | **partial / weak** | `src/lib/compliance.ts:16-30` | **Membership of three hardcoded port-id sets** — North Sea `{rotterdam, hamburg, antwerp, felixstowe}`, North America `{new-york, los-angeles, houston, vancouver}`, Mediterranean `{marseille, piraeus, istanbul}` — plus one corridor rule (`gibraltar` ∧ `suez`) and a latitude ≥ 62° check for the 2027 Norwegian Sea designation. **No polygon intersection.** Any route between two untagged ports reports "no ECA trigger" and silently uses the 0.50 % limit. The code comment at `:16` and the UI note at `ComplianceDialog.tsx:15` both say so plainly. |
| SOLAS passage planning | **working (informational)** | `src/lib/compliance.ts:43-47` | Always a `review` item stating the app does not produce a berth-to-berth plan. |
| Routeing / COLREG | **working (informational)** | `src/lib/compliance.ts:47-51` | Always `review`; counts named passages used. |
| EEXI / CII documentation | **working (informational)** | `src/lib/compliance.ts:51-55` | Branches on declared gross tonnage against the 5,000 GT threshold. Explicitly not an attained rating. |
| Forecast-window check | **working** | `src/lib/compliance.ts:56-60` | Added when the voyage exceeds 7 days or coverage is partial. |
| Upcoming northern ECA | **working** | `src/lib/compliance.ts:61-65` | Date-sensitive MEPC.392(82) note for departures before 2027-03-01. |
| **Sanctions screening** | **MISSING** | — | No OFAC/EU/UN list, no vessel/owner/flag/cargo check, no screening API. Deferred in text only (`ComplianceDialog.tsx:15`). |
| **Dangerous goods** | **UI-only** | `src/components/RoleOnboarding.tsx:81`, `src/lib/onboarding.ts:17,31` | A free-text *"IMDG class or UN number (if known)"* field appears when cargo is hazardous. The value is **never validated, classified, screened, segregated, or used** — it is stored on the draft, echoed in the review step, and exported. No IMDG table exists in the repo. |
| **Customs filings** | **MISSING** | — | No ENS/AMS/ISF/entry summary, no document generation, no HS codes, no commercial invoice/packing list. The wizard collects a goods *category* from an 11-item list (`src/lib/onboarding.ts:4`) and nothing downstream consumes it except the vessel-model guess. |
| Compliance freshness | **manual** | `src/lib/compliance.ts:3` | `RULES_VERIFIED_ON = '2026-10-20'` is a hardcoded string shown as *"Rules reviewed …"*. Nothing re-verifies it; it will silently go stale. |

### 2.4 Tracking and alerts

| Feature | Status | Files | Notes |
|---|---|---|---|
| **Shipment tracking** | **MISSING** | `src/app/workspace.css:1,12-13` | There is **no shipment entity, no identifier, no status, no milestones, no carrier/booking link, no history**. The CSS class names `.tracking-screen`, `.tracking-voyage-bar`, `.tracking-tools` are *the map screen* — naming only. The closest thing is `VoyagePreview.tsx`, an animated marker that sweeps the planned route on a 120-second loop (`:47`), explicitly labelled *"PLANNED POSITION · PREVIEW"* (`:29`) and deliberately decoupled from real AIS. |
| Live AIS vessel positions (global) | **working** | `server/ais-gateway.mjs:28-71`, `src/hooks/useGlobalVessels.ts` | Real AISStream feed. Gateway holds **one** compressed upstream WebSocket shared by up to 25 SSE clients (`:98`), batches every 2 s (`:73`), expires positions after 30 min, bounds caches at 50k entries, reconnects with capped exponential backoff + jitter (`:68`), closes upstream 30 s after the last client leaves (`:107`). Browser side re-validates MMSI, geometry, and timestamp window before trusting a report (`useGlobalVessels.ts:35`). |
| Live AIS (regional fallback) | **working** | `src/hooks/useLiveVessels.ts:53-88` | Fintraffic Digitraffic MQTT over `wss` for Finnish/Baltic waters, with a 30 s REST snapshot fallback and explicit `streaming`/`polling`/`offline` states. Used when no global key is configured. |
| AIS rendering / interaction | **working** | `src/lib/live-vessel-animator.ts`, `src/lib/vessel-popup.ts`, `src/components/OceanMap.tsx:279-300` | Oriented silhouettes, incremental GeoJSON diffs instead of full-source rebuilds, hover/click popups with broadcast particulars, and a trail **only** for the selected vessel containing **only received positions** (`scripts/test-vessels.ts:24`). Interpolation is clamped so a vessel is **never extrapolated past its last report** (`src/lib/vessel-motion.ts:5`, asserted `scripts/test-motion.ts:7`). This is the most rigorous part of the codebase. |
| **"Action required" alerts on change** | **MISSING** | `src/components/Dashboard.tsx:292` | The bell opens *"Voyage advisories"*: (1) the highest currently-sampled wave on the corridor, (2) a static Red Sea note if the route uses Suez, (3) a static "forecasts have a horizon" note. **There is no change detection, no previous-state comparison, no event log, no push/email/webhook, no unread state.** The red dot on the bell is simply `highestWave >= 3`. The phrase "ACTION REQUIRED" exists once, as a badge for a compliance check whose status is `attention` (`ComplianceDialog.tsx:14`) — i.e. "your declared fuel exceeds the screened limit", computed synchronously from form inputs. |
| Forecast refresh | **working** | `src/components/Dashboard.tsx:216-232` | 10-min interval (1-min on failure), refresh on return to a stale tab, routes recomputed with new weather. Does not reset map exploration. |
| Port activity | **working** | `src/lib/ocean-data.ts:101-124`, `src/hooks/usePortActivity.ts` | Real IMF PortWatch ArcGIS queries: latest published daily cargo port calls for both ports, plus a paged global join (4×1,000 records) to colour the port layer. Labelled "activity, not congestion". |

### 2.5 Platform / supporting

| Feature | Status | Files | Notes |
|---|---|---|---|
| Role-based onboarding | **working** | `src/components/RoleOnboarding.tsx`, `src/lib/onboarding.ts:42-108` | 5 steps, per-role drafts preserved for the session, errors routed back to the owning step (`errorStep`, `:99`), thorough validation (finite numbers, real calendar dates, unit-compatible capacity vs load, conditional temperature and container fields, explicit performance model required for unsupported vessel classes). 58-line test. |
| Save / restore voyages | **working** (local) | `src/components/Dashboard.tsx:235-243` | `localStorage` key `tideline-voyages-v1`, shape-validated on load, past departures advanced to today on reopen, quota failures surfaced as a toast. Browser-only; no sync, no sharing. |
| Export | **working** | `src/components/Dashboard.tsx:245-253` | GeoJSON route (with onboarding metadata, assumptions, compliance result, and a `"Planning estimate. Not for navigation."` status) and a CSV voyage brief. |
| Ocean current animation | **working** | `src/lib/ocean-field.ts`, `src/components/OceanFlow.tsx` | Real global 15° grid between ±67.5° lat (`ocean-field.ts:44`), land-masked by ray casting against Natural Earth, IDW vector interpolation over ≤4 nearest samples (`:91-112`), geographic particle trails that survive zoom/pan, 30→60 fps during camera motion, honours `prefers-reduced-motion`. No currents above 67.5°. |
| Historical AIS density | **working** | `src/components/OceanMap.tsx:75,89` | EMODnet WMS raster, European waters, 2023, off by default. |
| Data-sources panel | **working** | `src/lib/ocean-data.ts:3-13`, `Dashboard.tsx:288` | Nine provider cards with coverage, licence, and limitation text. |
| Accessibility | **good** | throughout | `aria-label`/`aria-expanded`/`aria-pressed`/`role="switch"`/`aria-invalid`+`aria-describedby` on form errors, `sr-only` legends, focus moved to the step heading (`RoleOnboarding.tsx:30`), native `<dialog>` with Escape handling, reduced-motion respected in both animators. |
| Responsiveness | **partial** | `src/app/globals.css:17`, `onboarding.css:15,22`, `workspace.css` | Media queries at 540/600/800 px adjust the shell, hide the brand tag, and drop a metric column. Layout is desktop-first with `height: 100dvh; min-height: 650px` and absolutely-positioned map furniture — a phone-width pass is likely still needed. |
| Auth / backend / DB / multi-user | **MISSING** | `next.config.ts:4` | Static export. No accounts, no server state, no API routes, no persistence beyond `localStorage`. |
| Multi-leg / transshipment / rates | **MISSING** | — | Single origin→destination ocean leg only. |

---

## 3. Verification status of the test suite

Six of the seven scripts are wired to npm and are meaningful assertion tests, not smoke tests — `test-routing.ts` checks global connectivity across six port pairs, Suez+Red Sea co-avoidance, antimeridian handling, and the exact fuel/CO₂ exponents; `test-compliance.ts` checks ECA triggers, effective dates, and that a numeric fuel match never certifies a voyage; `test-ais.mjs` checks malformed/stale/future reports and the 102.3 "unavailable speed" sentinel. **I did not run them** (read-only audit), so these are reviewed-as-written, not verified-as-passing. `scripts/test-map-lifecycle.ts` is **orphaned**: no npm script, and absent from the README's check list.

---

## 4. Claims vs. reality

The README is unusually trustworthy — I found no fabricated capability. Everything it asserts about data provenance, the 18-knot/58-32-45 t-day fuel model, the ×3.114 CO₂ factor, Arctic exclusion, no-extrapolation AIS, and the incompleteness of ECA screening is borne out in code. Discrepancies are minor:

1. **`README.md:60`** — *"This owner-private repository includes the configured `.env.local` at the owner's request."* There is no repository, and **`.gitignore:37` excludes `.env*.local`**, so the file could never have been committed. The live key is here because the folder was copied/zipped, not because git carried it. (§5.1)
2. **`src/lib/ocean-data.ts:10`** — network described as *"4,109 sea-lane segments"*. 4,109 is the **feature** count; the actual segment count is **15,936**.
3. **`README.md:35`** — *"1,380 mapped ports"* is true of the PortWatch activity layer, but a reader may take it as routing coverage, which is **34**. The in-app footer (`PortPicker.tsx:31`) is the honest number.
4. **`README.md:11`** — *"`npm run build` creates a static production export in `out/`"* is correct, but `npm start` fails until that build exists, and `out/` is absent from the delivery.
5. **`AGENTS.md`** — the majority of the file is Expo/EAS/React Native guidance that does not apply; it self-labels the block as legacy, and the Next.js block at the end warns that the installed Next.js differs from training data. (§5.8)

---

## 5. Risks and defects, by priority

### 5.1 BLOCKER — a live API key is sitting in the delivered folder
`.env.local:2` contains a **real 40-character `AISSTREAM_API_KEY`**. The folder has no `.git`, so this travelled as a plain file. The architecture around it is actually good — the key is read only server-side (`server/ais-gateway.mjs:5`), never prefixed `NEXT_PUBLIC_`, never logged (`:61`), and `scripts/configure-ais-key.mjs` writes it from hidden stdin with mode `0600` — but none of that helps once the file is distributed. **Treat the key as compromised: rotate it at AISStream, then re-provision via `scripts/configure-ais-key.mjs` and confirm `.env.local` is never added to the new repo.** (I have not printed, copied, or transmitted the value.)

### 5.2 HIGH — canal avoidance, route naming, and ECA screening all hang on 24 tagged segments
Exactly **one** feature in the 4,109-feature network is tagged `suez`, one `panama`, one `gibraltar`, one `malacca`. Consequences:
- `avoidSuez` works only because that single segment is the chokepoint (`src/lib/routing.ts:162,191`); any future network refresh that re-tags or splits it silently breaks canal avoidance, and the existing test (`test-routing.ts:15`) would catch it only for Rotterdam→Singapore.
- Route names are derived from traversed tags (`routing.ts:187`), so most ocean routes fall through to the generic *"Direct ocean passage"*.
- The "Ocean passages" comparison row is therefore sparse by construction, not because the route is open ocean.
- The Mediterranean ECA trigger depends on traversing **both** the `gibraltar` and `suez` segments (`src/lib/compliance.ts:26`) — a Gibraltar-only Mediterranean call (e.g. Algeciras→Piraeus) will not trigger it unless an origin/destination id happens to be in the hardcoded set.

### 5.3 HIGH — 34 routable ports is the central functional limit
For a product framed as "port A to port B", the planner accepts 34 destinations while a 1,380-port dataset with coordinates and LOCODEs sits unused in `public/data/portwatch-ports.geojson`. Promoting it is the single highest-leverage change, but it is not free: each port needs a *sea-side approach* coordinate that snaps to a connected network node, and `src/lib/compliance.ts:17-19` keys ECA detection off `Port.id` string literals, so it would need re-basing on geography (polygons or at least country/region) rather than ids.

### 5.4 MEDIUM — all routing is main-thread, recomputed more than necessary
`planRoutes` → `shortestPath` runs a full Dijkstra over 9,681 nodes **twice** per plan (once immediately, once after forecasts arrive, `Dashboard.tsx:54,61`), again on every 10-minute refresh (`:124`), and again whenever an advisory button re-plans. Within each call, `nearest()` is a **linear scan over all 9,681 nodes** run twice (`routing.ts:82-90`), and the wave-penalty pass is `O(nodes × samples)` ≈ 370k haversines (`:99-105`). There is no Web Worker, no spatial index, and no `AbortSignal` honoured inside the solver. Add the 746 KB + 839 KB GeoJSON downloads before first plan (`Dashboard.tsx:198`) and this will be the dominant cost on a mid-range phone.

### 5.5 MEDIUM — refresh effect churns
The forecast-refresh effect at `src/components/Dashboard.tsx:216-232` lists `routes`, `updated`, and `dataState` in its dependency array *and* sets all three inside `refresh()`. Every successful refresh therefore tears down and recreates the interval and `AbortController`. Behaviour stays roughly correct (the cadence just restarts), but it is fragile — any future early-return or shorter interval could turn it into a refresh loop.

### 5.6 LOW — `scripts/test-map-lifecycle.ts` is orphaned
36 lines of real assertions guarding a genuine Fast-Refresh hazard (`src/lib/map-lifecycle.ts:5-9`), with no npm script and no mention in the README check list. Add `"test:map": "tsx scripts/test-map-lifecycle.ts"`.

### 5.7 LOW — `Dashboard.tsx` is a 296-line god component
30+ `useState` hooks, all seven dialogs inlined as JSX, plan orchestration, persistence, and export in one file, with lines running past 1,000 characters. It works, but it is the hardest file to merge into a new front end and the most likely source of regressions.

### 5.8 LOW — Expo residue
`AGENTS.md` is still mostly Expo/EAS instructions (it flags itself as legacy, but an agent or new contributor will read it), and `assets/` holds six Expo app-icon PNGs (`icon.png`, `splash-icon.png`, `android-icon-*.png`) referenced by nothing in `src/` or `public/`. Both should be deleted during the merge.

### 5.9 Note — things that are *correctly* conservative
Worth preserving verbatim during the merge, because they are easy to lose: missing observations stay `null` and are rendered as `—`/"Unavailable" rather than zero (`ocean-data.ts:70`, `routing.ts:182`); AIS never extrapolates (`vessel-motion.ts:5`); the AIS speed sentinel 102.3 becomes `null`, not a measurement (`ais-normalize.mjs:23`); a missing provider timestamp is labelled `gateway-receipt` instead of being passed off as source time (`:28`); the voyage preview is loudly separated from real vessels (`VoyagePreview.tsx:22,29`); and the compliance report refuses to certify anything (`compliance.ts:38,42`).

---

## 6. Merging this into the new dot-matrix-globe front end

**Take as-is (framework-free, no map dependency):**
`src/lib/routing.ts` · `src/lib/types.ts` · `src/data/ports.ts` · `src/lib/compliance.ts` · `src/lib/onboarding.ts` · `src/lib/format.ts` · `src/lib/vessel-motion.ts` · `src/lib/ocean-colours.ts` · `src/lib/ocean-data.ts` (pure fetchers + `DATA_SOURCES`) · `src/lib/ocean-field.ts` · `server/` (both files) · `public/data/` · all `scripts/test-*`.
The single integration point is tiny: `planRoutes(network: MaritimeNetwork, input: VoyageInput, marine?: MarinePoint[]): RouteOption[]`.

**Your globe's From / To / Date map directly onto `VoyageInput`** (`src/lib/types.ts:21-30`): `origin`/`destination` are full `Port` objects (not ids — look them up in `PORTS`), `departure` is `YYYY-MM-DD`. The remaining three fields need defaults, which `Dashboard.tsx:32` already supplies: `speed: 18`, `vessel: 'container'`, `priority: 'balanced'`, `avoidSuez/avoidPanama: false`. `JourneySetup.tsx:52` (`JourneyPorts`) is the reusable From/To control if you want it; `PortPicker.tsx` is the searchable dropdown.

**Expect to rewrite, not port:**
`OceanMap.tsx` (344 L), `OceanFlow.tsx`, `VoyagePreview.tsx`, and `live-vessel-animator.ts` are hard-bound to MapLibre and to seven specific named GeoJSON sources (`src/lib/map-lifecycle.ts:3`). A dot-matrix globe is a different renderer — the *data* flowing into these (route coordinates, AIS feature collections, current vectors) is reusable; the drawing code is not. `Dashboard.tsx` should be decomposed rather than lifted. The seven global CSS files use generic class names (`.tracking-screen`, `.toggle`, `.dialog`) that **will collide** with a redesigned front end.

**Architectural decision you cannot defer:** the MVP is `output: 'export'` (`next.config.ts:4`) — zero server. Routing happens in the browser after downloading 1.6 MB of GeoJSON, and worldwide AIS requires a *separately hosted* long-lived SSE/WebSocket gateway with `NEXT_PUBLIC_AIS_GATEWAY_URL` baked in at build time (`src/hooks/useGlobalVessels.ts:23`). If the new front end expects API routes (likely, for real cost/sanctions/tracking data), you are dropping `output: 'export'` and should move `planRoutes` server-side at the same time — which also fixes §5.4.

**Honest scoping for the merged product.** Merging this MVP gets you: route generation, distance, transit time, fuel, CO₂, weather-aware comparison, IMO safety screening, live AIS, and export. It gets you **none** of: cost/rates, canal fees, ETS, war-risk/insurance, sanctions, dangerous-goods validation, customs filings, shipment tracking, or change alerts. Those are new builds requiring data sources this repo does not have — and each one needs a commercial or regulatory feed, not just UI.
