from contextlib import asynccontextmanager
from threading import Event, Thread
import secrets

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from service.config import settings
from service.data import Repository
from service.models import RouteError, RouteRequest, RouteResponse
from service.routing import calculate


@asynccontextmanager
async def lifespan(app):
    app.state.repository = Repository(settings)
    stop = Event()
    def refresh_loop():
        from service.providers import refresh_overviews
        from service.data import connect
        import logging
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
    if app.state.repository.client:
        app.state.repository.client.close()


app = FastAPI(title='Tideline', version='0.1.0', lifespan=lifespan)


@app.get('/route-schema')
def route_schema():
    """Machine-readable contract for route-report consumers."""
    return RouteResponse.model_json_schema(by_alias=True)


@app.post('/internal/refresh', include_in_schema=False)
def refresh_sources(request: Request):
    """Private scheduled refresh; the public Worker never forwards this path."""
    expected = settings.tideline_internal_token.get_secret_value()
    supplied = request.headers.get('X-Tideline-Internal-Token', '')
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        return JSONResponse(status_code=404, content={'error': {'code': 'not_found', 'message': 'Not found.'}})
    from service.providers import refresh_overviews
    from service.data import connect
    client, db = connect(settings)
    try:
        refresh_overviews(settings, db)
    finally:
        client.close()
    return {'status': 'refresh_checked'}


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
