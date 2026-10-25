"""Bounded TinyFish search + page extraction for the shared agent runner."""
import asyncio
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

TOOL = {'type': 'function', 'name': 'research_web',
    'description': 'Search public web information using TinyFish and read the top two pages. Returns URLs, dated snippets and page text for citations. Use focused public regulatory or port terms, never private cargo documents or secrets.',
    'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}


def public_url(value):
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except (TypeError, ValueError):
        return False


async def research(settings, query, transport=None):
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 600:
        return {'provider': 'tinyfish', 'error': 'Use a focused query of 3–600 characters.', 'sources': []}
    key = settings.tinyfish_api_key.get_secret_value()
    if not key:
        return {'provider': 'tinyfish', 'error': 'TinyFish is not configured. Web research unavailable.', 'sources': []}
    try:
        async with asyncio.timeout(35), httpx.AsyncClient(timeout=30, transport=transport) as client:
            headers = {'X-API-Key': key}
            response = await client.get('https://api.search.tinyfish.ai', params={'query': query}, headers=headers)
            response.raise_for_status()
            rows = response.json().get('results', [])[:5]
            sources = [{k: row.get(k) for k in ('url', 'title', 'snippet', 'date')} for row in rows if public_url(row.get('url'))]
            result = {'provider': 'tinyfish', 'retrievedAt': datetime.now(UTC).isoformat(), 'sources': sources}
            if sources:
                try:
                    fetched = await client.post('https://api.fetch.tinyfish.ai', headers=headers,
                        json={'urls': [s['url'] for s in sources[:2]], 'format': 'markdown', 'per_url_timeout_ms': 10000})
                    fetched.raise_for_status()
                    pages = {p['url']: p for p in fetched.json().get('results', [])}
                    for source in sources:
                        page = pages.get(source['url'])
                        if page:
                            source['text'] = (page.get('text') or '')[:12000]
                            source['publishedDate'] = page.get('published_date')
                    if fetched.json().get('errors'):
                        result['note'] = 'Some pages could not be read; snippets alone do not verify a claim.'
                except (httpx.HTTPError, ValueError):
                    result['note'] = 'Page extraction unavailable; these are search snippets only.'
            return result
    except (httpx.HTTPError, TimeoutError, ValueError):
        return {'provider': 'tinyfish', 'error': 'TinyFish research unavailable or rate limited. Do not infer clearance or absence of congestion.', 'sources': []}
