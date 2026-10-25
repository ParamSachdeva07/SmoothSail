import asyncio
import httpx
from service.config import Settings
from service.tinyfish_research import research


def test_search_fetch_preserves_citations_and_limits_pages():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers['X-API-Key'] == 'test-key'
        if request.method == 'GET':
            return httpx.Response(200, json={'results': [{'url': f'https://www.imo.org/{i}', 'snippet': 'A rule', 'date': '2026-10-25'} for i in range(8)]})
        import json
        assert len(json.loads(request.content)['urls']) == 2
        return httpx.Response(200, json={'results': [{'url': 'https://www.imo.org/0', 'text': 'Verified rule text', 'published_date': '2026-10-25'}], 'errors': []})
    result = asyncio.run(research(Settings(tinyfish_api_key='test-key'), 'IMO emissions', httpx.MockTransport(handler)))
    assert len(calls) == 2 and len(result['sources']) == 5
    assert result['sources'][0]['text'] == 'Verified rule text'
    assert result['sources'][0]['publishedDate'] == '2026-10-25'


def test_missing_credentials_and_rate_limit_are_explicit():
    missing = asyncio.run(research(Settings(tinyfish_api_key=''), 'port congestion'))
    assert missing['sources'] == [] and 'not configured' in missing['error']
    limited = asyncio.run(research(Settings(tinyfish_api_key='test'), 'port congestion', httpx.MockTransport(lambda _: httpx.Response(429))))
    assert limited['sources'] == [] and 'rate limited' in limited['error']


def test_failed_page_fetch_retains_snippets_with_warning():
    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'results': [{'url': 'https://imo.org/rule', 'snippet': 'Search only'}]})
        return httpx.Response(503)
    result = asyncio.run(research(Settings(tinyfish_api_key='test'), 'IMO rules', httpx.MockTransport(handler)))
    assert result['sources'][0]['snippet'] == 'Search only'
    assert 'snippets only' in result['note']


def test_runner_uses_tinyfish_function_and_collects_citation_urls():
    import json
    from service.compliance_agents import AgentRunner
    from service.checklist import DocumentResearch
    turns = []
    def handler(request):
        if request.url.host == 'api.search.tinyfish.ai':
            return httpx.Response(200, json={'results': [{'url': 'https://www.imo.org/rule', 'snippet': 'Official rule'}]})
        if request.url.host == 'api.fetch.tinyfish.ai':
            return httpx.Response(200, json={'results': [{'url': 'https://www.imo.org/rule', 'text': 'Official rule text'}], 'errors': []})
        body = json.loads(request.content); turns.append(body)
        if len(turns) == 1:
            assert not any(t.get('type') == 'google_search' for t in body['tools'])
            return httpx.Response(200, json={'status': 'requires_action', 'steps': [{'type': 'function_call', 'name': 'research_web', 'id': 'web1', 'arguments': {'query': 'IMO rules'}}]})
        result = next(s for s in body['input'] if s['type'] == 'function_result')
        assert json.loads(result['result'][0]['text'])['sources'][0]['text'] == 'Official rule text'
        return httpx.Response(200, json={'status': 'completed', 'steps': [{'type': 'model_output', 'content': [{'type': 'text', 'text': '{"documents":[],"gaps":[],"webEvidence":[]}'}]}]})
    runner = AgentRunner(Settings(gemini_api_key='test', tinyfish_api_key='test'), httpx.MockTransport(handler))
    _, citations = asyncio.run(runner.invoke('Check docs', '{}', {}, DocumentResearch))
    assert 'https://www.imo.org/rule' in citations
    assert len(turns) == 2
