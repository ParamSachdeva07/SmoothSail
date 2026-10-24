import time
from datetime import UTC, datetime, timedelta

import networkx as nx
import pytest

from service.canals import catalog, coordinate_hash, decorate_graph, is_reviewed_canal_edge, toll
from service.config import Settings
from service.costs import vessel_model
from service.data import Repository
from service.forecast import GridForecast
from service.geo import distance_nm
from service.models import Port, RouteRequest
from service.navigation import LandMask
from service.routing import calculate, simulate

DEPARTURE = datetime(2026, 10, 24, tzinfo=UTC)


def canal_graph(cid='panama'):
    graph = nx.DiGraph()
    for edge_id, edge in catalog()['canals'][cid]['reviewedEdges'].items():
        a, b = edge['from'], edge['to']
        coords = edge['coordinates']
        graph.add_node(a, coordinates=coords[0])
        graph.add_node(b, coordinates=coords[-1])
        nm = sum(distance_nm(x, y) for x, y in zip(coords, coords[1:]))
        for start, end, points in [(a, b, coords), (b, a, coords[::-1])]:
            graph.add_edge(start, end, sourceEdgeId=edge_id, passageIds=[cid], coordinates=points, distanceNm=nm)
    decorate_graph(graph)
    ends = [n for n in graph if graph.out_degree(n) == 1]
    return graph, ends


def test_only_exact_reviewed_geometry_can_bypass_land():
    graph, ends = canal_graph()
    a = ends[0]
    b = next(iter(graph[a]))
    edge = graph[a][b]
    assert is_reviewed_canal_edge(edge)
    assert coordinate_hash(edge['coordinates']) == coordinate_hash(edge['coordinates'][::-1])
    assert not is_reviewed_canal_edge(dict(edge, coordinates=[[-80, 8], [-70, 20]]))
    assert not is_reviewed_canal_edge(dict(edge, sourceEdgeId='unreviewed'))
    mask = LandMask([{'type': 'Polygon', 'coordinates': [[[-100, -10], [-60, -10], [-60, 30], [-100, 30], [-100, -10]]]}])
    graph.add_edge('bad-a', 'bad-b', coordinates=[[-80, 8], [-70, 20]], passageIds=['panama'])
    assert mask.remove_crossings(graph) == 1
    assert graph.has_edge(a, b)


@pytest.mark.parametrize('reverse', [False, True])
def test_multi_edge_panama_is_charged_once_and_time_is_continuous(reverse):
    graph, ends = canal_graph()
    if reverse:
        ends.reverse()
    path = nx.shortest_path(graph, *ends, weight='distanceNm')
    route = simulate(graph, path, 16, DEPARTURE, GridForecast([]), [], time.monotonic() + 10)
    assert len(route.canal_transits) == 1
    assert route.waiting_hours == 24
    assert route.canal_hours == pytest.approx(10, abs=.005)
    assert route.duration_hours == pytest.approx(34, abs=.01)
    assert route.cost.canal_tolls_usd == 340100
    assert route.cost.time_usd == pytest.approx(34 / 24 * 18000, abs=1)
    assert route.cost.total_usd == pytest.approx(route.cost.fuel_usd + route.cost.time_usd + 340100 + 15000)
    assert sum(s.fuel_tonnes for s in route.segments) == pytest.approx(route.cost.fuel_tonnes, abs=.00001)
    assert route.segments[0].kind == 'canal_wait'
    assert all(a.exit_time == b.entry_time for a, b in zip(route.segments, route.segments[1:]))
    assert all(s.entry_time <= s.sample_time <= s.exit_time for s in route.segments)
    assert route.eta == route.canal_transits[0].exit_time


def test_suez_known_surcharge_uses_effective_date():
    model = vessel_model()
    old = toll('suez', model, datetime(2026, 7, 14, tzinfo=UTC))
    current = toll('suez', model, DEPARTURE)
    assert old['amountUsd'] == 260955
    assert current['amountUsd'] == pytest.approx(old['amountUsd'] * 1.12)
    assert len(current['items']) == 2


def test_closure_starting_during_canal_wait_blocks_transit():
    graph, ends = canal_graph()
    path = nx.shortest_path(graph, *ends, weight='distanceNm')
    notice = {'id': 'closure', 'passageId': 'panama', 'verified': True, 'action': 'exclude',
              'validFrom': DEPARTURE + timedelta(hours=12), 'validTo': DEPARTURE + timedelta(days=2)}
    assert simulate(graph, path, 16, DEPARTURE, GridForecast([]), [notice], time.monotonic() + 10) is None


def test_economical_can_choose_longer_canal_free_route_without_extra_inputs():
    repo = Repository(Settings(tideline_mode='demo'))
    graph, ends = canal_graph()
    a, b = ends
    midpoint = [-92, 9]
    graph.add_node('ocean-detour', coordinates=midpoint)
    for start, end in [(a, 'ocean-detour'), ('ocean-detour', b)]:
        points = [graph.nodes[start]['coordinates'], graph.nodes[end]['coordinates']]
        graph.add_edge(start, end, coordinates=points, distanceNm=distance_nm(*points), passageIds=[])
    repo.graph = graph
    repo.ports = [Port(id='NLRTM', name='Test A', country='NL', coordinates=graph.nodes[a]['coordinates'], routing_node_id=a),
                  Port(id='USNYC', name='Test B', country='US', coordinates=graph.nodes[b]['coordinates'], routing_node_id=b)]
    class Empty(GridForecast):
        def overlays(self):
            return {'type': 'FeatureCollection', 'features': []}
    repo.forecast = lambda *args: Empty([])
    result = calculate(RouteRequest(origin='NLRTM', destination='USNYC', departure_time=DEPARTURE), repo)
    fastest, economical, environmental = result.routes
    assert fastest.canal_transits
    assert not economical.canal_transits
    assert economical.distance_nm > fastest.distance_nm
    assert economical.cost.total_usd < fastest.cost.total_usd
    assert economical.duration_hours > fastest.duration_hours
    assert environmental.canal_transits
    assert environmental.emissions.co2_tonnes < economical.emissions.co2_tonnes
