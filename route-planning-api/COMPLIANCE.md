# Cargo and voyage compliance

The frontend accepts a plain cargo list, a readable PDF/DOCX/text file and an optional IMO number. Search starts route calculation and public-data acquisition together. Argon specialists assess security, environment, tariffs/documents, sanctions/vessels and dangerous goods alongside the existing congestion researcher.

## Runtime flow and endpoints

| Endpoint | Contract |
|---|---|
| `POST /documents/extract` | Multipart `file`; returns full `text`, page-aware `references`, checksum and `stored:false`. PDF/DOCX/TXT/CSV/Markdown, up to 10 MiB / 200,000 extracted characters; PDF limit 200 pages. Scanned documents need OCR text. Rejected inputs are never silently truncated. |
| `POST /voyages/analyse` | JSON `{routeRequest,cargoText,documentReferences}`. `routeRequest` is the existing routing request with optional `complianceContext` declarations. Returns newline-delimited JSON, not one JSON document. |
| `POST /compliance/chat` | `{analysisId,contextToken,findingId,question,history}`; returns a cited answer about the finding. An optional stateless form accepts the report/cargo/finding directly. |
| `GET /compliance/data-status` | Reference versions, freshness and record counts. |

Analysis events are `started`, optional `heartbeat`, `route_report`, `context_ready`, six independent `assessment` results and `complete`. An `error` event can occur after HTTP 200 and must be handled. Existing `/routes` and `/port-congestion` remain available.

Reference loading and optional API lookups begin during routing. Specialists are dispatched concurrently when the complete model is ready, before transferring the large display report to the browser. The frontend resolves route planning on `route_report`; it keeps consuming assessments across navigation. A new journey cancels the old stream, and late results cannot attach to another report.

```javascript
await api.analyseVoyage({
  routeRequest: { origin: 'NLRTM', destination: 'SGSIN' },
  cargoText: 'Machinery, water-based paint and lithium-ion battery packs',
  documentReferences: []
}, { signal, onEvent(event) {
  if (event.type === 'route_report') renderRoutes(event.report);
  if (event.type === 'assessment') updateFindings(event);
  if (event.type === 'error') showError(event.message);
}});
```

## Compact shared context

Every specialist receives the same compact voyage brief: all route alternatives, ports/dates, passages, fuel/cost/CO₂ estimates, weather summary/coverage, assumptions, full cargo text and supplied/resolved vessel information. All results carry the same brief fingerprint, `contextSha256`. User declarations remain distinct from verified facts and generic performance assumptions. Upload references use page-aware offsets into cargo text to avoid sending the same text twice; separately supplied reference text is retained.

The full routing response can exceed 45 MB because of wave-display arrays. It stays available for the map and backend calculations, but it is not sent to each model. Detailed geometry, timed segments, raw weather and source records are available through the read-only `read_route_report` tool, using the explicit paths in the brief. Responses expand bounded subtrees, or describe large containers for deeper/paged reads. Bounds and passage tags do not establish a legal-area crossing. Oversized direct inputs are rejected explicitly rather than partly reading cargo text.

The runner also offers read-only `lookup_reference` for fresh public Mongo passages, and Google Search for necessary missing facts. Interactions use `store:false`, low thinking, a 4,096-token ceiling and at most three model turns, reserving the last turn for a final answer instead of another lookup. Quick screening requests zero to three short actionable findings, a one-sentence summary and at most two web sources per category. Each agent chooses its own Mongo lookups, route-detail reads and web searches. Web search is available for verification, enrichment or missing public facts even when Mongo already has evidence. Research stays shallow and targeted within the small tool-round budget; no exhaustive report is requested. A longer investigation is left to **Learn more** chat. There is no separate agent framework, autonomous delegation, shell tool or database-write tool. Provider data-processing terms still apply.

