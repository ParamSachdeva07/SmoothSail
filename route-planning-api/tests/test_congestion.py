import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from service import congestion
from service.config import Settings
from service.congestion_models import CongestionRequest, Finding
from service.main import app

NOW = datetime.now(UTC)
SOURCE = 'https://port.example/operations'
ALT_SOURCE = 'https://alternative.example/operations'


def finding(port='NLRTM', level='high', when=NOW - timedelta(hours=2)):
    return Finding.model_validate({
        'portId': port, 'level': level, 'basis': 'reported', 'confidence': 'medium',
        'summary': 'An operator reports substantial berth delays.', 'evidenceAsOf': when,
        'sources': [{'title': 'Operator update', 'url': SOURCE, 'observedAt': when}],
        'alternativePort': {'portId': 'BEANR', 'name': 'Antwerp', 'reason': 'Operator reports low delays.',
                            'congestionLevel': 'low',
                            'source': {'title': 'Alternative update', 'url': ALT_SOURCE, 'observedAt': when}},
    })


def check(value, now=NOW, citations=None):
    return congestion.validate_finding(value, now, citations or {SOURCE, ALT_SOURCE}, [])


def config(**kwargs):
    return Settings(_env_file=None, tideline_mode='demo', gemini_api_key='test-only-key', **kwargs)


class Repo:
    def resolve_port(self, port_id):
        return SimpleNamespace(id=port_id, name=port_id, country=port_id[:2], coordinates=[4, 52])

    def nearby_ports(self, longitude, latitude, radius_nm, limit):
        return [{'id': p, 'name': p, 'distanceNm': d} for p, d in
                [('NLRTM', 0), ('BEANR', 10), ('FRLEH', 20), ('SGSIN', 30)]][:limit]


def test_qualitative_evidence_is_enough_without_invented_numbers():
    result = check(finding())
    assert result.level == 'high' and result.basis == 'reported'
    assert result.display.color == 'red' and result.display.label == 'issue'
    assert result.alternative_port is None  # Model guesses are replaced by catalogue proximity later.
    assert result.refresh_after == NOW + timedelta(minutes=30)
    assert check(finding(level='mild')).display.color == 'yellow'
    low = check(finding(level='low'))
    assert low.level == 'low' and not low.display.show_badge and low.alternative_port is None


@pytest.mark.parametrize('level', ['low', 'mild', 'high'])
@pytest.mark.parametrize('change', ['stale', 'future', 'no_citation', 'no_date', 'missing_source', 'partial_sources'])
def test_unsubstantiated_or_stale_levels_never_create_badges_or_reassurance(level, change):
    value = finding(level=level)
    citations = {SOURCE, ALT_SOURCE}
    if change == 'stale':
        value = finding(level=level, when=NOW - timedelta(hours=73))
    elif change == 'future':
        value = finding(level=level, when=NOW + timedelta(hours=1))
    elif change == 'no_citation':
        citations = {'https://unrelated.example/'}
    elif change == 'no_date':
        value.evidence_as_of = None
    elif change == 'partial_sources':
        value.sources.append(value.sources[0].model_copy(update={'url': 'https://uncited.example/'}))
    else:
        value.sources = []
    result = check(value, citations=citations)
    assert result.level == 'unknown'
    assert not result.display.show_badge and result.alternative_port is None


@pytest.mark.parametrize('change', ['same_port', 'stale', 'not_better', 'uncited'])
def test_model_alternative_is_not_used_as_the_nearest_supported_port(change):
    value = finding(level='mild')
    citations = {SOURCE, ALT_SOURCE}
    if change == 'same_port':
        value.alternative_port.port_id = 'NLRTM'
    elif change == 'stale':
        value.alternative_port.source.observed_at = NOW - timedelta(days=5)
    elif change == 'not_better':
        value.alternative_port.congestion_level = 'mild'
    else:
        citations = {SOURCE}
    result = check(value, citations=citations)
    assert result.level == 'mild' and result.alternative_port is None


