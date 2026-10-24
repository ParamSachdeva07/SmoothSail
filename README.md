# SmoothSail

A dot-matrix globe and maritime route planner. Enter two supported ports and a departure date, compare **Fastest**, **Cheapest**, and **Lowest CO₂**, then open a route on the map.

The frontend uses vanilla JavaScript, Vite and Mapbox GL. The Python routing service, MongoDB integrations and Cloudflare deployment live in [`route-planning-api/`](route-planning-api/README.md).

## Run the frontend

Use Node.js 22+:

```sh
npm ci
cp .env.example .env.local   # fresh checkout only; preserve existing local settings
# Set VITE_MAPBOX_ACCESS_TOKEN to a Mapbox public token.
npm run dev -- --port 3200
```

Open http://localhost:3200. Scroll or click “Plan a shipment” to begin.

The public API defaults to **https://tideline-api.paramsachdeva81.workers.dev**. To use another backend, set `VITE_ROUTE_API_BASE_URL` in `.env.local` and restart Vite. `VITE_*` values are public browser configuration. MongoDB credentials, Copernicus credentials and internal tokens must only be configured on the backend.

```sh
npm test
npm run build
npm run preview
```

Build output is `dist/`. The Mapbox bundle is about 1.9 MB before compression; Vite reports a bundle-size warning. Static land-dot assets are larger and load progressively as the globe is zoomed.

## Request and rendering flow

1. `src/api/client.js` fetches `GET /ports?limit=50`. The deployed service currently returns ten supported ports. The frontend caches this catalogue in memory; it does not advertise unsupported demo ports.
2. The form validates selected ports, prevents identical endpoints and checks the departure date. Today omits `departureTime` so the API uses the current time; a future date uses midnight UTC.
3. A single `POST /routes` returns all available objectives:

   ```json
   { "origin": "NLRTM", "destination": "SGSIN" }
   ```

4. While calculating, the UI displays actual elapsed time. There is no fake percentage, delayed animation, polling or browser-side routing calculation. Cancel aborts the browser request and prevents a late result from replacing another search; work already running on the server may finish.
5. `src/data/routes.js` keeps the **complete report** in memory, including segments, sources, vessel assumptions, forecast coverage and compliance metadata. Its view adapter adds labels but does not recalculate fuel, cost, CO₂ or ETA. Refreshing the page clears the report; no voyage history is persisted.
6. The comparison cards show `durationHours`, `distanceNm`, the API's `eta`, `cost.totalUsd`, `cost.fuelTonnes` and `emissions.co2Tonnes`. Cost is USD for the **entire vessel voyage**, not per day or per container. “Lowest CO₂” refers to estimated tank-to-wake emissions, not every environmental impact.
7. Both **View route** and **Select this route** open the chosen API ID on the map. The renderer uses `geometry` directly, preserving every waypoint and `MultiLineString` date-line split. It adds no smoothing curve or fabricated stops. A separate, explicitly simulated ship follows the API’s timed segments without changing the route geometry. A route crossing the date line appears at both edges of the flat world map, with no line connecting across the world.

