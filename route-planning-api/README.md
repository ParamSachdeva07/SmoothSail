# SmoothSail route-planning API

See [COMPLIANCE.md](COMPLIANCE.md) for parallel cargo/voyage screening, Atlas reference ingestion, streaming results and cited follow-up chat.

For a local presentation, set `VITE_DEMO_RESEARCH=true` in the frontend's ignored `.env.local` and search **Le Havre (FRLEH) → Singapore (SGSIN)**. The development frontend then asks `/voyages/analyse` for the bundled, clearly labelled synthetic findings in `service/demo_research.py`. Upload `SMOOTHSAIL cargo manifest mock.pdf` and enter IMO `9912340` in the optional-details form to see findings based on those inputs. The mock manifest names Shanghai → Rotterdam and says its fictional vessel has no assigned IMO, so the demo flags both conflicts. Only the exact FRLEH → SGSIN pair accepts `demoResearch: true`; route calculation, ETA, cost, wave forecasts and `/routes/reroute` remain live. The demo has no verified port conditions, cites the uploaded PDF only as a user document, and is never ingested into MongoDB or requested in production builds. Remove the setting to resume live research for the same pair.

This directory contains the Python service and Cloudflare gateway. The current Vite/Mapbox frontend lives in the repository root; the previous Next.js prototype is not included. Run every backend command below from `route-planning-api/`. Production datasets are retrieved from the configured Atlas database or imported using the scripts. Git includes the Natural Earth fallback land mask needed to run demo mode and its tests, plus small planning references; large production masks, forecasts and source archives are excluded.

A Python maritime route comparison API and MongoDB for reference data and environmental snapshots. Enter two ports and receive **fastest, cheapest and lowest-CO₂ options in one response**. User inputs and calculated voyages are not persisted.

This README describes the implemented service, including what each source actually changes in the calculation. Fuel, ETA and costs are comparative planning estimates for an assumed ship. The service does not provide navigation clearance or an automated compliance decision.