def test_nearest_alternative_excludes_both_voyage_ports_and_needs_no_congestion_claim(monkeypatch):
    async def research(settings, seeds, now):
        return {s['portId']: check(finding(port=s['portId'], when=now), now) for s in seeds}
    monkeypatch.setattr(congestion, 'research', research)
    async def run():
        service = congestion.CongestionService(Repo(), config())
        result = await service.assess(CongestionRequest(port_ids=['NLRTM', 'BEANR']))
        alt = result.assessments[0].alternative_port
        assert alt.port_id == 'FRLEH' and alt.distance_nm == 20
        assert alt.congestion_level == 'unknown' and alt.source is None
        other_voyage = await service.assess(CongestionRequest(port_ids=['NLRTM', 'SGSIN']))
        assert other_voyage.assessments[0].alternative_port.port_id == 'BEANR'
        await service.close()
    asyncio.run(run())


def test_no_eligible_supported_alternative_returns_none(monkeypatch):
    repo = Repo()
    monkeypatch.setattr(repo, 'nearby_ports', lambda *args, **kwargs: [{'id': 'NLRTM', 'name': 'Rotterdam', 'distanceNm': 0}])
    async def research(settings, seeds, now):
        return {s['portId']: check(finding(port=s['portId'], when=now), now) for s in seeds}
    monkeypatch.setattr(congestion, 'research', research)
    service = congestion.CongestionService(repo, config())
    result = asyncio.run(service.assess(CongestionRequest(port_ids=['NLRTM'])))
    assert result.assessments[0].alternative_port is None


def test_cache_expires_before_evidence_crosses_freshness_limit():
    value = finding(when=NOW - timedelta(hours=71, minutes=55))
    assert check(value).refresh_after == NOW + timedelta(minutes=5)


def provider_response(value=None, status='completed', annotations=True):
    return {'status': status, 'steps': [
        {'type': 'google_search_result', 'result': [{'search_suggestions': '<div>Search attribution</div>'}]},
        {'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps({
            'assessments': [(value or finding()).model_dump(mode='json', by_alias=True)]}),
            'annotations': [{'type': 'url_citation', 'url': url} for url in (SOURCE, ALT_SOURCE)] if annotations else []}]},
    ]}


def test_provider_request_is_one_bounded_grounded_argon_call():
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['model'] == 'gemini-4-argon'
        assert body['tools'] == [{'type': 'google_search'}]
        assert body['generation_config']['thinking_level'] == 'low'
        assert body['response_format']['mime_type'] == 'application/json'
        assert request.extensions['timeout']['read'] is None
        assert request.extensions['timeout']['connect'] == 30
        assert 'test-only-key' not in request.url.query.decode()
        return httpx.Response(200, json=provider_response())
    result = asyncio.run(congestion.research(config(), [{'portId': 'NLRTM'}], NOW, httpx.MockTransport(handler)))
    assert len(calls) == 1 and result['NLRTM'].level == 'high'
    assert result['NLRTM'].search_suggestions == ['<div>Search attribution</div>']


def test_provider_json_without_tool_citations_is_unknown():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=provider_response(annotations=False)))
    result = asyncio.run(congestion.research(config(), [], NOW, transport))
    assert result['NLRTM'].level == 'unknown'


def test_incomplete_provider_output_is_rejected():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=provider_response(status='in_progress')))
    with pytest.raises(ValueError):
        asyncio.run(congestion.research(config(), [], NOW, transport))


@pytest.mark.parametrize('payload', [[], None, {'status': 'completed', 'steps': None},
                                      {'status': 'completed', 'steps': [None, {'type': 'model_output', 'content': None}]}])
def test_malformed_provider_envelope_is_rejected(payload):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(payload)))
    with pytest.raises(ValueError):
        asyncio.run(congestion.research(config(), [], NOW, transport))


def test_provider_failure_returns_sanitized_unknown(monkeypatch):
    async def failing(*args):
        raise httpx.HTTPStatusError('provider body with private key', request=httpx.Request('POST', 'https://example.org'),
                                    response=httpx.Response(403))
    monkeypatch.setattr(congestion, 'research', failing)
    service = congestion.CongestionService(Repo(), config())
    result = asyncio.run(service.assess(CongestionRequest(port_ids=['NLRTM'])))
    assert result.assessments[0].research_status == 'unavailable'
    assert 'private key' not in result.model_dump_json()


def test_missing_key_is_immediate_and_never_reads_mongo_or_calls_provider(monkeypatch):
    service = congestion.CongestionService(Repo(), Settings(_env_file=None, gemini_api_key=''))
    monkeypatch.setattr(service, 'load', lambda *args: pytest.fail('Unexpected database read'))
    result = asyncio.run(service.assess(CongestionRequest(port_ids=['NLRTM', 'SGSIN'])))
    assert all(a.level == 'unknown' and a.research_status == 'not_configured' for a in result.assessments)


