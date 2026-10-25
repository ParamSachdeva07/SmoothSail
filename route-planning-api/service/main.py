import asyncio
import json
import secrets
from contextlib import aclosing, asynccontextmanager
from threading import Event, Thread

from fastapi import FastAPI, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pymongo.errors import PyMongoError
from pypdf.errors import PyPdfError
from starlette.middleware.gzip import GZipMiddleware
from starlette.background import BackgroundTask

from service.checklist import ChecklistRequest, ChecklistExportRequest, generate as generate_checklist, export_snapshot
from service.checklist_pdf import render_pdf
from service.checklist_bundle import build_bundle
from service.compliance import ComplianceService
from service.compliance_models import ChatRequest, ChatResponse, VoyageAnalysisRequest, VoyageDetailsRequest
from service.config import settings
from service.congestion import CongestionService
from service.congestion_models import CongestionRequest, CongestionResponse
from service.data import Repository
from service.documents import MAX_UPLOAD, extract_document
from service.models import RouteError, RouteRequest, RouteResponse
from service.routing import calculate
from service.rerouting import RerouteRequest, preview_reroute


@asynccontextmanager
async def lifespan(app):
    app.state.repository = Repository(settings)
    app.state.congestion = CongestionService(app.state.repository, settings)
    app.state.compliance = ComplianceService(app.state.repository, settings, app.state.congestion)
    stop = Event()
    def refresh_loop():
        import logging

        from service.data import connect
        from service.providers import refresh_overviews
        while not stop.is_set():
            client = None
            try:
                client, db = connect(settings)
                refresh_overviews(settings, db)
            except Exception:
                logging.getLogger(__name__).warning('Forecast refresh unavailable; route coverage remains explicit.')
            finally:
                if client is not None:
                    client.close()
            stop.wait(6 * 3600)
    if settings.tideline_mode == 'mongo' and settings.auto_refresh_forecasts:
        Thread(target=refresh_loop, daemon=True, name='forecast-refresh').start()
    yield
    stop.set()
    await app.state.congestion.close()
    if app.state.repository.client:
        app.state.repository.client.close()


app = FastAPI(title='Tideline', version='0.1.0', lifespan=lifespan)
# Forecast frames compress well; keep global coastal detail affordable to send.
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=1)


@app.get('/route-schema')
def route_schema():
    """Machine-readable contract for route-report consumers."""
    return RouteResponse.model_json_schema(by_alias=True)


@app.post('/port-congestion', response_model=CongestionResponse)
async def port_congestion(body: CongestionRequest, request: Request):
    return await request.app.state.congestion.assess(body)


@app.post('/routes/reroute')
async def reroute_preview(body: RerouteRequest, request: Request):
    return JSONResponse(await preview_reroute(body, request.app.state.repository,
        request.app.state.congestion.onward), headers={'Cache-Control': 'no-store'})


@app.post('/documents/extract')
async def documents_extract(file: UploadFile):
    try:
        content = await file.read(MAX_UPLOAD + 1)
        return await asyncio.to_thread(extract_document, file.filename or 'document.txt', content)
    except (ValueError, UnicodeError, PyPdfError):
        return JSONResponse(status_code=422, content={'error': {'code': 'unreadable_document',
            'message': 'Use a readable PDF, DOCX or UTF-8 text file up to 10 MiB / 200 pages / 200,000 text characters. Scanned PDFs need OCR text.'}})
    finally:
        await file.close()


