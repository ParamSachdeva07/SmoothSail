# Cargo and voyage compliance

Search asks only for ports and departure. After selecting a route, an optional dialog accepts readable PDF/DOCX/text files, cargo notes and an IMO number. Search starts route calculation and public-data acquisition together. Argon specialists assess security, environment, tariffs/documents, sanctions/vessels and dangerous goods alongside the existing congestion researcher.

## Runtime flow and endpoints

| Endpoint | Contract |
|---|---|
| `POST /documents/extract` | Multipart `file`; returns full `text`, page-aware `references`, checksum and `stored:false`. PDF/DOCX/TXT/CSV/Markdown, up to 10 MiB / 200,000 extracted characters; PDF limit 200 pages. Scanned documents need OCR text. Rejected inputs are never silently truncated. |
| `POST /voyages/analyse` | JSON `{routeRequest,cargoText,documentReferences}`. `routeRequest` is the existing routing request with optional `complianceContext` declarations. Returns newline-delimited JSON, not one JSON document. |
| `POST /voyages/details` | `{analysisId,contextToken,cargoText,documentReferences,vessel}`. Adds optional declarations to the retained report and streams specialist findings without recalculating routing or retransmitting the wave grid. |
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

The runner also offers read-only `lookup_reference` for fresh public Mongo passages, and Google Search for necessary missing facts. Interactions use `store:false`, low thinking, a 3,072-token ceiling and at most two model turns, reserving the last turn for a final answer instead of another lookup. Quick screening requests zero to three short actionable findings, a one-sentence summary and at most two web sources per category. Each agent chooses its own Mongo lookups, route-detail reads and web searches. Web search is available for verification, enrichment or missing public facts even when Mongo already has evidence. Independent read-only Mongo/route lookups run concurrently, with at most four calls in one tool batch. The final turn has tools disabled. Agents are instructed to make one focused web-search batch, stop once evidence supports the essential conclusion, and return missing inputs rather than starting another investigation. Native search counts remain provider-controlled. Research stays shallow and targeted within the small tool-round budget; no exhaustive report is requested. A longer investigation is left to **Ask** chat. There is no separate agent framework, autonomous delegation, shell tool or database-write tool. Provider data-processing terms still apply.

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

MongoDB reference citations include a `downloadPath` pinned to the original GridFS file. Clicking a stored reference (including inline chat citations) downloads the exact stored PDF, HTML, CSV or other original, rather than opening the publisher's current page. `GET /compliance/documents/{fileId}/download` streams an attachment from the public `compliance_files` bucket only and verifies that its source is registered. The endpoint cannot read uploaded cargo documents or other MongoDB buckets. Ordinary web citations still open the publisher. Extracted user uploads are session-only and have no stored-original download link. A missing stored file returns 404 rather than substituting a different version.

Chat answers render validated inline citation numbers as small blue pills, with source-title tooltips and keyboard focus. Each pill links to its corresponding evidence record; stored documents download and web sources open in a new tab. Unresolved citation markers remain plain text.

Each port's issue marker opens one vertical list: congestion first, then applicable compliance findings. Evidenced yellow/red alerts retain their severity; missing-input and unverified findings are neutral list items with explicit status. Expand for short details, citations and **Ask**, which focuses the research chat. Congestion keeps **Reroute**. New findings update an open popup while retaining expanded rows. A separate rounded grey progress card at the top right shows a spinning loader with “Researching” for active categories and a green circular tick when research returns. The tick marks finished research, including results needing more details; it is not a clearance indicator. Failed checks remain marked unavailable. Detailed findings are on the ports. Route-wide findings describe voyage exposure even when displayed at an endpoint. Zero port badges is not a universal pass.

Secrets stay in ignored backend `.env` files. Defaults: `COMPLIANCE_CONCURRENCY=6`, `COMPLIANCE_MAX_ANALYSES=2`, `COMPLIANCE_MAX_CONTEXT_BYTES=3000000`, `COMPLIANCE_CALLS_PER_HOUR=60`, `CONGESTION_CALLS_PER_HOUR=20`. Budgets are process-local, not global provider spending caps. Research has no blanket elapsed deadline; network/provider/hosting failures remain possible. There is no artificial spinner delay. One local Rotterdam–Le Havre test returned route options in 11.2 seconds and all six assessments in 27.7 seconds; congestion was cached, and the five new specialists took 4.5–17.7 seconds each in parallel. This is a single observed run, not a latency guarantee.

The Worker accepts streaming NDJSON, 1 MiB analysis inputs and 11 MiB multipart envelopes, with separate stateless-chat limits. Provider credentials never enter frontend bundles. Source changes are local until the normal deployment command is run.

## Checks

```sh
python -m pytest tests/test_compliance.py tests/test_congestion.py -q
npm test
# From cloudflare/: npm test
```

