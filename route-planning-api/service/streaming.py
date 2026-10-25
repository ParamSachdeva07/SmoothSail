"""Compress large reports without buffering interactive research event streams."""
from starlette.middleware.gzip import GZipMiddleware


class ResearchAwareGZipMiddleware:
    def __init__(self, app, minimum_size=2048, compresslevel=1):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        streaming = scope['type'] == 'http' and scope.get('path') in ('/voyages/analyse', '/voyages/details')
        await (self.app if streaming else self.compressed)(scope, receive, send)
