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
7. Both **View route** and **Select this route** open the chosen API ID on the map. The renderer uses `geometry` directly, preserving every waypoint and `MultiLineString` date-line split. It adds no smoothing curve, fabricated stops or vessel position. A route crossing the date line appears at both edges of the flat world map, with no line connecting across the world.

The map keeps the original black-dot land, pink selected route and yellow alternatives. Alternatives can overlap because different objectives may select the same geography and speed. Endpoint markers use the API's offshore approach coordinates, which are not berth locations.

**Info** on the cards and **More info** on the map remain disabled placeholders. Wind prediction and conflict-zone switches are visibly unavailable: this response supplies no wind-direction field or connected conflict-screening feed. The API's wave grids are retained in the report but are not displayed by this frontend yet. Weather coverage is shown explicitly, and missing conditions are never described as calm or safe. Compliance is not assessed.

Network, timeout, startup, invalid-input and empty-result failures produce a retryable message. API calls omit cookies and use the service's existing cross-origin support.

## Backend

See [`route-planning-api/README.md`](route-planning-api/README.md) for data sources, Atlas collections/indexes/GridFS, forecast refresh, canal assumptions, costs, API schema and deployment.

```sh
cd route-planning-api
uv sync --extra dev --extra providers
cp .env.example .env   # fresh checkout only
uv run python -m scripts.dev
```

The local API listens at http://127.0.0.1:8765, with documentation at `/docs`. Set the frontend's `VITE_ROUTE_API_BASE_URL=http://127.0.0.1:8765` to use it. Demo mode is an explicitly simulated Atlantic network; use `TIDELINE_MODE=mongo` and your existing Atlas connection for the real imported network. The default frontend uses the already deployed production API.

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

Map rendering: Mapbox GL. Display land and the backend fallback mask: [Natural Earth](https://www.naturalearthdata.com/), public-domain geographic data. Production land screening uses GSHHG with its own licence and provenance described in the backend README. Display dots are an artistic representation and are not the collision geometry used by the routing service.