At most two analysis contexts are retained in process memory for 30 minutes for tools/chat. They are not written to Mongo and disappear on restart or eviction. The browser's `contextToken` is a private session capability; never log it or put it in a URL. Expired chat contexts require recalculation. Cargo extraction does not store uploads or create a customer profile.

## Atlas data and retrieval

| Storage | Contents and access |
|---|---|
| `compliance_sources` | Official/supplied provenance, URL, active snapshot, checksum, check/refresh dates and counts. |
| `compliance_documents` | Page/section-aware passages. Atlas Search under active-version filters, with ordinary text-index fallback. |
| `compliance_files.files/chunks` | Original public/reference files in GridFS. User cargo uploads are not written here. |
| `sanctions_entities` | Current UK/OFAC designations and separately identified supplied EU exports. Exact IMO/name indexes; name matches remain candidates. |
| `commodity_codes` | HS2022 classification records. These are not tariff rates. |
| `maritime_zones` | Reviewed JWC/IBF/ECA GeoJSON with dates. `2dsphere` selects route intersections; Python calculates distance/time/fuel overlap. |
| `compliance_rules`, `tariff_measures`, `port_fee_schedules` | Reviewed executable inputs. Importing a PDF does not create a verified rate/formula. |
| `market_observations` | Reviewed, dated instrument prices such as EUA; currency, observation time and provenance are required. |
| `vessel_facts`, `port_baselines` | Optional source-stamped registry enrichment and historical context, when acquired. |
| `api_cache` | Public API results with explicit expiry and TTL cleanup. No cargo text or user routes. |
| Existing routing, forecast and PortWatch collections | Continue supplying routing and port observations. Agents reuse the conditions actually used by the route engine. |

The importer writes complete versioned rows and original files first, then atomically replaces one active-source pointer. Old snapshots remain; failed imports do not activate half a list. Refresh timestamps and legal effective dates are separate. Retrieval checks expiry itself because TTL deletion is asynchronous. GridFS needs explicit file cleanup.

Current local ingestion includes UK/OFAC feeds, the supplied EU export, HS2022, JWC/IBF publications, official regulatory pages and selected supplied reference PDFs. Supplied copies retain Drive provenance and are not silently treated as independently verified current law. Historical OFAC exports containing removed designations are rejected for active screening. EU schema 1.0/1.1 exports must not be appended as independent entities.

## Import and refresh

Run from `route-planning-api/` with the backend environment configured:

```sh
python -m scripts.ingest_compliance --refresh --structured --publish --atlas-search
python -m scripts.ingest_compliance --env-file /path/backend.env \
  --file /path/current-list.csv --source uk_current --category sanctions \
  --kind uk_sanctions --url https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv --publish
```

Without `--publish`, the command validates and reports a dry run. Structured kinds are `uk_sanctions`, `ofac_sdn`, `eu_sanctions`, `hs`, `zones`, `rules`, `tariffs`, `fees`, `market_observations` | Reviewed, dated instrument prices such as EUA; currency, observation time and provenance are required. |
| `vessel_facts`, `port_baselines`. JSON zones/rules require `--reviewed` to participate in calculations. `document` preserves extracted passages and pages.

Registered refreshes acquire JWC/IBF pages and pinned current publications, Commission ETS/FuelEU/customs guidance, IMO CII/IMDG guidance and sanctions source pages. Structured refreshes acquire current UKSL, OFAC SDN and UN HS2022. Pinned JWC/IBF publication URLs need updating when a new edition appears; index pages are refreshed separately for discovery.

The authenticated private `/internal/refresh-compliance` endpoint refreshes due sources. Cloudflare's scheduled handler dispatches it alongside forecast refresh within the same cron window. Public requests cannot reach internal endpoints. Proposed application policies are six-hour sanctions checks, daily/weekly public-reference checks and monthly HS checks; these do not imply that every publisher updates at that frequency.

The provided AIS file and CPPI remain historical context, not live ship identities or congestion. ICS2 and DCSA specifications are interfaces/requirements, not operational feeds or submissions. Full IMDG content and comprehensive current vessel ownership data are not assumed to be freely available.