The selected-route map uses [Mapbox Light](https://www.mapbox.com/maps/light), with pale water, fine coastlines, a pink selected route and yellow alternatives. Place names, roads, buildings and points of interest are hidden to keep the maritime view minimal; boundary lines remain visible. Its Mercator projection matches the forecast raster so weather colours stay aligned with coastlines. The zoom-out limit adapts to the viewport, and world bounds prevent panning beyond the map; zooming in stops at level 8. The landing globe retains its original dots. Wave colours sit above water and below the basemap labels and route. Alternatives can overlap because different objectives may select the same geography and speed. Endpoint markers use the API's offshore approach coordinates, which are not berth locations.

**Info** on the cards and **More info** on the map remain disabled placeholders. The map includes an automatically playing voyage preview (90 seconds for the whole voyage), play/pause, restart and a scrubber. The ship follows every timed segment and stops during assumed canal waits. It is a simulated position, not live AIS. Playback pauses when the map or browser tab is hidden and respects reduced-motion preferences.

The **Wave forecast** switch shows the API’s global significant-wave-height grid at the selected voyage time, including oceans away from the route. The grid has 721 × 257 samples over the available forecast latitude range. A worker prepares one small, premultiplied RGBA texture per forecast frame; a Mapbox custom WebGL layer uploads each texture once and blends adjacent frames on the GPU. Zooming and playback no longer redraw or upload large canvases. Only five frames are retained, upcoming frames are prefetched, and rapid scrubbing prioritises the latest selection instead of building a queue of old work. Hidden overlays stop requesting textures.

The display uses a bounded Gaussian colour blur and GPU linear filtering, with a separate GSHHG coastline mask keeping land white. A faint visual halo can extend up to three grid cells beyond samples, but it does not create numeric coverage or additional forecast precision. Large missing areas stay transparent. Blue/sea-glass through sand/rose represents increasing significant wave height in metres. If the voyage playhead passes the forecast window, the map holds the last broadly covered snapshot and labels its actual valid date; it does **not** extrapolate weather. Entirely empty trailing frames and sparse regional tails with less than half the peak grid coverage are excluded from this global display window. Internal missing frames remain missing. Route conditions and numeric wave sampling beyond the forecast window remain unknown. Loading and display failures are labelled separately from missing data.

A separate **High seas** switch draws amber 4 m and rose 6 m contours with clickable evidence. A dedicated worker contours a time-interpolated scalar field at up to 12 Hz, coalesces obsolete requests, and defers geometry updates while the camera is moving. Existing lines still scale with the map at its rendering rate. These are forecast display thresholds, not confirmed storms or official warnings. The forecast timestamp remains attached to each feature, including when the display holds its last snapshot. Scrolling eases around the pointer; zoom buttons use the same bounded camera easing. Reduced-motion preferences and the viewport zoom-out limit are respected. These display operations do not change route calculations.

The coastline mask in `public/data/land-mask.geojson` is derived from the existing GSHHG 2.3.7 high-resolution display data, simplified by 0.005° and rounded to four decimals for display only. It does not replace the backend’s unsimplified navigation screening geometry. Rebuild it with `scripts/build-land-mask.py`; source attribution is shown on the map and the original license texts are in `public/licenses/`. The renderer waits for this mask before showing the blurred field.

**Restricted areas** renders verified, non-cancelled polygon notices supplied in the route report with a muted hatch, dashed border, name, validity interval and source link. Areas are filtered against the voyage playback time. When no verified polygons are supplied, the toggle is disabled and says data unavailable; this does not mean the route is unrestricted. The current catalogue has no verified restriction polygons. A live cyclone-warning feed is not connected. Weather coverage is shown explicitly, and missing conditions are never described as calm or safe. Compliance is not assessed.

Network, timeout, startup, invalid-input and empty-result failures produce a retryable message. API calls omit cookies and use the service's existing cross-origin support.

## Backend

See [`route-planning-api/README.md`](route-planning-api/README.md) for data sources, Atlas collections/indexes/GridFS, forecast refresh, canal assumptions, costs, API schema and deployment.

```sh
cd route-planning-api
uv sync --extra dev --extra providers
cp .env.example .env   # fresh checkout only
uv run python -m scripts.dev
```

The local API listens at http://127.0.0.1:8765, with documentation at `/docs`. For a same-origin local preview, run the API on port **8766** (`uv run uvicorn service.main:app --host 127.0.0.1 --port 8766`) and set `VITE_ROUTE_API_BASE_URL=/local-api` in `.env.local`. Vite proxies `/local-api` to that local service, avoiding cross-origin requirements during development. Production builds should use the deployed API URL instead. Demo mode is an explicitly simulated Atlantic network; use `TIDELINE_MODE=mongo` and your existing Atlas connection for the real imported network. The default frontend uses the already deployed production API.

This repository contains service source, importer/refresh scripts, tests, Docker/Wrangler configuration, small planning references and the public-domain Natural Earth fallback mask needed by demo tests. It excludes credentials, raw archives, forecast downloads, large generated geography, database caches and reports. Production graph, reference and forecast data are retrieved from Atlas.

Cloudflare commands run inside `route-planning-api/` or its `cloudflare/` subdirectory, as documented there. Do not run deployment commands from the frontend root.

## Project layout

```text
src/api/                     Public route-service client
src/data/                    Port catalogue, form state, report and formatting
src/app/screens/             Landing, search, comparison and map screens
src/globe/                   Globe and exact API geometry rendering
src/tokens.css               Shared visual design tokens
public/data/                 Precomputed Natural Earth land-dot assets
tests/                       Frontend contract/error/geometry tests
INTEGRATION.md               Original supplied frontend handover, preserved verbatim
route-planning-api/          Python API, Atlas tools and Cloudflare gateway
```

`INTEGRATION.md` is the supplied **pre-integration** handover. Its references to placeholder routes, a Next.js MVP, missing tests and dead-end buttons describe the old prototype. This README and the current source describe the implemented HTTP API integration.

## Data and map attribution

Map rendering: Mapbox GL; the selected-route basemap is Mapbox Light, with Mapbox/OpenStreetMap attribution in the map. The landing globe’s dot geometry and the backend fallback mask use [Natural Earth](https://www.naturalearthdata.com/), public-domain geographic data. Production land screening uses GSHHG with its own licence and provenance described in the backend README. Display dots are an artistic representation and are not the collision geometry used by the routing service.
