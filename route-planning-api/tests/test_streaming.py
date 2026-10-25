import asyncio
import pytest
from service.streaming import ResearchAwareGZipMiddleware


@pytest.mark.parametrize('path', ['/voyages/analyse', '/voyages/details'])
def test_assessment_delivered_while_research_still_running(path):
    async def run():
        delivered, finish = asyncio.Event(), asyncio.Event()
        messages = []
        event = b'{"type":"assessment","category":"environment","findings":[]}\n'
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'application/x-ndjson')]})
            await send({'type': 'http.response.body', 'body': event, 'more_body': True})
            await finish.wait()
            await send({'type': 'http.response.body', 'body': b'{"type":"complete"}\n', 'more_body': False})
        async def send(message):
            messages.append(message)
            if message.get('body') == event: delivered.set()
        async def receive(): return {'type': 'http.disconnect'}
        task = asyncio.create_task(ResearchAwareGZipMiddleware(app)({'type': 'http', 'path': path, 'headers': [(b'accept-encoding', b'gzip')]}, receive, send))
        try:
            await asyncio.wait_for(delivered.wait(), 1)
            assert not task.done()
            assert not any(k == b'content-encoding' for k, v in messages[0]['headers'])
        finally:
            finish.set()
            await task
    asyncio.run(run())


def test_regular_reports_still_compressed():
    async def run():
        messages = []
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'x' * 5000})
        async def receive(): return {'type': 'http.disconnect'}
        async def send(message): messages.append(message)
        await ResearchAwareGZipMiddleware(app)({'type': 'http', 'path': '/routes', 'headers': [(b'accept-encoding', b'gzip')]}, receive, send)
        assert (b'content-encoding', b'gzip') in messages[0]['headers']
    asyncio.run(run())