@app.post('/voyages/analyse')
async def analyse_voyage(body: VoyageAnalysisRequest, request: Request):
    async def events():
        async with aclosing(request.app.state.compliance.stream(body)) as stream:
            async for event in stream:
                yield json.dumps(event, default=str, separators=(',', ':')) + '\n'
    return StreamingResponse(events(), media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@app.post('/voyages/details')
async def voyage_details(body: VoyageDetailsRequest, request: Request):
    async def events():
        async with aclosing(request.app.state.compliance.stream_details(body)) as stream:
            async for event in stream:
                yield json.dumps(event, default=str, separators=(',', ':')) + '\n'
    return StreamingResponse(events(), media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@app.post('/compliance/chat', response_model=ChatResponse)
async def compliance_chat(body: ChatRequest, request: Request):
    return await request.app.state.compliance.chat(body)


@app.post('/voyages/checklist')
async def voyage_checklist(body: ChecklistRequest, request: Request):
    result = await generate_checklist(request.app.state.compliance, body)
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


@app.post('/voyages/checklist/pdf')
async def voyage_checklist_pdf(body: ChecklistExportRequest, request: Request):
    snapshot = export_snapshot(request.app.state.compliance, body)
    content = await asyncio.to_thread(render_pdf, snapshot, body.checked_item_ids, body.item_notes)
    return Response(content, media_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="SmoothSail-voyage-checklist.pdf"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@app.post('/voyages/checklist/bundle')
async def voyage_checklist_bundle(body: ChecklistExportRequest, request: Request):
    snapshot = export_snapshot(request.app.state.compliance, body)
    archive = await build_bundle(snapshot, body.checked_item_ids, body.item_notes, request.app.state.compliance.store)
    def chunks():
        try:
            while chunk := archive.read(256 * 1024): yield chunk
        finally:
            archive.close()
    return StreamingResponse(chunks(), media_type='application/zip', background=BackgroundTask(archive.close), headers={
        'Content-Disposition': 'attachment; filename="SmoothSail-voyage-package.zip"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@app.get('/compliance/data-status')
async def compliance_status(request: Request):
    return await asyncio.to_thread(request.app.state.compliance.store.status)


@app.get('/compliance/documents/{file_id}/download')
def download_compliance_document(file_id: str, request: Request):
    stored = request.app.state.compliance.store.download_document(file_id)
    if stored is None:
        return JSONResponse(status_code=404, content={'error': {'code': 'document_not_found',
            'message': 'The stored source document is not available.'}})
    document, filename = stored
    def chunks():
        try:
            while chunk := document.read(256 * 1024):
                yield chunk
        finally:
            document.close()
    return StreamingResponse(chunks(), media_type='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Length': str(document.length), 'X-Content-Type-Options': 'nosniff',
        'Cache-Control': 'no-store'})


@app.post('/internal/refresh', include_in_schema=False)
def refresh_sources(request: Request):
    """Private scheduled refresh; the public Worker never forwards this path."""
    expected = settings.tideline_internal_token.get_secret_value()
    supplied = request.headers.get('X-Tideline-Internal-Token', '')
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        return JSONResponse(status_code=404, content={'error': {'code': 'not_found', 'message': 'Not found.'}})
    from service.data import connect
    from service.providers import refresh_overviews
    client, db = connect(settings)
    try:
        refresh_overviews(settings, db)
    finally:
        client.close()
    return {'status': 'refresh_checked'}


@app.post('/internal/refresh-compliance', include_in_schema=False)
def refresh_compliance(request: Request):
    expected = settings.tideline_internal_token.get_secret_value()
    supplied = request.headers.get('X-Tideline-Internal-Token', '')
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        return JSONResponse(status_code=404, content={'error': {'code': 'not_found', 'message': 'Not found.'}})
    from scripts.ingest_compliance import refresh_sources, refresh_structured
    from service.compliance_data import ensure_compliance_indexes
    db = request.app.state.repository.database()
    ensure_compliance_indexes(db)
    async def refresh():
        return await refresh_sources(db) + await refresh_structured(db)
    return {'sources': asyncio.run(refresh())}


@app.exception_handler(RouteError)
async def route_error(request: Request, error: RouteError):
    return JSONResponse(status_code=error.status, content={'error': {'code': error.code, 'message': error.message}})


@app.exception_handler(PyMongoError)
async def mongo_error(request: Request, error: PyMongoError):
    # Driver messages may include connection details; never forward them to the client.
    return JSONResponse(status_code=503, content={'error': {'code': 'database_unavailable', 'message': 'MongoDB is unavailable. Check the server configuration.'}})


@app.get('/health')
def health(request: Request):
    return request.app.state.repository.health()


@app.get('/data-status')
def data_status(request: Request):
    return request.app.state.repository.data_status()


@app.get('/ports')
def ports(request: Request, q: str = Query(default='', max_length=80), limit: int = Query(default=20, ge=1, le=50)):
    return {'ports': [p.model_dump(by_alias=True) for p in request.app.state.repository.search_ports(q, limit)]}


@app.post('/routes', response_model=RouteResponse)
def routes(body: RouteRequest, request: Request, response: Response):
    result = calculate(body, request.app.state.repository)
    response.headers['Server-Timing'] = ', '.join(
        f'{name};dur={seconds * 1000:.2f}' for name, seconds in result.metadata.phase_seconds.items())
    return result


@app.get('/ports/nearby')
def nearby_ports(request: Request, longitude: float = Query(ge=-180, le=180),
                 latitude: float = Query(ge=-85, le=85), radius_nm: float = Query(default=100, gt=0, le=2000),
                 limit: int = Query(default=20, ge=1, le=50)):
    return {'ports': request.app.state.repository.nearby_ports(longitude, latitude, radius_nm, limit),
            'distanceBasis': 'spherical proximity to supported offshore approach points; not sailing distance'}
