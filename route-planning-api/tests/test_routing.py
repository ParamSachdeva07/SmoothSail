import time
from datetime import UTC, datetime, timedelta

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ConnectionFailure

from service.config import Settings
from service.data import Repository
from service.geo import line_geometry
from service.main import app
from service.models import RouteError, RouteRequest
from service.routing import active_notice, calculate, simulate

DEPARTURE = datetime(2026, 10, 24, tzinfo=UTC)


def test_three_strategies_and_partial_coverage_are_honest():
    repo = Repository(Settings(tideline_mode='demo'))
    result = calculate(RouteRequest(origin='NLRTM', destination='USNYC', departure_time=DEPARTURE), repo)
    fastest, economic, environmental = result.routes
    assert fastest.duration_hours <= economic.duration_hours
    assert economic.cost.fuel_tonnes < fastest.cost.fuel_tonnes
    assert economic.forecast_coverage_percent < 100
    assert economic.exposure_score is None
    assert economic.unknown_weather_hours > 0
    assert environmental.emissions.co2_tonnes <= min(r.emissions.co2_tonnes for r in result.routes)
    assert environmental.strategy == 'lowest_emissions'
    # Strategies may legitimately share geometry after land screening.
    assert result.mode == 'demo' and result.sources[0]['simulated']
    for route in result.routes:
        assert route.eta == route.segments[-1].exit_time
        assert all(a.exit_time == b.entry_time for a, b in zip(route.segments, route.segments[1:]))
    repeat = calculate(RouteRequest(origin='NLRTM', destination='USNYC', departure_time=DEPARTURE), repo)
    assert [r.model_dump() for r in result.routes] == [r.model_dump() for r in repeat.routes]


def test_missing_weather_keeps_three_strategies_but_exposure_remains_unknown():
    repo = Repository(Settings(tideline_mode='demo'))
    class Missing:
        sources = []
        def sample(self, *args):
            return dict.fromkeys(['wave', 'wind', 'u', 'v'])
        def overlays(self):
            return {'type': 'FeatureCollection', 'features': []}
    repo.forecast = lambda *args: Missing()
    result = calculate(RouteRequest(origin='PTLIS', destination='NLRTM'), repo)
    assert {r.strategy for r in result.routes} == {'fastest', 'economical', 'lowest_emissions'}
    assert not result.unavailable_strategies
    assert all(r.exposure_score is None and r.forecast_coverage_percent == 0 for r in result.routes)
    assert result.metadata.compliance_handoff.status == 'not_assessed'
    assert result.metadata.compliance_handoff.decision is None
    assert all(check.status == 'not_assessed' for check in result.metadata.compliance_handoff.checks)
    for route in result.routes:
        assert route.metadata.restriction_screening['loadedRecordCount'] == 0
        assert route.metadata.coverage['wind'].percent == 0
        assert route.metadata.unknown_intervals
        assert all(s.metadata.jurisdiction_ids is None for s in route.segments)
        assert all(s.metadata.conditions['waveHeight'].status == 'unknown' for s in route.segments)


def test_future_passage_sampling_and_fuel_use_speed_through_water():
    graph = nx.DiGraph()
    graph.add_edge('a', 'b', coordinates=[[-20, 40], [-18, 40]], passageIds=[])
    calls = []
    class Current:
        def sample(self, lon, lat, timestamp):
            calls.append(timestamp)
            return {'wave': 1, 'wind': 10, 'u': 1, 'v': 0}
    route = simulate(graph, ['a', 'b'], 16, DEPARTURE, Current(), [], time.monotonic() + 10)
    assert min(calls) > DEPARTURE and max(calls) > min(calls)
    assert route.duration_hours < route.distance_nm / 16
    assert route.cost.fuel_tonnes == pytest.approx(route.duration_hours * 41 / 24, abs=.01)


def test_notice_requires_spatial_and_temporal_overlap():
    notice = {'id': 'closed', 'geometry': {'type': 'Polygon', 'coordinates': [[[-21, 39], [-19, 39], [-19, 41], [-21, 41], [-21, 39]]]},
              'validFrom': DEPARTURE.isoformat(), 'validTo': (DEPARTURE + timedelta(hours=3)).isoformat()}
    line = line_geometry([[-22, 40], [-18, 40]])
    assert active_notice(notice, line, DEPARTURE, DEPARTURE + timedelta(hours=2), [])
    assert not active_notice(notice, line, DEPARTURE + timedelta(hours=3), DEPARTURE + timedelta(hours=5), [])
    assert not active_notice(notice, line_geometry([[-22, 45], [-18, 45]]), DEPARTURE, DEPARTURE + timedelta(hours=2), [])


