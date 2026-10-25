import asyncio
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from service.onward_transport import OnwardTransport
from service.rerouting import RerouteRequest, preview_reroute
from service.congestion import validate_finding, research
from service.congestion_models import Finding, ResearchOutput
from service.config import Settings


class Repo:
    def port_land_coordinates(self, port):
        return [4.2, 51.9] if port == 'NLRTM' else [4.4, 51.2]


def test_road_cost_uses_routed_distance_once_and_is_never_a_whole_vessel_quote():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'code': 'Ok', 'routes': [{'distance': 120000, 'duration': 7200,
            'geometry': {'type': 'LineString', 'coordinates': [[4.2, 51.9], [4.4, 51.2]]}}]})
    async def run():
        service = OnwardTransport(Repo(), httpx.MockTransport(respond))
        a, b = await asyncio.gather(service.estimate('NLRTM', 'BEANR'), service.estimate('NLRTM', 'BEANR'))
        assert a == b and len(requests) == 1
        assert a['cost']['low'] == 390 and a['cost']['high'] == 780
        assert a['cost']['basis'] == 'per_40ft_container_one_way' and not a['cost']['isQuote']
        assert a['drivingHours'] == 2 and a['air']['cost'] is None
    asyncio.run(run())


def test_no_road_connection_never_becomes_a_straight_line_or_fake_price():
    service = OnwardTransport(Repo(), httpx.MockTransport(lambda _: httpx.Response(200, json={'code': 'NoRoute'})))
    result = asyncio.run(service.estimate('NLRTM', 'SGSIN'))
    assert result['status'] == 'unavailable' and result['geometry'] is None and result['cost'] is None


@pytest.mark.parametrize('affected,direction', [('NLRTM', ('NLRTM', 'BEANR')), ('SGSIN', ('BEANR', 'SGSIN'))])
def test_reroute_keeps_vessel_settings_and_only_changes_one_endpoint(affected, direction):
    original = {'origin': 'NLRTM', 'destination': 'SGSIN', 'departureTime': '2026-10-25T03:00:00Z',
        'vesselParameters': {'fuelUsdPerTonne': 700}}
    body = RerouteRequest(original=original, affectedPortId=affected, alternativePortId='BEANR', strategy='economical')
    calls = []
    def calculate(request, repo, *, include_display):
        calls.append(request)
        assert include_display is False
        assert request.vessel_parameters.fuel_usd_per_tonne == 700
        route = SimpleNamespace(strategy='economical', model_dump=lambda **_: {'id': 'alt', 'strategy': 'economical'})
        return SimpleNamespace(routes=[route], origin=request.origin, destination=request.destination,
            metadata=SimpleNamespace(ports={'origin': SimpleNamespace(model_dump=lambda **_: {'locode': request.origin})}))
    async def estimate(origin, destination):
        assert (origin, destination) == direction
        return {'status': 'unavailable', 'cost': None}
    result = asyncio.run(preview_reroute(body, Repo(), SimpleNamespace(estimate=estimate), calculator=calculate))
    assert result['ports']['origin']['locode'] == result['origin']
    assert result['route']['id'] == 'alt' and result['complianceStatus'] == 'not_assessed'
    assert original['origin'] == 'NLRTM' and original['destination'] == 'SGSIN'
    assert len(calls) == 1


def test_reroute_rejects_unrelated_or_identical_endpoints():
    for affected, alternative in [('USLAX', 'BEANR'), ('NLRTM', 'SGSIN')]:
        with pytest.raises(ValidationError): RerouteRequest(original={'origin': 'NLRTM', 'destination': 'SGSIN'},
            affectedPortId=affected, alternativePortId=alternative)


def test_recent_weekly_report_can_support_pressure_but_not_old_normal_operation():
    now = datetime.now(UTC); date = now - timedelta(days=5); url = 'https://example.com/port-report'
    finding = Finding(portId='NLRTM', level='mild', basis='reported', confidence='medium',
        summary='The latest weekly report describes berth delays.', evidenceAsOf=date,
        sources=[{'title': 'Weekly report', 'url': url, 'publishedAt': date,
            'supportingPassage': 'Current berth congestion causes moderate waiting times.'}])
    result = validate_finding(finding, now, {url}, [])
    assert result.level == 'mild' and result.evidence_window_hours == 168 and result.confidence == 'low'
    assert validate_finding(finding.model_copy(update={'level': 'low'}), now, {url}, []).level == 'unknown'


def test_congestion_shared_runner_receives_context_and_resolves_grounding_redirect():
    now = datetime.now(UTC); redirect = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/example'
    target = 'https://port.example/current'; report = {'routes': [{'id': 'original'}]}
    class Runner:
        async def invoke(self, prompt, shared, extra, schema, **kwargs):
            assert kwargs['report'] is report and 'NLRTM' in shared
            return ResearchOutput(assessments=[{'portId': 'NLRTM', 'level': 'high', 'basis': 'reported',
                'confidence': 'medium', 'summary': 'Severe queues reported.', 'evidenceAsOf': now,
                'sources': [{'title': 'Port update', 'url': target, 'observedAt': now}]}]), {redirect}
    transport = httpx.MockTransport(lambda _: httpx.Response(302, headers={'location': target}))
    result = asyncio.run(research(Settings(_env_file=None), [{'completeVoyageContext': {'origin': 'NLRTM'}}], now,
        transport=transport, runner=Runner(), report=report))
    assert result['NLRTM'].level == 'high'


def test_date_only_provider_reports_do_not_fail_or_invent_precise_observation_times():
    day = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    output = ResearchOutput.model_validate({'assessments': [{'portId': 'NLRTM', 'level': 'mild', 'basis': 'reported', 'confidence': 'medium',
        'summary': 'The dated report describes delays.', 'evidenceAsOf': day,
        'sources': [{'title': 'Dated report', 'url': 'https://example.com/report', 'publishedAt': day,
            'supportingPassage': 'Berthing delays continue.'}]}]})
    finding = output.assessments[0]
    assert finding.date_precision == 'day' and finding.sources[0].date_precision == 'day'
    assert finding.evidence_as_of.hour == 0 and finding.evidence_as_of.tzinfo == UTC
    result = validate_finding(finding, datetime.now(UTC), {'https://example.com/report'}, [])
    assert result.level == 'mild' and any('calendar date' in note for note in result.quality_notes)


def test_missing_landside_coordinates_do_not_snap_an_offshore_point_to_a_road():
    class Missing:
        def port_land_coordinates(self, _): return None
    service = OnwardTransport(Missing(), httpx.MockTransport(lambda _: pytest.fail('No road request without landside coordinates')))
    result = asyncio.run(service.estimate('NLRTM', 'SGSIN'))
    assert result['geometry'] is None and result['cost'] is None