- [How a request becomes three routes](#how-a-request-becomes-three-routes)
- [Data sources and their roles](#data-flow-and-storage)
- [MongoDB collections and local files](#mongodb-collections-and-local-files)
- [Atlas features used](#atlas-features-used)
- [Static data, forecasts and refresh policy](#static-data-forecasts-and-refresh-policy)
- [Run locally](#run-locally)
- [Deploy on Cloudflare](#deploy-on-cloudflare)
- [Import the supplied archives](#import-the-supplied-archives)
- [Canals, fuel and cost calculations](#canal-support-and-generic-cost-model)
- [Refresh forecasts and PortWatch](#refresh-forecasts)
- [Endpoints, route objects and rendering](#endpoints-and-route-object)
- [Optional ship parameters](#optional-ship-parameters)
- [Evidence for an AI agent](#evidence-for-an-ai-agent)
- [Code map](#code-map)
- [Verification](#verification)

## Port congestion search

`POST /port-congestion` is independent of `/routes`; it never changes route ETA, cost, compliance or geometry. Required input:

```json
{"portIds": ["NLRTM", "SGSIN"]}
```

At most two distinct UN/LOCODEs are accepted. Optional `knownData` can contain up to four public facts per requested port:

```json
{
  "portIds": ["NLRTM"],
  "knownData": {
    "NLRTM": [{
      "statement": "A dated operational observation, supplied by your integration.",
      "source": {
        "title": "Operational update",
        "url": "https://example.org/operations",
        "observedAt": "2026-10-24T12:00:00Z",
        "scope": "port"
      }
    }]
  }
}
```

This is a schema example, not a real port observation. Send only public operational facts. Credentials, cargo/customer details and private documents are not needed. Input facts and web pages are explicitly treated as data rather than instructions. In Mongo mode, the backend resolves the supported port and includes up to seven existing PortWatch observations (`containerPortCalls`, `allPortCalls`, date). It does not download PortWatch on demand or treat activity counts as measured queues.

**Research:** one HTTPS request to the Gemini Interactions API, model `gemini-4-argon`, Google Search tool, `low` thinking (Argon's lowest supported setting), 3,072-token output cap, JSON schema. The short prompt requests one search pass, at most one focused query per port, one supporting source and summaries of at most 35 words. It requests no follow-up searches or separate alternative-port investigation. The nearest supported alternative is supplied from the port catalogue. These are model instructions, not a provider-enforced search-call limit; the provider may run more than one search internally. The token cap is a ceiling including thinking, not a target response length. Qualitative, dated operational reporting can support `reported` congestion; numerical observations can support `measured`. The model must use `unknown` for missing, conflicting or inconclusive evidence. There is no fabricated numerical congestion score.

**Validation:** a non-unknown conclusion needs source URLs present in the provider's citation annotations, observation dates within 72 hours and no future dates. If any claimed source is stale or uncited, the assessment becomes unknown. This checks provenance/freshness, not independent factual truth; extraction quality still depends on the source and model. For mild/high, Atlas `$geoNear` on supported port approach points supplies the closest alternative, excluding both requested endpoints. Demo mode ranks its supported catalogue locally. The backend attaches this canonical port rather than trusting a model-generated identity or congestion claim. `alternativePort` includes `distanceNm`, `selectionBasis: nearest_supported_port` and `congestionLevel: unknown`; a source is optional because this is a catalogue proximity suggestion. Distance is straight-line between approach points, not sailing distance. Carrier, cargo, terminal suitability and congestion at that alternative remain unassessed. Only the user's **Reroute** click replaces the affected endpoint and starts a new calculation.

The response contains `assessments[]`, each with `portId`, `portName`, `level` (`low/mild/high/unknown`), `basis`, `confidence` (qualitative), `summary`, `evidenceAsOf`, dated `sources`, nullable `alternativePort`, `checkedAt`, `refreshAfter`, `researchStatus`, `qualityNotes`, `cached`, `methodVersion` and `display`. `display` gates the frontend's blue **1 issue** pill for mild/high only. Clicking the pill opens a collapsed issue list, with yellow/red severity shown beside the row; expanding the row reveals details and source citations. Google search suggestions remain response metadata but are not rendered as widgets in the popup. Missing data is never a low-congestion claim. The assessment describes current conditions, not conditions at a future voyage arrival.

**Latency and storage:** research starts with route submission and has no application-imposed elapsed-time cutoff in the service, browser or Worker gateway. The provider HTTP client has no response-read deadline; connection, write and pool operations retain 30-second network timeouts. Provider/hosting limits and disconnections can still interrupt a request. Route calculations keep their separate timeouts and return without waiting for research. Evidence freshness and cache expiry are evaluated when research completes. Cached assessments return without a provider call. Provider/network failures return unknown, with no alert. Two identical concurrent port-pair requests share one in-flight task; at most two distinct requests run concurrently. Shutdown cancels outstanding tasks. The in-memory cache holds up to 128 assessments. In Atlas, `port_congestion_cache` stores the assessment and source metadata under a hash of port ID, voyage port pair, model, method version and supplied facts. Frontend caching also uses the complete port pair so an alternative from another journey is never reused blindly. Its `expiresAt` TTL index removes expired entries; application code also checks `refreshAfter` because TTL deletion is asynchronous. Supported results last at most 30 minutes, shortened if evidence would become stale. Unknown/error results last 60 seconds. No route or customer record is persisted by this feature.

`CONGESTION_CALLS_PER_HOUR=20` limits paid research calls **per service process**, including failed attempts; the limit resets on process restart and is not a global billing cap across replicas. Use the provider's spending controls for a hard account-level budget. Setting it to `0` disables research while allowing existing cached assessments. Model output and Google Search may incur usage charges.

Set `GEMINI_API_KEY` in the backend `.env`, never in a `VITE_` variable. Restart the API after adding it. The current local preview can also launch with `--env-file /Users/paramsachdeva/Documents/ChatGPT/SmoothSail/.env`, matching the existing local credentials file. Without a key, the endpoint returns `unknown/not_configured` immediately without touching Mongo or Google. Tests use mocked provider responses; live model quality and latency require credentials.

For a future Cloudflare deployment, save `GEMINI_API_KEY` with `wrangler secret put GEMINI_API_KEY` from `cloudflare/`, then deploy the updated Worker/container. The gateway permits this public endpoint with the same JSON/CORS policy as routes. This code change does not itself deploy or provision a key.

Historical datasets remain context: ADB Port Traffic can supply historical waiting/service baselines; World Bank CPPI supplies annual efficiency comparisons. Neither is treated as current congestion. Canal authority data belongs to canal transit planning; bunker prices belong to the cost model. These sources are not newly ingested by this feature. Fresh structured queue/wait feeds can later bypass research without changing the UI contract.

Implementation: `service/congestion_models.py` (contract), `service/congestion.py` (search, validation and cache), `tests/test_congestion.py` (mocked provider, freshness, failures, budget, endpoint tests). Official API references: [Gemini 4 Argon](https://ai.google.dev/gemini-api/docs/latest-model), [Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search), [structured output](https://ai.google.dev/gemini-api/docs/structured-output).

## How a request becomes three routes

The only required inputs are the origin and destination UN/LOCODEs:

```json
{"origin": "NLRTM", "destination": "SGSIN"}
```

The request follows this sequence:

1. **Load planning references and resolve the ports.** Pin the active Mongo planning version (vessel, canal catalogue and land mask), then read the two supported ports. Use their mapped offshore approach points and network nodes. A port's catalogue coordinate can be on land and is not used as a harbour entrance.
2. **Load the sea network.** Read the active graph version, reuse its local/in-memory cache, restore dateline connections and remove ordinary edges crossing the land mask. Only the exact reviewed Suez and Panama corridors receive canal exceptions.
3. **Load available conditions and permanent exclusions.** Read forecast snapshot metadata and verified, undated exclusions from Mongo. Load reusable forecast grids from local cache or GridFS. There is no ECMWF, Copernicus or PortWatch API call inside the route request.
4. **Generate candidate paths and query their restrictions.** Compare paths weighted for time, cost and fuel, explicit canal bypasses, and weather-weighted alternatives. Mongo `$geoIntersects` retrieves restrictions within padded envelopes covering all candidate paths; passage-only records are included by ID. Future-dated notices remain available for simulation. This is a bounded network search, not a search over every possible ocean coordinate.
5. **Simulate each path at several speeds.** By default these are 12, 14 and 16 knots. Walk along the path in time order; sample waves and currents at the estimated passage time, calculate elapsed time and fuel, add canal waiting/transit costs, and reject candidates intersecting verified exclusions during their effective intervals.
6. **Select the three winners.** Fastest minimizes total duration; cheapest minimizes included voyage cost; lowest emissions minimizes estimated fuel-combustion CO₂. A path can win more than one category. Different speeds on the same path are valid alternatives.
7. **Return a self-contained report.** Include route geometry, timed segments, cost and emissions breakdowns, forecast coverage, source references, assumptions and compliance handoff metadata. The frontend renders the API geometry and metrics. The full response also includes forecast grids and metadata for other clients.

In `mongo` mode the flow is:

```text
Static archives → import/preparation scripts → Mongo records + local geometry
Provider APIs   → refresh process            → Mongo forecast metadata + GridFS
                                                      ↓
Two ports → Vite frontend → Python /routes → cached data + simulation
                                                      ↓
                                    three route options + evidence
                                                      ↓
                                      comparison cards + 2D/globe map
```

The service performs the calculation within one request. It has no job queue, route polling, saved voyage profile or route-history database. Forecast refresh runs separately so a user does not wait for provider downloads.

## Data flow and storage

### Data that affects routes and estimates

| Source | What is used | Where it is stored | What it changes |
|---|---|---|---|
| [UNECE UN/LOCODE](https://unlocode.unece.org/publications/) | Location code, name, country and coordinates; the importer uses the function field to filter port entries | Mongo `ports`; source ZIP in `data/raw/` | Port search and endpoint identity. Only records with a supported approach mapping can be routed. |
| [NGA World Port Index via OCHA](https://gis.unocha.org/server/rest/services/Hosted/global_world_seaport_index_202511/FeatureServer/0) | Independently named harbour positions, matched by country and reviewed name to UN/LOCODE | Download snapshot in ignored `data/raw/`; match ID, offset and route check in Mongo `ports.accessValidation` | Helps verify new port identities before snapping them to the existing sea network. It does not supply sailing paths or precise berth entrances. |
| Project approach mappings | Approximate offshore access coordinate and matching graph node for each supported port | `data/access_points.json`, copied into each applicable `ports` record during import | The actual start/end of the calculated voyage and ETA. These are not berth or pilotage plans. |
| [Eurostat SeaRoute](https://github.com/eurostat/searoute) | Nodes, connecting sea polylines, distances and passage tags from the canonical 5 km network | Mongo `routing_nodes`, `routing_edges`, `data_imports`; checksummed local graph cache | The available geographic paths. The service searches this network rather than drawing a straight line between cities. |
| [GSHHG 2.3.7](https://github.com/GenericMappingTools/gshhg-gmt/releases/tag/2.3.7) | High-resolution L1 land polygons | Runtime source in Mongo `reference_files` GridFS, selected by `planning_versions`; replaceable disk cache; seed data in `data/geography/` | Rejects ordinary sea edges intersecting land. It provides no depths or under-keel-clearance information. |
| [Natural Earth](https://www.naturalearthdata.com/downloads/10m-physical-vectors/) | Imported geographic features and a fallback land mask | Mongo `geography`; local `data/geography/land.geojson`; original ZIPs | Local/demo fallback when the detailed local mask is absent. Mongo mode requires its published land reference and does not silently substitute a local mask. |
| [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) | 10 m wind components, converted to wind speed | Mongo `forecast_cache` + NetCDF in `forecast_files` GridFS | Weather-weighted candidate generation, exposure and wind metadata. **Wind does not directly alter propulsion fuel or speed in the current simulator.** |
| [Copernicus Marine waves](https://help.marine.copernicus.eu/) | `VHM0`: significant wave height from `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` | Same forecast storage | Generic wave-induced speed loss, resulting ETA/fuel changes, weather-weighted candidates, exposure and the wave map. Wave direction, period and separate swell fields are not used. |
| [Copernicus Marine currents](https://help.marine.copernicus.eu/) | Near-surface `uo`, `vo` from `cmems_mod_glo_phy_anfc_merged-uv_PT1H-i` | Same forecast storage | Along-track current changes speed over ground, elapsed time and therefore voyage fuel/time costs. Tidal and Stokes components are not added. |
| Canal authority publications | Reviewed corridor IDs/coordinates and selected tariff components; project assumptions for waiting/transit time | Active Mongo `planning_versions` bundle; local `data/planning/canals.json` supplies publishable seed data | Makes Suez/Panama paths usable through the land screen and adds tolls, waiting, transit time and service allowances. See [canal calculations](#canal-support-and-generic-cost-model). |
| Generic ship model and optional user inputs | Speed/fuel relation, auxiliary burn, fuel price, daily vessel cost, physical/canal assumptions and CO₂ factor | Active Mongo `planning_versions` bundle; local `vessel.json` seed; overrides only in request memory | Fuel tonnes, USD cost, CO₂ and rankings. These defaults are assumptions, not a measured average of the container fleet. |
| Explicit restriction records, when populated | Geometry or passage ID, action, verification flag and effective time interval | Mongo `restrictions` | An active, verified `exclude` record rejects an intersecting candidate. Other matching records provide advisory evidence. No automatic authoritative closure feed populates this collection. |

The three environmental variables have different roles: **waves affect the modelled speed through water; currents affect speed over ground; wind contributes to exposure and candidate selection.** Wind, waves and currents are not interchangeable fuel multipliers.

### Context and validation data

| Source | Storage | Actual use |
|---|---|---|
| [IMF PortWatch](https://portwatch.imf.org/) | Mongo `port_activity`; reviewed ID mapping in `data/portwatch_mappings.json` and `ports.portwatchId` | Endpoint activity context and observation dates. It does **not** change ETA, infer closure, predict congestion or set canal waiting time. Configured chokepoint observations can be stored, but do not currently affect route scoring. |
| Published ship fuel specifications and a dated bunker price | `data/validation/fuel-benchmarks.json`; Mongo `planning_reference` | Reproducible magnitude/unit comparisons using `scripts.validate_fuel`. These benchmark records do not calibrate the optimizer. The active Mongo vessel reference supplies the calculation's price; demo/local checks use `vessel.json`. |
| Source manifests and archived publications | Local manifests and archives; Mongo `data_imports`, `reference_sources`, `reference_files` | Explain which files, checksums and versions produced a result. Storing evidence does not automatically make its contents a routing rule. |

### Considered sources that are not used

| Source | Current status and reason |
|---|---|
| ERA5 historical weather | No routing integration. This service consumes issued forecasts; it does not train a weather model or extrapolate recent history. |
| Copernicus historical ocean conditions | No routing integration or backtesting pipeline. Live forecast snapshots supply the conditions used for upcoming voyages. |
| NOAA IBTrACS historical cyclones | No routing integration. Historical storm tracks cannot identify the position of a future storm on the voyage. |
| Hapag-Lloyd container specification PDF | No calculation dependency. Box specifications do not supply ship fuel curves, actual loading or canal eligibility. |
| AISStream / IMO GISIS | No vessel identification, AIS globe layer or automatic vessel-performance lookup. `AISSTREAM_API_KEY` is an unused placeholder. |
| EU MRV fuel reports | Downloaded during research, **not imported into Mongo and not used to change defaults**. Annual ship totals do not directly provide a suitable speed–consumption curve; the proposed fleet-matching/calibration work was not implemented. |
| Sanctions, cargo-control and geopolitical material | No automated interpretation or compliance engine. Optional declarations are passed through as unverified context for a future agent. Only explicitly loaded geographic/passage restrictions can block routing today. |

A file being present in `data/raw/` or listed in the handover does not mean the service uses it. The tables above describe the implemented dependencies.

## MongoDB collections and local files

Mongo stores queryable records and binary source/forecast files. It does not run the pathfinding algorithm: Python loads the graph and forecast arrays into memory for calculation.

| Collection / bucket | Important fields or contents | Written by | Read for |
|---|---|---|---|
| `ports` | `locode`, `name`, `country`, GeoJSON `location`, `supported`, `accessPoint`, `routingNodeId`, `importVersion`, optional `portwatchId` and `accessValidation` | Static importer, reviewed expansion; PortWatch mapping refresh | Port search, endpoint resolution and report context |
| `routing_nodes` | `graphVersion`, `nodeId`, GeoJSON `location` | Static importer | Building the in-memory graph for the active version |
| `routing_edges` | `graphVersion`, `edgeId`, `from`, `to`, GeoJSON `geometry`, `distanceNm`, `passageIds`, `bidirectional` | Static importer | Graph connections, route geometry and passage evidence |
| `data_imports` | Per-import counts, parser version and archive checksums; `_id: "active_graph"` stores `graphVersion` and `graphSha256` | Static importer | Selecting/verifying the active network and documenting provenance |
| `geography` | GeoJSON geometry, kind, source and import version | Static importer | Reference/analytics records; Mongo-mode land screening uses the published GridFS mask |
| `forecast_cache` | `datasetId`, `region`, `kind`, `status`, `gridFsFileId`, `sha256`, `retrievedAt`, `forecastRunAt`, `refreshAfter`, valid-time bounds, spatial bounds/resolution and variables | Provider refresh | Discovering forecast snapshots, their freshness and their provenance |
| `forecast_files.files` / `.chunks` | Compressed NetCDF forecast arrays stored by GridFS | Provider refresh | Loading forecast data on a local cache miss |
| `port_activity` | `source`, `locationId`, `date`, `retrievedAt`, original `observations` | PortWatch refresh | Latest endpoint activity date/context; available for analytics |
| `restrictions` | `id`, optional `name`, `geometry` or `passageId`, `validFrom`, `validTo`, `verified`, `action`, `cancelled`, source references | Explicitly curated data; no bundled feed/import endpoint | Time/location screening and advisory overlays |
| `planning_reference` | Seed/reference records plus `_id: "active"` with `version` and `activatedAt` | `scripts.store_planning_data` | Current runtime-version pointer, source records and benchmark evidence |
| `planning_versions` | Content-addressed `_id`, complete `data.vessel`, `data.canals`, `data.land` bundle and `publishedAt` | Reference publisher | Authoritative runtime planning configuration in Mongo mode; old versions remain for reproducibility |
| `reference_sources` | Checksum, filename, `gridFsFileId`, retrieval time and interpretation | `scripts.store_planning_data` | Archived canal-publication evidence |
| `reference_files.files` / `.chunks` | Compressed detailed land mask and canal source files | `scripts.store_planning_data` | Load the published land mask on cache miss; retrieve archived evidence |
| `source_status` | Provider success/failure times; `portwatch_locations` and `atlas_search_ports` configuration | Refresh/setup code | Refresh diagnostics, selected PortWatch chokepoints and autocomplete index configuration |

**GridFS is Mongo's file storage mechanism.** The small `forecast_cache` document describes a snapshot; its `gridFsFileId` points to the larger NetCDF file. Forecasts are arrays indexed by time, latitude and longitude, not one Mongo document per weather cell.

Indexes enforce unique UN/LOCODEs, graph-version/node and graph-version/edge pairs, and PortWatch source/location/date records. Geospatial indexes cover catalogue locations, supported approach points and restriction geometries. Mongo narrows restriction records with a spatial query; Python then checks exact simulated segment/time intersections. Forecast lookup has a dataset/region/retrieval-time index. Expired forecasts are excluded by application logic; `--prune` removes older snapshots and their GridFS files, rather than relying on a TTL index that would leave orphaned file chunks.

```text
data/raw/                       Original source archives and research downloads (ignored by Git)
data/source_manifest.json       Checksums of the supplied archives
data/access_points.json         Supported port-to-network mappings
data/portwatch_mappings.json    Reviewed UN/LOCODE-to-PortWatch IDs
data/planning/vessel.json       Seed/default vessel assumptions for publishing; also used in demo
data/planning/canals.json       Seed canal geometry/tariffs/times for publishing; also used in demo
data/validation/                Fuel specification/price benchmark evidence
data/geography/                 Prepared detailed land mask and manifest
data/cache/                     Replaceable graph snapshots and NetCDF disk cache
data/geography/land-detail.geojson  Simplified land geometry for map display
data/geography/land.geojson         Natural Earth fallback screening geometry
reports/                       Generated import/validation/profile reports (ignored by Git)
```

In Mongo mode, **Atlas is the runtime source of truth** for vessel assumptions, canals and land. To publish a reviewed change, edit the local seeds, regenerate dependent files if needed, and run `scripts.store_planning_data`. It writes a complete content-addressed bundle and atomically switches the `planning_reference/active` pointer after the files exist. The next calculation sees the new version without restarting; an in-progress calculation keeps its original version. Editing a seed record alone does not activate it, and editing a published bundle directly causes its integrity check to fail. Old versions remain available for audit.

Only a new reference version loads its land mask. A changed reference version also rebuilds the screened graph, so updated land/canal rules cannot leave stale edges in memory. Missing or corrupt Mongo references fail explicitly instead of switching to local defaults. The local files remain useful for publishing, offline demo mode and standalone validation scripts.

Forecast arrays and the graph are cached on disk and in memory to avoid database reads at every waypoint. User declarations, vessel overrides and completed route reports are request-local; there are no user, saved-profile, voyage-history or route-plan collections. The UI can export a report without saving it to Mongo.

### Expanding supported ports

The catalogue contains many more UN/LOCODE records than the routing graph can safely serve. `python -m scripts.expand_ports --download-wpi --env-file /path/to/.env` retrieves an [OCHA-hosted World Port Index snapshot](https://gis.unocha.org/server/rest/services/Hosted/global_world_seaport_index_202511/FeatureServer/0) and writes a review report under `reports/`; it does not change the supported set. Each candidate needs one country/name match within 25 nautical miles of its catalogue location, a land-screened SeaRoute node within 15 nautical miles of the WPI position in the main connected component, and three complete route options to an already supported reference port. Review the report, then rerun with `--apply` to write validated mappings to `data/access_points.json` and the matching Mongo `ports` documents. The source snapshot is ignored by Git; the mapped node and provenance are retained.

These points are approximate offshore approaches, not berth positions or navigational clearance certificates. Rejected ports remain searchable only as unsupported catalogue records and are not returned by `/ports`. To serve important ports beyond the current network's coastal reach, evaluate a more detailed sea graph and repeat the same land, canal, endpoint and route validations before activation. Check the source's reuse terms before deploying new WPI-derived mappings commercially.

[auto-sea-way](https://github.com/auto-sea-way/asw) is a candidate for that separate graph evaluation, but its own documentation says the graph has no depth data and can route larger vessels through shallow water. Its planet graph also needs roughly 1.5 GB on disk and a 4 GB server. It has not been substituted into the container-vessel planner; the existing SeaRoute graph, canal rules and cost/weather models remain in force.

## Atlas features used

Atlas hosts the MongoDB database; the Python service accesses it through **PyMongo**. Next.js calls the Python API and never connects to Atlas from the browser. Most features below are standard MongoDB capabilities running on Atlas. **Atlas Search** is the additional search service used for port autocomplete; its search index is separate from ordinary Mongo indexes.

| Feature | Application |
|---|---|
| Document collections and indexes | Reference data, versioned configuration, network records and forecast metadata |
| GridFS | Durable land/forecast files, downloaded to disposable caches when needed |
| `2dsphere` + `$geoNear` | Nearby supported offshore approach points, sorted by spherical distance |
| `2dsphere` + `$geoIntersects` | Candidate-route restriction prefilter, including dateline-safe envelopes and separate passage-ID matches |
| Atlas Search autocomplete | Name/UN/LOCODE typeahead with limited typo tolerance; exact codes take precedence and literal search remains a fallback |
| Aggregation pipelines | `/data-status` summarizes forecasts, freshness and PortWatch observations without downloading all records to Python |
| JSON Schema validation | Protects the versioned planning bundle's required fields and BSON types |
| Atomic document updates | Activates one complete reference version for subsequent calculations |

### Geospatial indexes: nearby ports

`ensure_indexes()` in [service/data.py](service/data.py) creates `2dsphere` indexes on `ports.location`, `ports.accessPoint` and `restrictions.geometry`. Coordinates are GeoJSON **`[longitude, latitude]` in degrees**. `location` is the imported catalogue position; `accessPoint` is the supported offshore routing position. The nearby-port endpoint explicitly uses `accessPoint`, because a port's catalogue point can sit inland.

For example, this read-only `mongosh` query matches the query behind a 100-nautical-mile nearby-port request:

```javascript
db.ports.aggregate([
  {
    $geoNear: {
      near: { type: "Point", coordinates: [3.7, 51.95] },
      key: "accessPoint",
      distanceField: "distanceMetres",
      spherical: true,
      maxDistance: 100 * 1852,
      query: { supported: true }
    }
  },
  { $limit: 10 }
]);
```

Mongo returns nearby supported ports in distance order. Python converts metres to nautical miles and exposes `distanceNm`, rounded to three decimal places:

```http
GET /ports/nearby?longitude=3.7&latitude=51.95&radius_nm=100&limit=10
```

Through Next.js, use `/api/ports/nearby` with the same parameters. This endpoint is available for a map-click or nearby-port picker; the current port form uses text search. Nearby lookup does not itself change a route or choose a different origin. Its distance is spherical proximity to the approach point, **not a sailing distance around land**. The catalogue `location` index is available for geographic catalogue queries but is not used by this endpoint.

### Geospatial indexes: restrictions along candidate routes

Restriction retrieval is part of every Mongo-mode route calculation, through `Repository.restrictions()` and `Repository.route_restrictions()`:

1. Before searching, retrieve non-cancelled, verified `exclude` records with no effective-date bounds. These permanent exclusions can remove blocked edges while generating paths.
2. Generate all candidate paths, including canal bypasses and weather-weighted alternatives.
3. Build padded geographic envelopes around those paths. The implementation subdivides route geometry, splits dateline crossings, limits each envelope to at most 90 degrees of longitude and subdivides horizontal envelope edges. This avoids treating a Pacific route as a box across the rest of the world and limits spherical-edge distortion.
4. Query `restrictions.geometry` using `$geoIntersects`. Also match `passageId` independently so a notice such as a Suez closure does not need a polygon.
5. Simulate each candidate in Python. Check the actual segments, canal events and effective times against the returned notices. An active, verified exclusion makes that candidate infeasible; other matching notices provide evidence.

The spatial portion has this shape; `candidateEnvelope` and `candidatePassageIds` below are computed by the service, not supplied by the user:

```javascript
// Query shape only: production adds one spatial clause per envelope.
db.restrictions.find({
  cancelled: { $ne: true },
  $or: [
    { geometry: { $geoIntersects: { $geometry: candidateEnvelope } } },
    { passageId: { $in: candidatePassageIds } }
  ]
});
```

The envelopes deliberately include surrounding water and land: this is a **database prefilter**, not the final intersection result. A nearby restriction can be returned without intersecting any chosen route. Future-dated notices remain in the result because the ship may arrive after they take effect. Each retrieval rejects more than 10,000 matching records with `restriction_limit`, rather than silently dropping rules.

This feature saves transferring the full restrictions collection to Python. It does not manufacture restriction data: the collection currently depends on explicit curation, with no automatic authoritative closure feed. There is also no loaded EEZ/jurisdiction dataset or sanctions screen. Fine coastline screening uses the published land mask and Shapely in Python, rather than issuing a Mongo query for every sea edge.

### Atlas Search: names, codes and small typing errors

[scripts/configure_mongo.py](scripts/configure_mongo.py) defines the `tideline_ports_v1` search index on `ports` with static mappings:

| Indexed field | Search configuration | Purpose |
|---|---|---|
| `name` | `autocomplete`, `edgeGram`, 2–20 characters, folded diacritics | Match name prefixes while typing |
| `locode` | `autocomplete`, `edgeGram`, 2–5 characters | Match UN/LOCODE prefixes |
| `supported` | Boolean | Exclude ports without supported routing access |

For `/ports?q=...`, a complete UN/LOCODE is checked first through an ordinary indexed lookup. Otherwise, queries of at least two characters use a `$search` compound query: the port must be supported and match the name or code autocomplete clause. Name queries of at least four characters allow one edit, with a one-character exact prefix and at most 20 expansions. This supports a small typo such as `Roterdam`; it is not unrestricted fuzzy matching.

Search has a 1,500 ms server-side time limit. If its index is absent/building, the query raises an `OperationFailure`, or it returns no matches, the service falls back to escaped, case-insensitive literal name/code matching. The fallback does not correct spelling and may scan supported records; the regular `(supported, name)` index does not provide arbitrary substring-search capabilities. Full codes remain a reliable lookup path.

`source_status` record `_id: "atlas_search_ports"` contains `enabled` and `indexName`; the service caches this setting for up to 60 seconds. Search-index creation is asynchronous. Running the setup command again leaves an existing named search index in place; it does not migrate a changed index definition automatically. The current implementation does not change the Atlas cluster tier or provision separate search nodes.

### GridFS: forecast grids and detailed land geometry

The application stores large binary files in two GridFS buckets rather than embedding weather arrays or land geometry inside a planning document:

| Bucket | File contents | Document that points to the file |
|---|---|---|
| `forecast_files` | Normalized NetCDF forecast grids | `forecast_cache.gridFsFileId` |
| `reference_files` | Gzip-compressed land mask and archived canal publications | `planning_versions.data.land.gridFsFileId` or `reference_sources.gridFsFileId` |

Each bucket uses a `.files` collection for file metadata and a `.chunks` collection for binary chunks. PyMongo's GridFS API handles splitting and reconstructing the files. This avoids Mongo's single-document size limit while retaining the files in Atlas. Weather is **not** stored as millions of individual coordinate/time documents, and geospatial queries do not interpolate the forecast arrays.

For a forecast refresh, [service/providers.py](service/providers.py) validates the normalized file, computes a checksum, uploads it, then inserts its `status: "ready"` metadata. Readers only discover ready snapshots. Snapshot identity includes dataset, region and file checksum: re-downloading identical content returns the existing record and does not reset its freshness clock. If metadata insertion fails, the uploader attempts to delete the uploaded file.

At calculation time, the repository reads up to 200 ready metadata records, newest first, and selects the newest record per dataset/region. Files absent from `data/cache/` are downloaded from GridFS and checksum-checked before use. Unchanged forecast arrays are reused in memory. The sampler ignores stale snapshots, prefers finer-resolution fields and evaluates coverage at each segment's position and simulated time; it does not extrapolate beyond available cells/times. Currently this loads the latest configured regional snapshots, rather than fetching a new route-specific subset from a provider.

Land is loaded only when the active planning version changes. Its cached bytes are checksum-checked; missing or mismatched cache contents are fetched again from GridFS, decompressed and checked before building the land mask. Source-publication files are retained as evidence; storing a tariff PDF does not automatically turn its text into executable tariff rules.

`--prune` keeps the newest configured number of ready snapshots per dataset/region and explicitly deletes older metadata **and** its GridFS file. There is no TTL index: automatic metadata expiry alone would leave file chunks behind. Pruning is not a multi-document transaction or a complete disk-cache cleanup; local cache files are replaceable and are not the durable source.

### Versioned planning data and atomic activation

Vessel defaults, canal geometry/tariffs and the land manifest must agree for one calculation. [service/references.py](service/references.py) publishes them as a single bundle:

1. `scripts.store_planning_data` copies reviewed local seeds into `planning_reference`, stores any new land/source files, then calls `publish_references()`.
2. The publisher requires vessel, canals and land records, and verifies that the land file exists.
3. It hashes the canonical bundle and upserts `planning_versions` under that SHA-256 `_id`, using `$setOnInsert`. Re-publishing identical content reuses the version.
4. Only after the bundle exists, it replaces the single `planning_reference` document `_id: "active"` with its version and activation time. **That single pointer replacement is atomic**; the whole publication is not a multi-document transaction.
5. At the start of a calculation, Python reads the active pointer, verifies/loads that bundle if needed and pins it in a request context. A later publication affects subsequent calculations; the running calculation retains its chosen bundle.

Changing a vessel price in the local JSON or a seed document alone has no runtime effect until publication. The next calculation after publication uses the new value and returns `metadata.dataProvenance.planningReferenceVersion`. A version change also rebuilds the screened graph, so new canal/land rules do not reuse the old screened edges.

Old bundles remain for audit. They are treated as immutable by the publisher and verified by hash when loaded; Mongo does not make the documents physically immutable. Directly editing a published bundle is unsupported and causes an integrity failure when it is next loaded. Missing/corrupt references fail explicitly instead of substituting local defaults in Mongo mode. This version mechanism covers the planning bundle; it is not a transaction spanning all port, restriction and forecast records.

The sea network has a separate activation mechanism: imported nodes/edges carry `graphVersion`, and `data_imports/_id: "active_graph"` selects the network with its checksum. On a cache miss, the repository loads that version's records, verifies the snapshot and builds a NetworkX graph. Mongo stores and selects the network; Python runs the path search.

### Ordinary indexes and schema validation

The setup script creates the following ordinary indexes in addition to Mongo's default `_id` indexes:

| Collection | Index | Why it exists |
|---|---|---|
| `ports` | Unique `locode`; `(supported, name)` | Prevent duplicate codes; filter/list supported ports |
| `ports` | `location: 2dsphere`; `accessPoint: 2dsphere` | Catalogue geography and supported approach-point proximity |
| `routing_nodes` | Unique `(graphVersion, nodeId)` | Separate network versions without duplicate nodes within a version |
| `routing_edges` | Unique `(graphVersion, edgeId)` | Separate network versions without duplicate edges within a version |
| `forecast_cache` | `(datasetId, region, retrievedAt descending)` | Dataset/region refresh and snapshot lookups |
| `port_activity` | Unique `(source, locationId, date)` | Repeated refreshes update the same daily observation |
| `port_activity` | `(locationId, date descending)` | Read the latest endpoint observation |
| `restrictions` | `geometry: 2dsphere`; `(passageId, cancelled)`; `(action, verified)` | Spatial/passage retrieval and permanent-exclusion filtering |

An index supports its matching query pattern; it does not mean every scan or aggregation uses that index. For example, the route loader's global forecast-metadata scan and inventory-wide counts still do collection-level work.

The setup also installs a `$jsonSchema` validator on **`planning_versions` only**. It requires a 64-character hexadecimal `_id`, a `data` object containing vessel/canals/land objects, the land manifest's `sha256`, `name` and `gridFsFileId`, and a BSON date `publishedAt`. Invalid writes are rejected. It is a structural check, not a validator for every nested numeric field, a calibration check, a file-integrity check or a validator on every collection. Import/provider validation, checksums and Python request validation serve those separate roles.

### Aggregations: source analytics without saved voyages

`GET /data-status` (or `/api/data-status` through Next.js) runs aggregation pipelines in Mongo and returns compact summaries:

- `forecast_cache`: `$match` ready records, `$group` by dataset/region, count snapshots and those with `refreshAfter > now`, and report the latest retrieval/valid-until times.
- `port_activity`: `$group` by location, count observations and return the latest observation date.
- Ordinary reads/counts add the active planning version, catalogue/supported port totals, non-cancelled restriction count and Search configuration.

Mongo performs these counts/groups rather than sending all source documents to Python for counting. This is on-demand source analytics, not a materialized dashboard or saved-route analytics. `freshSnapshots` measures the cache cutoff, not coverage of an entire voyage; a non-cancelled restriction can be expired or future-dated. The Search setting reports configuration, not proof that the search index is ready.

### Exactly what a route request reads and writes

| Stage | Atlas access | Work kept in Python |
|---|---|---|
| Resolve inputs | Read the active planning pointer and supported origin/destination records | Pin the model version and apply request-local ship overrides |
| Prepare graph | Read the graph pointer; fetch versioned nodes/edges on cache miss | Build/cache NetworkX graph, apply canal rules and screen land crossings |
| Prepare environment | Read forecast metadata; fetch GridFS files on cache miss | Load arrays and sample waves/currents/wind by location and time |
| Screen restrictions | Read permanent exclusions, then spatial/passage matches for candidates | Test exact segments/events and effective intervals |
| Compare and explain | Read endpoint PortWatch context and import/source metadata | Simulate speeds, rank three options, calculate costs/CO₂ and construct evidence |
| Return | **No calculated-route or user-input write** | Serialize the response to Next.js for map display/export |

These are logical stages, not a fixed database-round-trip count. The database remains part of every Mongo-mode calculation even when large assets are cached. There is no database or external-provider lookup at each simulated waypoint, no route-result cache and no minimum artificial wait. A background refresh can write new source snapshots independently of the request.

The PyMongo client is reused by the API repository, and `.env` connection settings stay server-side. This deployment uses a database user through the Mongo driver; there is no browser Atlas login, Atlas Data API integration, Trigger-based refresh, Change Stream listener or Vector Search pipeline. Forecasts/PortWatch use ordinary collections rather than Mongo time-series collections. Refresh scheduling belongs to the Python process or explicit scripts.

### Configure and inspect the Atlas features

With the existing `.env` connection configured and the local reference seeds/land files prepared, run:

```sh
uv run python -m scripts.configure_mongo
uv run python -m scripts.configure_mongo --atlas-search
uv run python -m scripts.store_planning_data
```

The first command configures ordinary indexes and reference validation. The second includes those steps and requests Atlas Search setup; it is optional on non-Atlas Mongo deployments. The third publishes the reviewed planning bundle. These are setup/publication commands, not commands to run for each voyage.

Read-only checks against the running Next.js app:

```sh
curl 'http://localhost:3100/api/health'
curl 'http://localhost:3100/api/ports?q=Roterdam'
curl 'http://localhost:3100/api/ports/nearby?longitude=3.7&latitude=51.95&radius_nm=100&limit=10'
curl 'http://localhost:3100/api/data-status'
```

`/health` reports the active graph/reference versions and default vessel model; it can initialize the caches and is not just a database ping. For database-level inspection in an already authenticated `mongosh` session, use `db.ports.getIndexes()`, `db.restrictions.getIndexes()`, `db.ports.getSearchIndexes("tideline_ports_v1")` and `db.getCollectionInfos({name: "planning_versions"})`. The last two show Search readiness and the installed validator respectively. No credential belongs in these examples or in client-side code.

Mongo reference documentation: [2dsphere indexes](https://www.mongodb.com/docs/manual/core/indexes/index-types/geospatial/2dsphere/), [autocomplete search](https://www.mongodb.com/docs/search/query/operators-collectors/autocomplete/), [GridFS](https://www.mongodb.com/docs/manual/core/gridfs/), and [schema validation](https://www.mongodb.com/docs/manual/core/schema-validation/). The implementation links above define which of those capabilities Tideline actually uses.

## Deploy on Cloudflare

The deployment in [cloudflare/wrangler.jsonc](cloudflare/wrangler.jsonc) uses a **Worker as the public HTTPS/CORS gateway and a Cloudflare Container for the Python service**. Atlas remains the durable data store. The container holds only replaceable local caches. It does not forward requests to this laptop.

```text
Any frontend → HTTPS Worker → Cloudflare Container: FastAPI + routing → Atlas
                   ↑                       ↑
             handles CORS         private scheduled forecast refresh
```

The Python Workers FastAPI example supports ASGI, but it does not make the application's native libraries, Mongo networking and memory requirements compatible automatically. A local real-route run peaked at approximately **688 MiB**, compared with the [128 MB Workers memory limit](https://developers.cloudflare.com/workers/platform/limits/). The container runs the existing Linux Python stack without rewriting the route engine for WebAssembly.

**Deployment status:** the Worker and container were deployed on 24 October 2026 after enabling Workers Paid. The API base URL is **`https://tideline-api.paramsachdeva81.workers.dev`**; [the Cloudflare project](https://dash.cloudflare.com/78eebbca0acd8b98fa162545a97f6103/workers/services/view/tideline-api/production) shows its deployments. [Cloudflare pricing](https://developers.cloudflare.com/containers/platform/pricing/) lists a $5/month Workers subscription plus usage beyond included allowances. Enabling that subscription is an account/billing step, not something the deployment script performs.

### Deploy with Wrangler

Prerequisites: Docker running, Node.js 22+, Wrangler logged into the intended account, Workers Paid enabled, and Atlas reachable from the deployed container. The checked-in account ID is the account selected during setup; change it when deploying to a different account. Open the account's Workers & Pages dashboard to initialize its `workers.dev` subdomain if it does not have one.

```sh
cd cloudflare
npm ci
npx wrangler whoami
npm test
npm run check
cd ..
uv run python -m scripts.deploy_cloudflare
```

`npm run check` builds the Linux/amd64 image and performs a Wrangler dry run. The deploy script first checks Container access, then uploads only the Atlas URI, Marine username/password and a generated internal-refresh token through Wrangler's encrypted secrets API. Values go through stdin, never command-line arguments, Docker build arguments or checked-in files. It then runs `wrangler deploy`. The root `.env` is excluded from the Docker build; the image contains neither credentials nor local data downloads. [Dockerfile](Dockerfile) uses the locked Python dependencies and runs as a non-root user.

The current configuration provisions at most **one `standard-1` instance** (4 GiB memory, half a vCPU), with a 15-minute idle timeout. Route requests reuse that instance and its caches while it is awake. The first request after sleep must start the process and reload Atlas assets; it is slower than a warm request. Calculation timeouts are 90 seconds in this deployment and the gateway allows 180 seconds. These are upper bounds, not intentional delays or a latency guarantee.

This deploys the **API**, not the Next.js UI. An external frontend can call it directly, or a separately hosted Next.js app can set its server-side `BACKEND_URL=https://tideline-api.paramsachdeva81.workers.dev`. [Interactive API documentation](https://tideline-api.paramsachdeva81.workers.dev/docs) describes the request and response models. Atlas network-access configuration must allow the deployed container's outbound connection; changing browser CORS does not change database network access. For this deployment, the project owner approved adding `0.0.0.0/0` to Atlas on 24 October 2026. Database authentication and TLS remain required, but the source-IP restriction is removed. This rule is not a dedicated Cloudflare-only network allowlist.

### CORS and frontend calls

The gateway accepts the documented read endpoints and `POST /routes`, both directly and under `/api/`. It responds to JSON preflight `OPTIONS` requests without starting the container, and adds CORS headers to successful responses, validation errors and gateway errors. It exposes `Server-Timing` to the frontend and disables response caching.

`ALLOWED_ORIGINS` defaults to `*`, so any frontend origin can make **credential-free** requests. Do not use `credentials: "include"`; no browser cookies or login are involved. Only the `Content-Type` request header is permitted by preflight. Set `ALLOWED_ORIGINS` to a comma-separated list of exact origins, such as `https://app.example.com,http://localhost:3000`, and redeploy to restrict browser callers. CORS is a browser policy, not authentication or a global request-rate limit; the configured API is public.

```javascript
const API_BASE_URL = 'https://tideline-api.paramsachdeva81.workers.dev';
const response = await fetch(`${API_BASE_URL}/routes`, {
  method: 'POST',
  credentials: 'omit',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ origin: 'NLRTM', destination: 'SGSIN' }),
});
const report = await response.json();
if (!response.ok) throw new Error(report.error?.message || 'Route calculation failed');
// Render report.routes, as described in the route-object section below.
```

The gateway limits route request bodies to 8 KiB and strips cookies, authorization and internal headers before forwarding. It cannot proxy arbitrary target URLs. `/internal/refresh` is inaccessible through the public Worker, including its `/api/` alias. The container also requires the internal secret for this endpoint. Temporary container failures return a JSON `service_unavailable` error with HTTP 503 and `Retry-After: 5`, including when the Containers SDK returns plain text during provisioning. Frontends may retry after that interval; the gateway does not hide additional retries inside the route request.

### Forecast refresh and deployment checks

A Worker Cron Trigger at **00:17, 06:17, 12:17 and 18:17 UTC** wakes the same container and invokes its private refresh endpoint. This performs the existing bounded ECMWF/Copernicus freshness checks and pruning. Provider failures remain visible through source status and missing/stale coverage; `refresh_checked` does not promise every provider succeeded. PortWatch still uses the explicit refresh script. The standalone background refresh thread is disabled in the container so it does not depend on a sleeping process or compete with the Cron Trigger.

After deployment, verify `/health`, `/ports?q=Roterdam`, `/ports/nearby`, `/data-status` and a real `POST /routes`. Send a preflight and the POST from at least two frontend origins, and check error responses too. Check `/data-status` and route coverage after the first scheduled refresh. The unit checks are `cd cloudflare && npm test`; the Python suite also tests that the private refresh cannot run without the correct token. A local dry run or Docker test does not by itself confirm deployment or Atlas connectivity from Cloudflare.

Run the repeatable live checks with `uv run python -m scripts.check_deployment https://tideline-api.paramsachdeva81.workers.dev`. This validates three real route reports against the Python response schema, checks their strategies and metadata, and exercises CORS, discovery endpoints and blocked private paths. It writes `reports/cloudflare-live-checks.json` and exits unsuccessfully if a check fails.

**Live verification, 24 October 2026:** deployment `24a12ab7-ee80-43b1-b486-f05319503420` passed the public API checks against Atlas. Hamburg–Le Havre returned in **12.08 seconds**, Rotterdam–Singapore via Suez in **19.67 seconds**, and New York–Los Angeles via Panama in **6.55 seconds**, each with fastest, economical and lowest-emissions results. Their reported calculation times were 11.67, 19.10 and 5.87 seconds; the remaining time includes transport and response handling. The initial successful health/data load took **30.72 seconds**. Both tested frontend origins received CORS headers on successful and invalid requests. Port autocomplete, geospatial proximity, data inventory, JSON schema, API docs and private-endpoint rejection passed. The gateway suite now contains **9 passing tests**, including plain-text provisioning-error normalization. These are individual measurements, not latency guarantees or proof of operational voyage accuracy. The Cron Trigger is deployed; a scheduled provider-refresh execution has not yet been observed.

The first deployment initially returned 503 while Cloudflare provisioned the container, then `database_unavailable` because Atlas permitted only the development laptop's IP. The owner-approved Atlas rule above resolved the connection failure. `reports/cloudflare-first-start.json` retains the first provisioning check and `reports/cloudflare-live-checks.json` contains the subsequent successful audit.

The local deployment audit on 24 October 2026 passed **67 Python tests, 8 gateway tests, Ruff and the Wrangler dry-run build**. Wrangler's local Worker forwarded to a fresh Linux/amd64 container using real Atlas data. Hamburg–Le Havre, Rotterdam–Singapore and New York–Los Angeles each returned all three strategies. Preflights from two origins, JSON POST, validation errors, nearby lookup and blocked private paths passed; results are saved in `reports/cloudflare-local-checks.json`. The cold health/data load took 45.94 seconds and the subsequent route requests took 10.28, 8.89 and 3.85 seconds on this machine's emulated Linux container. These are local test timings, not measured Cloudflare production latency. No scheduled provider download was triggered during this audit.

For local Worker/container testing, `npm run dev` uses `cloudflare/.dev.vars` for test secrets; this ignored file must contain the same four secret names used by the deploy script. It is not uploaded by `wrangler deploy`. Keep the normal local Next.js/API ports separate from Wrangler's default port 8787.

## Static data, forecasts and refresh policy

**Storing data in Mongo does not make it static.** Static reference records and regularly replaced forecast snapshots share the same database, but have different update rules.

| Data | Update policy | What happens between updates |
|---|---|---|
| Ports, graph, approach points and land | Explicit re-import/rebuild when the source or mappings change | Reuse the same reviewed geometry. Daily refresh is unnecessary for the planning graph. |
| Vessel assumptions, fuel price, tariffs and exchange-rate assumptions | Explicit review and publication of a complete Mongo reference bundle | Reuse the dated assumptions and return their version in the report. The app does not fetch live prices or tariff changes. |
| Wind/wave/current forecasts | Manual refresh, or an optional background freshness check every six hours | Reuse eligible snapshots; expired, out-of-bounds or unavailable cells become unknown. |
| PortWatch observations | Manual refresh command | Preserve the observation date and show available endpoint context; an old observation is not relabelled as live. |
| Restrictions | Explicit curation with effective dates and cancellation state | Apply records only when the simulated segment's place and time overlap. Absence of a record does not establish permission. |

The service **does not forecast journey weather from recent historical data**. ECMWF and Copernicus supply forecasts for future valid times; Tideline samples those forecasts along the estimated voyage. Historical ERA5/ocean records are not a substitute for an issued forecast.

Four timestamps answer different questions:

- `forecastRunAt`: when the provider's forecast cycle was initialized, when available; recorded for ECMWF, currently `null` for Marine snapshots.
- `retrievedAt`: when this service downloaded the snapshot.
- `validFrom` / `validUntil`: the times represented by its forecast cells.
- `refreshAfter`: the application's freshness cutoff. ECMWF uses 24 hours after the chosen model run; Marine uses 30 hours after retrieval. These are cache-policy choices, not guarantees of forecast skill.

A recently downloaded snapshot can still lack the location or voyage date needed. A 20-day voyage can have forecast data for its first nine days and unknown conditions thereafter. The response retains the full route and marks those unknown intervals; it does not invent a forecast for the remaining days.

When enabled, the background loop runs at startup and every six hours. It refreshes a dataset/region only when there is no ready snapshot with more than two hours before `refreshAfter`; it does not automatically download every new provider run. Each pass covers the overview plus Channel, Suez and Panama detail and retains two successful snapshots per dataset/region. PortWatch is not part of that automatic loop. See [refresh commands and coverage](#refresh-forecasts).

Missing waves produce no additional wave slowdown; missing currents produce no current adjustment. **That is a conditional calculation assumption, not a claim of calm water or zero current.** The corresponding evidence remains `null`/unknown, coverage warnings are returned, and exposure is unavailable unless wind/wave coverage is effectively complete. Waiting at canals currently counts as unknown weather time.

## Run locally

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and Node.js 22+.

```sh
uv sync --extra dev --extra providers
cp .env.example .env  # fresh checkout only; then configure Atlas for mongo mode
uv run python -m scripts.dev
```

The API runs on **http://127.0.0.1:8765**, with interactive documentation at `/docs`. Start the frontend separately from the repo root with `npm run dev -- --port 3200`, and set its `VITE_ROUTE_API_BASE_URL=http://127.0.0.1:8765` to use this local API. The frontend defaults to the deployed Cloudflare API. Node.js 22+ is needed only for Wrangler and the frontend.

Copy `.env.example` to `.env` only on a fresh checkout; preserve existing configuration. Credentials belong in this ignored server-side file, never in `NEXT_PUBLIC_*` variables.

- `TIDELINE_MODE=demo`: offline Atlantic graph with explicitly simulated conditions.
- `TIDELINE_MODE=mongo`: imported SeaRoute graph, supported approach points and available forecasts. Missing weather remains unknown.
- `MONGODB_URI`: connection string. Atlas templates containing `<db_password>` can use `MONGODB_PASSWORD`; the service URL-encodes it.
- `MONGODB_DB=tideline`: target database.
- `AUTO_REFRESH_FORECASTS=false`: fresh-checkout default. Set `true` for bounded background freshness checks every six hours; route requests use existing caches without waiting for downloads.

For disposable local Mongo, run `docker compose up -d mongo` and use `mongodb://localhost:27019`. Atlas uses the same importer and API.

## Import the supplied archives

Put the port, SeaRoute and Natural Earth ZIPs in `data/raw/`; supplied filenames are supported.

```sh
uv run python -m scripts.import_data --source-dir data/raw --inspect
uv run python -m scripts.prepare_access
uv run python -m scripts.import_data --source-dir data/raw --access-points data/access_points.json --dry-run
uv run python -m scripts.import_data --source-dir data/raw --access-points data/access_points.json --apply --allow-rejected
```

Review `reports/import.json` before accepting rejected records. Malformed coordinates, invalid polygons and degenerate edges are rejected. Invalid ocean polygons are not needed for the land exclusion check. Imported catalogue records remain available for analytics, but a port is selectable only when it has a supported offshore approach mapping.

The checked-in mapping currently includes Rotterdam (`NLRTM`), New York (`USNYC`), Lisbon (`PTLIS`), Le Havre (`FRLEH`), Hamburg (`DEHAM`), Singapore (`SGSIN`), Tokyo (`JPTYO`), Sydney (`AUSYD`), Los Angeles (`USLAX`) and Mumbai (`INBOM`). `/ports` returns the supported records in the active installation. Adding another catalogue row alone does not enable routing: it needs a suitable network access point and route/land validation.

Approach points are approximations for voyage planning. `scripts.prepare_access` snaps explicit offshore targets within 15 nm of the connected network. It does not validate pilotage, draft, depth, tides or traffic separation. Imports validate ZIP paths, sizes, coordinates and endpoints without executing archive contents. Identical imports upsert stable records; a graph becomes active only after its count check. Formats include UN/LOCODE/general CSV, GeoJSON, EPSG:4326 GeoPackage, shapefiles with `.prj`, and normalized `TidelineNetwork` JSON.

### More detailed land

The official free GSHHG archive has been downloaded in this installation. To reproduce the derived files elsewhere:

```sh
curl --fail --location --output data/raw/gshhg-shp-2.3.7.zip https://github.com/GenericMappingTools/gshhg-gmt/releases/download/2.3.7/gshhg-shp-2.3.7.zip
uv run python -m scripts.prepare_land
uv run python -m scripts.store_planning_data
```

Original ZIP SHA-256: `8dbbe7e071e77e9e75f2d639239099ebca8d5c16d6a07df8169729d49f15cf41`. Preparation produces 145,720 screening polygons, a separate map GeoJSON and licence files. Screening uses the GSHHG **high-resolution** product without further simplification; only map display is simplified by 0.001°. Its underlying shoreline is older and is not a navigation chart or depth model. Retain LGPL licensing and attribution. `store_planning_data` upserts reference metadata and checksum-addressed files without replacing the routing graph.

## Canal support and generic cost model

Both directions of Suez and Panama are supported by exact reviewed SeaRoute edge IDs and coordinate hashes. A canal tag alone cannot bypass the land check. Suez includes the southern approach; Panama uses the detailed two-edge corridor and rejects the crude straight shortcut. Canal geometry is a planning corridor, not operational clearance. Arctic Northeast/Northwest, Kiel and Corinth passages are excluded for this generic ship.

The shared assumed ship is a **3,500 TEU container ship**, 230 m long, 32 m beam, 10.5 m loaded draft, carrying 2,800 loaded and 350 empty TEU. Suez net tonnage is assumed to be 30,000; Panama uses the Super container category. These particulars are illustrative, not vessel eligibility evidence.

| Model input | Assumption |
|---|---|
| Candidate speeds | 12, 14 and 16 kn through water |
| Main fuel | 38 t/day at 16 kn, scaled by `(speed / 16)^3` |
| Auxiliary fuel | 3 t/day, including waiting |
| Fuel price | $763/t, dated Rotterdam VLSFO indication, 24 October 2026; optional override |
| Vessel time cost | $18,000/day |
| SDR conversion | $1.35/SDR |
| Wave speed loss | `min(0.35, 0.025 × max(0, Hs − 1)^2)`; generic, uncalibrated |
| Suez time | 12 h transit + 12 h assumed wait |
| Panama time | 10 h transit + 24 h assumed wait |

Fuel is calculated from propulsion speed and elapsed time. Waiting burns auxiliary fuel only, in both candidate search and final simulation. Current adjusts speed over ground; waves affect sailing time through the generic speed-loss curve. Fixed canal transit times replace ordinary sea-speed timing on canal segments. `service/costs.py` owns the shared fuel and cost formulas; `service/simulation.py` owns voyage timing and conditions. Geometry is prepared once and reused across operating speeds.

For an ordinary sailing segment, the calculation is:

```text
main tonnes/day       = reference main tonnes/day × (operating speed / reference speed)³
wave loss fraction    = min(0.35, 0.025 × max(0, significant wave height − 1)²)
speed through water   = operating speed × (1 − wave loss fraction)
speed over ground     = speed through water + along-track current
segment hours         = segment nautical miles / speed over ground
segment fuel tonnes   = (main tonnes/day + auxiliary tonnes/day) × segment hours / 24

waiting fuel tonnes   = auxiliary tonnes/day × waiting hours / 24
voyage fuel tonnes    = sum of sailing, canal-transit and waiting fuel
fuel USD              = voyage fuel tonnes × fuel USD/tonne
time USD              = total voyage hours / 24 × daily vessel cost
total USD             = fuel USD + time USD + canal tolls USD + canal service allowance USD
CO₂ tonnes            = voyage fuel tonnes × selected fuel-category CO₂ factor
```

The simulator projects the east/north current onto the segment's heading and converts it to knots. It iterates passage-time sampling up to eight times, aiming for segment-duration convergence within one second. Non-positive speed over ground makes that candidate infeasible. For ordinary sailing, propulsion consumption uses the chosen operating speed; waves increase elapsed time by reducing achieved speed. There is no second wave fuel multiplier. Canal fuel uses the speed implied by its fixed transit time, while canal waiting uses auxiliary fuel only.

The operating speed above is a model setting, not a measured engine command. The cubic relation and wave-speed-loss formula are uncalibrated assumptions. If the user supplies a multi-point fuel curve, piecewise-linear consumption replaces the cubic relation between those supplied points.

For illustration, a longer canal bypass may save a toll but add fuel and vessel days. A slower option may lower fuel and CO₂ while raising vessel-time cost. These tradeoffs are why the cheapest and fastest strategies can differ. The service compares the available path/speed combinations; it does not force three different map lines.

Suez uses the publicly returned container SDR bands effective 15 January 2024, plus the **12% surcharge effective 15 July 2026** from Circular 2/2026. For the default assumed SCNT and conversion, the included base plus surcharge is **$292,269.60**. Deck-tier charges, rebates and other adjustments are excluded and identified per transit. The public circular's surcharge also applies to deck charges when applicable; those charges are not available in this model.

Panama uses the published Super container fixed/capacity/loaded/empty tariff components: **$100,000 + $40 × 3,500 + $35 × 2,800 + $6 × 350 = $340,100**. Reservation/auction charges, freshwater surcharges and other applicable services are excluded from this base. Separate service allowances are explicit assumptions, not official quotes. Exact components, source URLs, effective dates, exclusions and assumed waits are returned in `canalTransits`.

The default bunker price is a dated public Rotterdam reference, not a live global quote or a bunkering plan. No charter quotes, canal bookings or queue forecasts are claimed. Port dues, cargo handling, insurance/war premiums, emissions charges, fuel switching and vessel calibration are excluded. Current canal access, draft eligibility and legal/security permissions remain unassessed. Tariff references are versioned planning inputs and require review when authority publications change; they are not silently refreshed by the weather task.

## Refresh forecasts

```sh
uv run python -m scripts.refresh_data --region global-overview --days 9
uv run python -m scripts.refresh_data --region global-overview --days 9 --sources weather,waves,currents --execute --prune
uv run python -m scripts.refresh_data --region channel --days 9 --sources waves,currents --execute --prune
uv run python -m scripts.refresh_data --sources portwatch --execute
```

The first command previews without downloading. Copernicus requires `COPERNICUS_USERNAME`/`COPERNICUS_PASSWORD`; ECMWF needs no API key. Presets are `global-overview`, `channel`, `north-atlantic`, `suez-approaches` and `panama-approaches`.

The overview is explicitly bounded to 60°S–70°N, approximately 0.5° spatial/six-hour temporal spacing and at most ten days. Lazy Marine retrieval subsamples before materializing arrays. Regional Marine grids preserve approximately 1/12° coastal detail and three-hour samples. ECMWF retrieves selected global GRIB fields before local cropping. Automatic refresh covers the overview plus Channel and both canal approaches; regional wind uses the global atmospheric grid to avoid duplicate downloads.

Normalized float32 arrays are compressed in GridFS, capped at 128 MiB per snapshot. Metadata records resolution, bounds, valid times, retrieval time, run information where available, checksum and refresh deadline. Finer regional data takes precedence, then newer data at equal resolution; coarse ocean data fills available coverage. Global longitude interpolation wraps at the dateline. Missing cells and times beyond the forecast horizon remain unknown.

Weather coverage requires both wind and waves. Canal waits currently remain unsampled and count as unknown. Copernicus snapshots expire after 30 hours of retrieval age; ECMWF snapshots expire 24 hours after the selected model run. Later forecast days are not assumed equally reliable. Automatic refresh and `--prune` keep two successful snapshots per dataset/region. A checksum-verified disk cache and in-process grids avoid repeated GridFS downloads. Forecast arrays reload only when the snapshot identity, checksum or expiry state changes; freshness is still checked on each request. East/north current components must come from the same snapshot. Exact known grid nodes survive missing adjacent cells; interpolation across a missing contributing cell remains unknown.

Map colours show a smooth significant-wave-height field. `waveGrid` contains a global 721 × 257 display grid covering 180°W–180°E and the latitude extent of the currently loaded wave forecasts (not cropped to the route) with evenly spaced Mercator rows, north to south, and six-hour frames over ten days. The browser interpolates samples spatially, blends adjacent forecast textures in time, splits world-spanning rasters into compatible image quads, and leaves missing cells/times transparent. Longitude wraps seamlessly at the date line. Global display coverage uses the existing cached forecasts; it does not trigger additional provider downloads. The current global overview covers approximately 60°S–70°N, so the display envelope is not a claim of full polar coverage. Half-degree longitude spacing and denser Mercator rows preserve Mediterranean and coastal samples. The frontend uses bounded colour blurring and a separate coastline mask to soften the coarse display boundary. The resulting visual halo is not additional numeric forecast coverage. Gzip compresses the denser JSON response when the client supports it. This improves display smoothness without claiming additional forecast resolution. Routing samples the underlying provider grids independently; unknown coastal cells and times outside coverage are not filled.

PortWatch refresh only retrieves reviewed mappings in `data/portwatch_mappings.json` or `portwatchId` on port records. Chokepoint IDs can be configured in `source_status` under `_id: "portwatch_locations"`. Observation dates are preserved; old observations are not relabelled as live data.

## Endpoints and route object

The browser uses Next.js proxies. Provider and Mongo credentials stay on the Python server.

| Method | Browser endpoint | Python endpoint | Returns |
|---|---|---|---|
| GET | `/api/health` | `/health` | Mode, readiness, graph version, supported-port count and, in Mongo mode, fresh-snapshot count. The count does not establish coverage for a particular voyage. |
| GET | `/api/ports?q=rot&limit=20` | `/ports?q=rot&limit=20` | Matching supported ports, approach coordinates and routing node IDs |
| GET | `/api/ports/nearby?longitude=3.7&latitude=51.95` | `/ports/nearby?longitude=3.7&latitude=51.95` | Nearby supported approach points and their spherical distance in nautical miles |
| GET | `/api/data-status` | `/data-status` | Database source inventory, active reference version, forecast freshness and PortWatch summaries |
| POST | `/api/routes` | `/routes` | One report containing the three strategy winners and their evidence |
| GET | `/api/route-schema` | `/route-schema` | JSON Schema for the complete response contract |

Python also exposes `/docs` for interactive API documentation. There is no import, provider-refresh or report-history HTTP endpoint; ingestion and refresh use the scripts below.

Example direct request:

```sh
curl --fail-with-body http://127.0.0.1:8765/routes \
  -H 'Content-Type: application/json' \
  -d '{"origin":"NLRTM","destination":"SGSIN"}'
```

`departureTime` is optional, defaults to now and must include a timezone when supplied. The response uses **schemaVersion 1.4.0**, with a unique `reportId`, departure/generated times, assumptions, routes, unavailable strategies, overlays, optional `waveGrid`, source provenance and notices. The schema is also saved in `docs/route-schema.json`. The obsolete unitless `relativeFuelUse` field has been removed; use `cost.fuelTonnes`.

### Reading the returned report

| Field | What the consumer should use it for |
|---|---|
| `schemaVersion`, `reportId`, `generatedAt`, `departureTime`, `mode` | Contract version, report identity and effective timing; distinguish real-source mode from simulated demo mode |
| `assumptions.vessel`, `assumptions.graphVersion`, `assumptions.canalCatalogVersion` | The exact resolved defaults/overrides and reference versions used |
| `routes[]` | The three selected strategy results, each with its own geometry, timing, cost and evidence |
| `routes[].strategy` | `fastest`, `economical` or `lowest_emissions`; `economical` is displayed as “Cheapest” |
| `routes[].geometry` | GeoJSON `LineString` or dateline-split `MultiLineString` to draw on the map |
| `routes[].distanceNm`, `durationHours`, `eta`, `speedKnots` | Overall distance, duration, ETA at the destination approach point and selected operating speed |
| `routes[].cost` | Entire-voyage fuel tonnes and included USD costs; separate daily-average fuel figures |
| `routes[].emissions` | Estimated combustion CO₂, factor, source and excluded impacts |
| `routes[].canalTransits` | Which canals, entry/wait/transit times, tariff components, allowance and exclusions |
| `routes[].segments[]` | The time-ordered route broken into sailing, canal transit and waiting; geometry, entry/exit/sample time, fuel, conditions and network reference |
| `routes[].metadata.coverage`, `unknownIntervals` | Known/unknown time by variable, plus contiguous intervals requiring missing-data treatment |
| `routes[].explanations`, `warnings` | Why the option won and which assumptions/gaps affect its interpretation |
| `sources` | Forecast snapshot identities, valid times, retrieval/freshness dates, resolution and stale status; static sources are in `metadata.dataProvenance` |
| `waveGrid`, `overlays` | Display-ready wave frames and geographic overlays, separate from the route line and underlying calculation grids |
| `metadata.routingMethod.candidateComparisons` | Distance, duration, speed, canals, cost, fuel, CO₂ and coverage for every evaluated path/speed combination |
| `metadata.complianceHandoff` | Unverified declarations, evidence locations and checks still requiring external authoritative data |

All coordinates are `[longitude, latitude]` in EPSG:4326. Calculated passage times are UTC; distances are nautical miles, fuel is metric tonnes and monetary values are USD. `metadata.units` and `metadata.coordinateSystem` make these conventions explicit. A route ID is scoped to its `reportId`; it is not a persisted database record.

Common errors include `unsupported_port` (no supported access mapping), `no_route` (disconnected graph), `no_feasible_route` (no evaluated candidate survives), `database_unavailable` and `calculation_timeout`. Invalid request fields receive a validation error. Missing forecasts alone do not reject a geographic route: coverage and uncertainty remain visible in the successful response.

`metadata.phaseSeconds` and the HTTP `Server-Timing` header expose reference-data loading, forecast/restriction access, candidate search, voyage simulation, selection, wave display preparation and evidence generation. `calculationSeconds` measures backend calculation, excluding JSON encoding, transfer and browser rendering. The Next.js proxy forwards the response stream and timing header without decoding and re-encoding the report. There is no minimum spinner time, artificial route delay or job polling.

`cost.period` is `entire_voyage`: the displayed fuel cost is the entire voyage total. Daily averages are separate fields. `emissions` covers tank-to-wake CO₂ rather than a complete lifecycle footprint.

### How the options are ranked

Candidate generation compares time, cost, fuel, weather and canal/bypass alternatives at the configured speed settings (12/14/16 kn by default). Time-dependent simulation selects:

1. **Fastest:** minimum modelled total duration, including canal transit/waiting.
2. **Cheapest:** minimum included voyage cost in USD (`economical` in the API).
3. **Lowest emissions:** minimum estimated onboard fuel-combustion CO₂ (`lowest_emissions`). Includes auxiliary fuel during waiting. This is the environmental comparison metric, not a complete environmental-impact assessment.

Two strategies can legitimately share a geographic path and differ in speed, fuel and duration. All three strategies are returned whenever a feasible candidate exists, even with incomplete weather. Missing weather is never scored as calm: exposure scores remain unavailable and fuel/cost/CO₂ estimates carry coverage warnings. Long voyages extending beyond the available forecast retain unknown intervals. There is no deadline, mandatory cargo form, saved profile, job queue or polling flow. Search is heuristic, not a globally optimal time-dependent routing solver.

Weather-weighted search can generate alternatives with less exposure, but there is no vessel-specific maximum wind/wave operating limit or calibrated probability-of-harm model. “Lowest emissions” means lowest estimated combustion CO₂ among evaluated options, not “safest” or lowest overall ecological impact.

### How the map is rendered

MapLibre draws `routes[].geometry` as line layers over the local land GeoJSON, using the same route in 2D and globe modes. Original network vertices are retained; long segments are subdivided to at most 10 nm offshore and 1 nm inside pinned canal corridors. Dateline crossings become separate `MultiLineString` parts so a Pacific route does not draw across the wrong side of the world. More vertices improve representation and time sampling; they do not create newly surveyed sea lanes or navigational precision.

The separate `waveGrid` feeds an interpolated raster overlay and voyage playback uses the timed segments. A smooth colour field is a display of the available forecast, not new observations. Missing wave cells/times stay transparent. Detailed land used for calculation is independent of display simplification: the map's appearance does not determine whether an edge passes screening.

### Optional ship parameters

The UI keeps two ports as its only required inputs. A collapsed **Optional ship details** section accepts service speed, main-engine tonnes/day at that speed, auxiliary tonnes/day, fuel price, daily vessel cost, fuel category and an optional speed/fuel curve. Blank fields retain defaults. Inputs are request-local and do not create a profile or change other users’ defaults.

```json
{
  "origin": "NLRTM",
  "destination": "SGSIN",
  "vesselParameters": {
    "serviceSpeedKnots": 18,
    "mainFuelTonnesPerDay": 50,
    "auxiliaryFuelTonnesPerDay": 4,
    "dailyVesselCostUsd": 22000,
    "fuelUsdPerTonne": 800,
    "fuelCategory": "residual_hfo"
  }
}
```

The main-engine figure excludes auxiliary consumption. Service speed is the fuel curve’s reference point and upper candidate speed; candidates use 75%, 87.5% and 100% of it. Supplied and defaulted fields appear separately in `metadata.vesselModel.inputProvenance` and `assumptions.vessel`. Values are range/finite checked. Physical particulars and the canal tariff category still use the generic ship; these overrides do not validate eligibility for another ship class.

If only `serviceSpeedKnots` is supplied, the default 38 t/day main-engine rate becomes the reference consumption at that new speed. Supply the corresponding `mainFuelTonnesPerDay` too when known; changing speed alone does not identify a real ship's fuel performance.

Alternatively, supply `vesselParameters.fuelCurve` as 2–12 objects such as `{"speedKnots": 14, "mainFuelTonnesPerDay": 32}`. Speeds must increase strictly and consumption must not decrease. This cannot be combined with a single `mainFuelTonnesPerDay` value. The service uses piecewise-linear consumption between the supplied points and compares the lowest, midpoint and highest supported operating speeds. Optional service speed caps that range and must lie above the first point and at or below the last. Canal speeds below the supplied range use an explicitly flagged cubic extrapolation. User points are unverified inputs, not a claim of vessel calibration. In the form, enter one `knots, main tonnes/day` pair per line; auxiliary consumption remains separate.

CO₂ uses the [IMO MEPC.395(82), Annex 7 section 5](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.395%2882%29.pdf) factors: HFO-category residual fuel 3.114, light fuel oil 3.151 and marine diesel/gas oil 3.206 tonnes CO₂ per tonne fuel. The default residual factor is an assumption about fuel carbon content; VLSFO does not identify one universal blend. If selecting another fuel category, also supply its price; the default VLSFO price is otherwise retained and marked as mismatched. Upstream emissions, methane, NOx/SOx, black carbon and ecological impacts are excluded. This is not lifecycle CO₂e.

### Fuel accuracy check

Run `uv run python -m scripts.validate_fuel` to reproduce `reports/fuel-validation.json` from the dated external references in `data/validation/fuel-benchmarks.json`. This checks model magnitude and units, **not actual voyage accuracy**.

A published [3,000 TEU charter listing](https://horizonship.com/ship/2-x-container-ships-of-3000-teu-for-long-period-t-c/) reports main-engine consumption of 32 t/day at 14 kn and 37.8 t/day at 16 kn. The generic model gives 25.46 and 38 t/day respectively: differences of −20.45% and +0.53%. At 20 kn the difference is +42.18%. These are comparisons with one published specification for a different ship, not measured errors for our assumed vessel and not fleet-wide confidence bounds. Its data does not validate extrapolation to 12 kn or the generic weather response.

A second [4,222 TEU newbuild listing](https://horizonship.com/ship/2-x-container-ships-2025-built-china-dwt-61000/) reports 17.5, 24.5 and 37.5 t/day at 12, 14 and 16 kn respectively. Those main-engine figures include shaft-generation load, and additional auxiliary consumption depends on reefer load. The validation report preserves that difference in scope. These examples demonstrate ship-specific variation; averaging them would not establish a representative fleet curve.

The default price is the stored [Bulugo $763/t Rotterdam VLSFO indication](https://bulugo.com/bunker-prices) dated 24 October 2026, with the location/date/source in the response. It does not imply the same price at other ports or future dates and is not automatically refreshed.

At constant 16 kn with no weather/current/canal effects, the default uses 38 + 3 = **41 t/day**, costing **$31,283/day** at $763/t. Ten days costs **$312,830 in fuel**. The app’s voyage cost additionally includes vessel time and any canal charges. Unit tests reconcile those components, but passing software tests does not establish real-world prediction accuracy.

The model has no validated accuracy percentage. Credible vessel-specific accuracy requires observed speed/fuel curves across several speeds and drafts, independent voyage fuel records, auxiliary/reefer loads, actual fuel grades/prices, and comparable weather. Optional single-point consumption improves the baseline but does not validate the cubic speed curve. Supplied multi-point curves avoid imposing that cubic relationship between known operating points, but still do not validate weather response. Metadata explicitly retains `validatedErrorPercent: null` and identifies its benchmark limitations.

The audit also checks the [IMO GreenVoyage speed-management rule of thumb](https://greenvoyage2050.imo.org/technology/speed-management/): 10% lower speed reduces daily propulsion fuel by 27.1%, but fixed-distance propulsion fuel by 19%, because the voyage takes longer. Auxiliary fuel and vessel-time costs are additional. `reports/fuel-validation.json` separately holds out interior points from each published ship specification and checks interpolation against them. Those results test interpolation of the supplied specifications, not real-voyage prediction accuracy.

### Evidence for an AI agent

| Location | Evidence |
|---|---|
| `metadata.ports` | UN/LOCODE, country, catalogue and actual approach coordinates, graph node/import version, mapped PortWatch observation date. |
| `metadata.dataProvenance`, `sources` | Graph/archive checksums, forecast snapshot IDs, refresh/valid times, bounds, resolution and interpolation method. No credentials or local filesystem paths. |
| `metadata.routingMethod`, `vesselModel`, `units` | Candidate comparison summaries, objectives/formulas, canal catalogue, generic particulars, units and missing-data policy. |
| `routes[].cost`, `canalTransits` | Included fuel/time/toll costs, dates and source references, assumed waits, tariff exclusions and model basis. |
| `routes[].metadata` | Geometry/route hashes, dateline-aware bounds, coverage by variable, contiguous unknown intervals, passage events and restriction encounters. |
| `routes[].segments[].metadata` | Coordinates, midpoint, course, cumulative distance/time, speed over ground, condition values/units/status and snapshot references. |
| `metadata.complianceHandoff` | Unverified declarations, separate assessment categories, evidence paths, missing inputs and interpretation rules. |

Optional `complianceContext` accepts vessel, cargo, parties and applicable jurisdiction declarations. These declarations are returned for downstream review and do not alter routing. Separate `vesselParameters` change the performance/cost assumptions described above. Neither is stored as voyage history. Next.js limits request bodies to 8 KiB. The agent should read coverage and handoff first, then inspect segments and obtain current authoritative rules. Country/EEZ intersections, sanctions, cargo controls, emissions rules, permits and physical clearance remain unassessed. Unknown jurisdiction values are `null`; no matches against loaded restrictions do not establish compliance. Event intervals describe matching segments, not exact legal-boundary crossing instants.

## Code map

| File | Responsibility |
|---|---|
| [service/main.py](service/main.py) | FastAPI endpoints and optional background forecast refresh |
| [service/models.py](service/models.py) | Request validation and response/schema contract |
| [service/data.py](service/data.py) | Mongo access, indexes, graph/forecast caching, port lookup and source context |
| [service/references.py](service/references.py) | Atomic publication, integrity checks, GridFS land loading and request-scoped planning versions |
| [service/importing.py](service/importing.py) | Archive validation, normalization, stable record IDs and graph activation |
| [service/providers.py](service/providers.py) | Bounded ECMWF/Copernicus downloads, GridFS storage, PortWatch retrieval and pruning |
| [service/forecast.py](service/forecast.py), [service/interpolation.py](service/interpolation.py) | Freshness, unit normalization, space/time sampling, source priority and wave display frames |
| [service/navigation.py](service/navigation.py), [service/geo.py](service/geo.py) | Land screening, dateline handling, geodesic distance and geometry subdivision |
| [service/routing.py](service/routing.py) | Candidate generation, speed comparison and selection of the three winners |
| [service/simulation.py](service/simulation.py) | Timed voyage simulation, conditions, restriction intersections and accumulated fuel |
| [service/costs.py](service/costs.py), [service/canals.py](service/canals.py) | Shared vessel/fuel/cost/CO₂ formulas, exact canal corridor matching and tariffs |
| [service/metadata.py](service/metadata.py) | Per-segment evidence, coverage, hashes, assumptions and compliance handoff |
| [scripts/import_data.py](scripts/import_data.py), [scripts/prepare_access.py](scripts/prepare_access.py) | Import commands and supported approach mappings |
| [scripts/prepare_land.py](scripts/prepare_land.py), [scripts/store_planning_data.py](scripts/store_planning_data.py) | Detailed land preparation and versioned Mongo reference publication |
| [scripts/refresh_data.py](scripts/refresh_data.py) | Preview/execute forecast and PortWatch refreshes |
| [scripts/configure_mongo.py](scripts/configure_mongo.py) | Geospatial/query indexes, reference schema validation and optional Atlas Search setup |
| [../src/api/client.js](../src/api/client.js) | Browser client for the public route API |
| [../src/globe/flatmap.js](../src/globe/flatmap.js) | Mapbox rendering of exact API route geometry |

Source-specific licences and attribution still apply to each dataset. The importer retaining a file or Mongo storing its contents is not a separate grant of reuse rights. GSHHG attribution/licence files are retained with the prepared data and map assets.

## Verification

```sh
TIDELINE_MODE=demo uv run pytest -q
TIDELINE_MODE=demo TIDELINE_TEST_MONGO_URI=mongodb://localhost:27019 uv run pytest -q
uv run ruff check service scripts tests --select F,E9
cd web
npm run build
```

Mongo integration tests create and drop only randomly named disposable databases. They check repeatable imports, graph activation, GridFS round trips and forecast cache expiry. They also cover pinned planning versions, changed-reference graph rebuilding, corrupt-bundle rejection, approach-point proximity across the dateline, spatial/passage restriction retrieval including future notices, Search fallback, source aggregations and schema rejection. Other regressions cover exact canal corridor validation, both transit directions, one-time canal charges, surcharge effective dates, closures during waits, a cheaper canal bypass, temporary-closure timing, future-time forecast sampling, native coastal detail, dateline interpolation, missing/stale fields, paired current provenance, cost reconciliation and metadata provenance. Scalar and vector interpolation are checked against SciPy independently. Route evidence uses the exact conditions used for timing/fuel, without resampling them during metadata generation.

Frontend interpolation checks run with `cd web && node --experimental-strip-types --test tests/waves.test.mjs`. They check space/time values, unknown-cell transparency and global raster seams. `npm run build` also checks TypeScript.

With the API running, `uv run python -m scripts.verify_routes --report reports/final-route-matrix.json` checks every ordered pair of ten supported ports. It verifies mapped-land exclusion outside exact pinned canal corridors, endpoint matching, dateline splits, temporal continuity, ETA/distance reconciliation, cost/strategy ordering, fuel totals, canal/waiting time totals and honest forecast coverage.

The calculation audit on 24 October 2026 passed **59 backend tests**, including disposable Mongo integration tests, **3 frontend interpolation tests**, the Ruff correctness checks and the production Next.js build. The browser verified supplied-curve submission, malformed-curve rejection followed by a working reset to defaults, 2D/globe wave rendering, the conditions toggle and transparency beyond the forecast horizon. Live proxy checks of supplied/default/invalid curves are saved in `reports/audit-live-api.json`. These checks establish software consistency, not measured voyage fuel or ETA accuracy.

The subsequent Atlas integration audit on the same date passed **65 backend tests**, Ruff correctness checks and the production Next.js build. Live checks confirmed the Search index was ready, `Roterdam` found Rotterdam, and nearby lookup used its offshore approach point. Six before/after route comparisons—Rotterdam–New York, Rotterdam–Singapore, New York–Los Angeles, Tokyo–Los Angeles, Mumbai–Sydney and Hamburg–Le Havre—returned identical geometry, distance, duration, fuel, cost, CO₂ and canal choices for all three strategies, with the same departure and data. Results are in `reports/atlas-route-checks.json`. This verifies that sourcing the same planning inputs from Atlas preserves the calculations; it does not independently validate the physical model.

The updated live matrix passed **90/90 ordered pairs** of the ten supported ports, with zero failures. Request-plus-validation time was a median **2.275 seconds** and maximum **7.164 seconds**, including concurrent browser/API checks. `reports/audit-route-matrix.json` records each case. Checks additionally cover the versioned contract, phase timing totals, wave-grid units/shape/finite values, sample times within segments and removal of the obsolete fuel index. Reproduce it with `uv run python -m scripts.verify_routes --report reports/audit-route-matrix.json` while the API is running.

### Measured calculation performance

`uv run python -m scripts.profile_routes --report reports/profile-after.json` measures calculations separately from initial data loading and JSON serialization. Fixed departure: 24 October 2026 at 18:00 UTC; two warm runs per route, same cached forecast data, no route-result cache. The recorded mean times on this machine were:

| Route | Before | After | Reduction |
|---|---:|---:|---:|
| Rotterdam → New York | 5.64 s | 1.76 s | 68.8% |
| Rotterdam → Singapore | 10.64 s | 3.48 s | 67.3% |
| New York → Los Angeles | 2.67 s | 1.44 s | 46.1% |

The main changes are direct array interpolation, shared geometry across speeds, weather-only sampling during candidate search, skipping equivalent canal searches, reusing the simulation's conditions in metadata and retaining unchanged forecast grids in memory. Initial graph/forecast loading remained about 6–7 seconds in this benchmark; first-request latency, network transfer and concurrent requests add overhead. The larger, smoother wave display also adds response bytes, so these are calculation measurements rather than guaranteed browser response times. Raw runs and profiling output are in `reports/profile-before.json`, `reports/profile-after.json` and the associated logs.

The installation audit on 24 October 2026 recorded 11,732 catalogue ports, 36,121 source nodes, 72,463 source edges and 4,144 original geography features in Atlas. Ten ports had supported approach mappings. The GSHHG mask excludes land-crossing edges when loading the graph. Overview snapshots then covered approximately 24 October 12:00 UTC through 2 November 12:00 UTC, supplemented with coastal snapshots. These are dated audit figures: use the active graph, `/health` and the response's per-route coverage for current state. They do not imply weather coverage for an entire multi-week voyage.

Sources: [UN/LOCODE](https://unlocode.unece.org/publications/), [SeaRoute](https://github.com/eurostat/searoute), [GSHHG](https://github.com/GenericMappingTools/gshhg-gmt), [Natural Earth](https://www.naturalearthdata.com/downloads/10m-physical-vectors/), [ECMWF](https://www.ecmwf.int/en/forecasts/datasets/open-data), [Copernicus Marine](https://help.marine.copernicus.eu/), [PortWatch](https://portwatch.imf.org/), [Suez base tolls](https://www.suezcanal.gov.eg/English/Navigation/Tolls/Pages/TollsTable.aspx), [Suez Circular 2/2026](https://www.suezcanal.gov.eg/English/Navigation/NavigationCirculars/Pages/Cir_02_2026.aspx), [Panama tariffs](https://pancanal.com/en/maritime-services/maritime-tariff/). Retain attribution and source-specific licences.