def test_dateline_line_does_not_cross_the_entire_map():
    geometry = line_geometry([[179, 10], [-179, 11]])
    assert geometry['type'] == 'MultiLineString'
    assert geometry['coordinates'][0][-1][0] == 180
    assert geometry['coordinates'][1][0][0] == -180


def test_api_validation_and_redacted_database_errors():
    with TestClient(app) as client:
        assert client.post('/routes', json={'origin': 'NLRTM', 'destination': 'NLRTM'}).status_code == 422
        assert client.post('/routes', json={'origin': 'NLRTM', 'destination': 'USNYC', 'departureTime': '2026-10-24T00:00:00'}).status_code == 422
        assert client.get('/ports?q=rot').json()['ports'][0]['id'] == 'NLRTM'
        def broken(*args):
            raise ConnectionFailure('mongodb://secret-user:secret-password@private-host')
        app.state.repository.search_ports = broken
        response = client.get('/ports')
        assert response.status_code == 503
        assert 'secret' not in response.text and 'private-host' not in response.text


def test_unsupported_port_has_a_typed_error():
    with pytest.raises(RouteError, match='supported routing'):
        calculate(RouteRequest(origin='GBXXX', destination='NLRTM'), Repository(Settings(tideline_mode='demo')))


def test_agent_metadata_preserves_evidence_without_claiming_compliance():
    repo = Repository(Settings(tideline_mode='demo', mongodb_password='do-not-export-this'))
    notice = {'id': 'channel-advisory', 'name': 'Test advisory', 'action': 'review', 'verified': True,
              'passageId': 'English Channel', 'validFrom': DEPARTURE.isoformat(),
              'validTo': (DEPARTURE + timedelta(days=30)).isoformat(), 'sourceUrl': 'https://example.invalid/notice'}
    repo.restrictions = lambda: [notice]
    request = RouteRequest(origin='NLRTM', destination='PTLIS', departure_time=DEPARTURE,
                           complianceContext={'vessel': {'imoNumber': '1234567', 'flagCountryCode': 'NL', 'draftM': 10},
                                              'cargo': {'hsCodes': ['090111'], 'originCountryCode': 'NL', 'destinationCountryCode': 'PT'},
                                              'parties': [{'role': 'operator', 'name': 'Example Operator', 'countryCode': 'NL'}]})
    result = calculate(request, repo)
    assert result.schema_version == '1.4.0'
    assert result.metadata.compliance_handoff.declared_context.vessel.imo_number == '1234567'
    assert not result.metadata.compliance_handoff.declarations_used_for_routing
    assert result.metadata.vessel_model['loadedDraftM'] == 10.5
    assert result.metadata.ports['origin'].country_code == 'NL'
    assert result.metadata.restriction_catalog[0].source_url == notice['sourceUrl']
    assert 'do-not-export-this' not in result.model_dump_json()
    snapshots = {source['snapshotId'] for source in result.sources}
    for route in result.routes:
        assert len(route.metadata.content_sha256) == 64
        assert route.metadata.restriction_screening['matchedRecordIds'] == ['channel-advisory']
        assert route.metadata.forecast_snapshot_ids_used == ['illustrative-weather-v1']
        assert route.metadata.restriction_events
        assert route.compliance_status == route.metadata.compliance_status == 'not_assessed'
        for event in route.metadata.restriction_events:
            included = route.segments[event.first_segment_index:event.last_segment_index + 1]
            assert all('channel-advisory' in segment.notice_ids for segment in included)
            assert event.entry_time == included[0].entry_time and event.exit_time == included[-1].exit_time
        for index, segment in enumerate(route.segments):
            assert segment.metadata.index == index
            assert segment.metadata.start == segment.geometry['coordinates'][0]
            assert segment.entry_time <= segment.sample_time <= segment.exit_time
            assert segment.metadata.speed_over_ground_knots > 0
            for condition in segment.metadata.conditions.values():
                if condition.value is not None:
                    assert condition.status == 'simulated' and condition.snapshot_id in snapshots


def test_route_schema_exposes_metadata_contract_and_optional_input_validation():
    with TestClient(app) as client:
        response = client.get('/route-schema')
        assert response.status_code == 200
        schema = response.json()
        assert 'metadata' in schema['required']
        assert 'ComplianceHandoff' in schema['$defs']
        assert 'ConditionEvidence' in schema['$defs']
        invalid = client.post('/routes', json={'origin': 'NLRTM', 'destination': 'USNYC',
                                              'complianceContext': {'vessel': {'draftM': -5}}})
        assert invalid.status_code == 422