Regression coverage includes parallel launch, complete-report tools, shared context, canonical ports, invented evidence/costs, historical-list rejection, effective dates, document extraction, progressive streams, session expiry and cancellation. Live provider/source checks are also required; passing fixtures establishes software behaviour rather than legal clearance or measured voyage accuracy.


## Optional details and conditional research

Security, environmental and congestion research starts with the route. With no cargo, IMO or parties supplied, dangerous-goods, tariff and identity-specific sanctions checks return `needs_input` with no model request and no findings. The progress card remains unchanged: its completion indicator means the category returned, not that a skipped check cleared the voyage; its tooltip explains the gap.

Submitting the optional dialog calls `/voyages/details` with the analysis capability and extracted text/page references. Every enabled specialist receives the complete cargo text, supplied IMO and the same compact route context. Specialists launch in parallel; the map opens without waiting for their findings. No cargo means no dangerous-goods research; an IMO enables vessel fees/sanctions research, and cargo enables goods tariffs/restrictions. A model with no IMO must not research the generic routing vessel as a known ship. New-context results replace previous category findings; late baseline results cannot overwrite them. Congestion remains attached to the original port pair.

PDF/DOCX/text uploads are extracted sequentially with 10 MiB per-file and combined 200,000-character/200-section limits. Unsupported legacy DOC/XLS files are not offered. Raw uploads, cargo text and IMO are not stored in MongoDB. Ask opens a focused chat for the selected finding. Responses render formatted paragraphs, lists and citations; the question composer stays visible while messages scroll.

### Voyage checklist and PDF export

The selected-route screen offers **Create voyage checklist**. `POST /voyages/checklist` accepts `analysisId`, `contextToken` and `routeId`; it does not retransmit the wave grid or recalculate the voyage. The browser first requests `research: false` for an immediate action preview, then starts document research with the default `research: true`. The server takes a snapshot of the latest returned category results for that voyage and preserves every applicable `recommendedAction`, including its finding, port scope, missing inputs and citations. Current mild/high congestion produces an explicitly labelled operational follow-up because the congestion response has a different schema.

A separate low-thinking document-research call receives the shared voyage brief, selected route and compiled actions. It can read Mongo references, search official web sources and inspect the complete retained report using the existing tools and bounded two-turn budget (low thinking, up to 8,192 output tokens for this document checklist). It finds relevant forms, declarations, permits, certificates and records; each result identifies its purpose, provider, timing, obtaining instructions and related action IDs. Unknown action/evidence IDs are discarded. A document cannot be labelled required without official evidence and confirmed associated findings. Unverified details stay visibly conditional or to verify. Unsupported deadlines, insurance quotes and clearance claims are prohibited in the prompt. These remain screening suggestions, not a complete determination of statutory requirements.

The dialog shows actions, document suggestions, all six categories' coverage and outstanding gaps. Select all / Deselect all toggles the actions and documents currently displayed. Checkboxes and optional notes are local to this browser session; they mean user-recorded progress, not regulatory approval. Refresh incorporates newly returned findings. If the document agent fails or is not configured, the original action checklist remains available for viewing/export and Refresh retries research. A partial snapshot explicitly identifies ongoing research.

Closing the checklist dialog does not cancel document curation or an initiated export. The browser keeps one in-flight curation job per voyage context and route; reopening displays its current preview or completed result without launching duplicate research. Checked items and notes survive closing, and late results cannot replace another route’s checklist. This is browser-session background work, not persistence across a page reload or closing the browser tab.

Snapshots remain in the existing capability-protected 30-minute in-memory voyage context, with at most six cached checklist snapshots per context. Identical concurrent requests share one research call. New findings or changed declarations generate a new snapshot. No cargo, voyage or checklist is persisted to Mongo by this feature. Source documents remain in the existing Mongo/GridFS reference store, and their citation links continue to download the original stored file.

`POST /voyages/checklist/pdf` accepts `checklistId`, `checkedItemIds`, `itemNotes`, and a compact `snapshot` of the displayed checklist. PDF formatting does not depend on the temporary research context: exports continue after expiry, RAM eviction or a backend restart. The server validates field sizes, route/checklist identity, document/action references and selected item IDs before rendering with ReportLab. This formats the displayed planning data; it does not revalidate or attest to regulatory findings. Legacy requests without a snapshot still require the original context capability. It includes all actions, documents, progress, notes, gaps, research status and linked source references. Source strings are escaped before PDF layout. Raw source passages and route grids are omitted from the export payload; citations are retained. The browser uses an attached download link and keeps a visible Download PDF link for browsers needing a second click. Export errors replace a single alert instead of accumulating repeated banners. Both endpoints are allowed through the Cloudflare gateway with CORS and no-store responses; PDF export is a binary attachment. Research refresh after context expiry requires a new route analysis, while an existing displayed checklist remains exportable. The PDF request budget at the gateway is 2 MiB.