def test_concurrent_pair_requests_coalesce_and_cache_preserves_callers_order(monkeypatch):
    calls = []
    async def research(settings, seeds, now):
        calls.append(seeds)
        await asyncio.sleep(0.01)
        return {s['portId']: check(finding(port=s['portId'], when=now), now) for s in seeds}
    monkeypatch.setattr(congestion, 'research', research)
    async def run():
        service = congestion.CongestionService(Repo(), config())
        a = CongestionRequest(port_ids=['NLRTM', 'SGSIN'])
        b = CongestionRequest(port_ids=['SGSIN', 'NLRTM'])
        first, second = await asyncio.gather(service.assess(a), service.assess(b))
        cached = await service.assess(a)
        assert [v.port_id for v in second.assessments] == b.port_ids
        assert not first.assessments[0].cached
        assert all(v.cached for v in cached.assessments)
        # A different request with supplied evidence cannot reuse the prior assessment blindly.
        changed = a.model_copy(update={'known_data': {'NLRTM': []}})
        assert service.key('NLRTM', changed.known_data['NLRTM']) == service.key('NLRTM', [])
        await service.close()
    asyncio.run(run())
    assert len(calls) == 1


def test_research_can_finish_after_the_previous_service_deadline(monkeypatch):
    async def slow(settings, seeds, now):
        await asyncio.sleep(21)
        finished = datetime.now(UTC)
        return {s['portId']: check(finding(port=s['portId'], when=finished), finished) for s in seeds}
    monkeypatch.setattr(congestion, 'research', slow)
    service = congestion.CongestionService(Repo(), config())
    result = asyncio.run(service.assess(CongestionRequest(port_ids=['NLRTM'])))
    assert result.assessments[0].research_status == 'completed'
    assert result.assessments[0].display.color == 'red'


def test_connection_timeouts_still_return_unknown(monkeypatch):
    async def failed_connection(*args):
        raise httpx.ConnectTimeout('Provider is unreachable')
    monkeypatch.setattr(congestion, 'research', failed_connection)
    service = congestion.CongestionService(Repo(), config())
    result = asyncio.run(service.assess(CongestionRequest(port_ids=['NLRTM'])))
    assert result.assessments[0].research_status == 'timeout'
    assert not result.assessments[0].display.show_badge


def test_shutdown_cancels_outstanding_research(monkeypatch):
    async def run():
        started = asyncio.Event()
        async def slow(*args):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(congestion, 'research', slow)
        service = congestion.CongestionService(Repo(), config())
        pending = asyncio.create_task(service.assess(CongestionRequest(port_ids=['NLRTM'])))
        await started.wait()
        await service.close()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not service.inflight
    asyncio.run(run())


def test_budget_stops_further_paid_calls(monkeypatch):
    async def research(*args):
        pytest.fail('Budget exhausted: provider must not be called')
    monkeypatch.setattr(congestion, 'research', research)
    service = congestion.CongestionService(Repo(), config(congestion_calls_per_hour=0))
    result = asyncio.run(service.assess(CongestionRequest(port_ids=['NLRTM'])))
    assert result.assessments[0].research_status == 'budget_limited'


@pytest.mark.parametrize('payload', [
    {'portIds': []}, {'portIds': ['NLRTM', 'NLRTM']}, {'portIds': ['bad']},
    {'portIds': ['NLRTM'], 'knownData': {'SGSIN': []}},
    {'portIds': ['NLRTM'], 'apiKey': 'must-not-be-accepted'},
])
def test_input_rejects_unbounded_or_unrelated_data(payload):
    with pytest.raises(ValidationError):
        CongestionRequest.model_validate(payload)


def test_http_endpoint_and_schema_work_without_key(monkeypatch):
    from pydantic import SecretStr

    from service.main import settings
    monkeypatch.setattr(settings, 'gemini_api_key', SecretStr(''))
    with TestClient(app) as client:
        response = client.post('/port-congestion', json={'portIds': ['NLRTM', 'SGSIN']})
        assert response.status_code == 200
        body = response.json()
        assert body['model'] == 'gemini-4-argon'
        assert body['assessments'][0]['display']['showBadge'] is False
        assert body['assessments'][0]['researchStatus'] == 'not_configured'
        assert '/port-congestion' in client.get('/openapi.json').json()['paths']