## External calls and evidence

Declared ten-digit UK codes can trigger the official Trade Tariff API, with a six-hour public cache. Measure conditions/legal references are preserved; the adapter does not guess a payable rate. US/EU tariff and unsupported port-fee coverage uses imported reviewed measures and focused official-source research. No universal free port-fee/registry API is claimed.

Search URLs must appear in provider tool citations. Approved official pages are fetched and the quoted passage must match their text; Google grounding redirects can resolve to the publisher. A guessed URL alone is insufficient. Source retrieval cannot activate a rule or modify the route. TinyFish is not a runtime dependency.

Findings include category, severity, evidence status, short title/explanation/action, route/port scope, missing inputs, citations and optional Python-calculated costs. The backend validates route IDs and maps departure/arrival roles to canonical port IDs. It discards model-invented costs and unverified scope. Missing evidence never becomes clearance.

Initial numeric calculators cover reviewed zone overlap, explicit reviewed ad-valorem tariff scenarios, reviewed fixed/per-GT/per-container port-fee components and reviewed CO₂-only ETS scenarios with dated allowance prices. The current database has reference documents and lists, but no reviewed global zone catalogue, tariff-rate coverage, port-fee schedules or allowance-price feed; those numerical costs remain unavailable until such records are supplied. A sanctions-list match remains a screening alert requiring jurisdiction/identity/ownership checks, rather than automatically proving a prohibition on this voyage. Actual premiums require quotes/rates, insured value and terms. FuelEU liability/CII grades need annual vessel data. Demurrage needs free time, tariffs and container milestones. Definitive dangerous-goods checks need sufficient product details and licensed current IMDG rules. Missing information produces a scoped missing-input result rather than a zero charge.

## UI and configuration

Each port's blue issue pill opens one vertical list: congestion first, then applicable compliance findings. Evidenced yellow/red alerts retain their severity; missing-input and unverified findings are neutral list items with explicit status. Expand for short details, citations and **Learn more**, which focuses the research chat. Congestion keeps **Reroute**. New findings update an open popup while retaining expanded rows. A separate rounded grey progress card at the top right shows a spinning loader with “Researching” for active categories and a green circular tick when research returns. The tick marks finished research, including results needing more details; it is not a clearance indicator. Failed checks remain marked unavailable. Detailed findings are on the ports. Route-wide findings describe voyage exposure even when displayed at an endpoint. Zero port badges is not a universal pass.

Secrets stay in ignored backend `.env` files. Defaults: `COMPLIANCE_CONCURRENCY=6`, `COMPLIANCE_MAX_ANALYSES=2`, `COMPLIANCE_MAX_CONTEXT_BYTES=3000000`, `COMPLIANCE_CALLS_PER_HOUR=60`, `CONGESTION_CALLS_PER_HOUR=20`. Budgets are process-local, not global provider spending caps. Research has no blanket elapsed deadline; network/provider/hosting failures remain possible. There is no artificial spinner delay. One local Rotterdam–Le Havre test returned route options in 11.2 seconds and all six assessments in 27.7 seconds; congestion was cached, and the five new specialists took 4.5–17.7 seconds each in parallel. This is a single observed run, not a latency guarantee.

The Worker accepts streaming NDJSON, 1 MiB analysis inputs and 11 MiB multipart envelopes, with separate stateless-chat limits. Provider credentials never enter frontend bundles. Source changes are local until the normal deployment command is run.

## Checks

```sh
python -m pytest tests/test_compliance.py tests/test_congestion.py -q
npm test
# From cloudflare/: npm test
```

Regression coverage includes parallel launch, complete-report tools, shared context, canonical ports, invented evidence/costs, historical-list rejection, effective dates, document extraction, progressive streams, session expiry and cancellation. Live provider/source checks are also required; passing fixtures establishes software behaviour rather than legal clearance or measured voyage accuracy.