### Checklist and document package

**Download package** calls `POST /voyages/checklist/bundle` and returns one ZIP attachment. **PDF only** retains the standalone PDF export. The package uses the same bounded display snapshot as PDF export, so an expired research context does not block it. Checked items remain progress indicators; every listed document is represented regardless of its checked state.

The ZIP includes `SmoothSail-voyage-checklist.pdf`, a `prepare-or-verify/` guide for every recommended document, identified public blank forms in `blank-forms/`, source files or readable HTML reference text in `references/`, `document-index.json`, and `README.txt`. The index maps recommendations to shared files, citations, hashes, file status and obtaining instructions. A regulatory reference is clearly distinguished from an actual vessel certificate or completed declaration. Vessel-specific certificates, policy endorsements, signed declarations and bookings must still be obtained from their issuer. No such document is fabricated.

Document research may return `downloadAssets` with an existing evidence ID and kind `blank_form` or `reference`. The backend resolves IDs through the verified evidence registry; unverified evidence cannot label a blank form. Existing cited sources are also eligible as references. The export snapshot carries these file references without raw source passages.

Files come from the registered public `compliance_files` GridFS bucket or approved HTTPS publishers. Publisher redirects are checked at every hop; cookies, API credentials and browser sessions are not forwarded. Only supported document types are included, and HTML references become readable text rather than active pages. An online portal is not relabelled as a downloaded blank form. Shared sources are deduplicated. Retrieval is bounded to four concurrent reads, forty source files, twelve MiB per file and forty-eight MiB total source content; unavailable, unsupported or over-budget files are recorded with their links and obtaining instructions. A temporary spooled archive is closed after streaming and is not persisted to Mongo. Package creation performs no new model research.

### Congestion research and route comparison

Congestion uses the same `AgentRunner` as the other specialists: low thinking, a bounded two-turn research budget, Google Search, Mongo reference lookup and read-only access to the full route report. The compact voyage brief is passed directly; the wave-display grid is not copied into prompts. Google grounding redirects are resolved before matching publisher citations. Date-only source reports retain day precision; start-of-day UTC is used conservatively for expiry, without claiming an exact observation time. Current moderate/high pressure can be supported by dated reporting up to seven days old; reporting older than 72 hours is explicitly labelled, with low confidence. A low-congestion result still needs affirmative evidence within 72 hours. Missing evidence remains unknown. Versioned Mongo and memory caches expire at the earlier of 30 minutes or evidence expiry, and unknown results retry after one minute.

The map's Fastest / Cheapest / Lowest CO₂ buttons select existing route objects without new API or model calls. Metrics, ETA, ship playback, route-scoped port findings and checklist selection follow the active route. Research remains shared across the original voyage options.

A congestion popup's **Reroute** action calls `POST /routes/reroute` with `original` (the original route request), `affectedPortId`, `alternativePortId`, and `strategy`. It preserves departure and optional vessel parameters, replaces only the affected endpoint, and returns the selected alternative route, port metadata and `onwardTransport`. It does not restart the compliance swarm or reload the global wave grid. Sampled route weather is calculated normally. The original remains pink, the alternative is `#FFEE00`, and an available road connection is dashed yellow. Original / Alternative switches change the displayed figures and playback. The alternative explicitly has no compliance assessment; original findings are not presented as its clearance.

Road transfers use the port catalogue's physical coordinates, never offshore sea-network access nodes. The fixed OSRM endpoint supplies distance, driving time and geometry, cached for 30 minutes. Departure replacement means original port → alternative; arrival replacement means alternative → original destination port. The original port is a pickup/delivery proxy because no inland address is supplied. Missing/disconnected routes return no geometry or price.

Transfer costs are a transparent planning scenario: USD 2–4 per routed kilometre plus USD 150–300 dispatch allowance, **per one standard 40-foot container, one way**. These are assumptions, not local market quotes; the cited US ATRI operating-cost benchmark is background only. They exclude handling, duties, tolls/ferries, storage/waiting, loading and empty return, and are never added to a whole-vessel sea cost. OSRM uses a car profile, so heavy-goods restrictions, borders and terminal access require confirmation. Air freight remains quote-required without weight/volume and handling information. No transfer is represented as a verified truck route or a final delivery ETA.

### TinyFish research

All shared research agents (compliance, congestion, chat and checklist documents) now use the `research_web` function backed by TinyFish Search and Fetch. Gemini chooses focused queries and writes the final structured findings; Mongo retrieval and route inspection remain available. Each tool call returns up to five search results and extracts the first two pages, with URLs and retrieval/publication metadata. Calls run concurrently within the existing four-tool, two-model-turn budget. TinyFish failures are explicit; there is no silent Google Search fallback. Existing official-source and quotation validation still applies. Configure server-only `TINYFISH_API_KEY` in the backend environment, including deployment secrets; no CLI is required in the container.
