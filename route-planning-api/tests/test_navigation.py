from datetime import UTC, datetime

import networkx as nx
import pytest
from shapely.geometry import shape

from service.config import Settings
from service.data import Repository
from service.models import RouteRequest
from service.geo import densify, distance_nm, line_geometry
from service.navigation import LandMask, connect_dateline, default_land_mask, exclude_unsupported_passages
from service.routing import calculate


def test_thin_island_blocks_an_edge_even_with_water_endpoints():
    mask = LandMask([{'type': 'Polygon', 'coordinates': [[[-20.02, 39], [-19.98, 39],
                     [-19.98, 41], [-20.02, 41], [-20.02, 39]]]}])
    assert mask.intersects([[-21, 40], [-19, 40]])
    assert not mask.intersects([[-21, 42], [-19, 42]])


def test_every_returned_demo_route_stays_out_of_detailed_land_mask():
    repository = Repository(Settings(tideline_mode='demo'))
    result = calculate(RouteRequest(origin='NLRTM', destination='USNYC',
                       departure_time=datetime(2026, 10, 24, tzinfo=UTC)), repository)
    mask = default_land_mask()
    for route in result.routes:
        assert not len(mask.tree.query(shape(route.geometry), predicate='intersects'))
        assert max(segment.distance_nm for segment in route.segments) <= 10.001


def test_dateline_crossing_does_not_hit_unrelated_land():
    mask = LandMask([{'type': 'Polygon', 'coordinates': [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]]}])
    assert not mask.intersects([[179, 0], [-179, 0]])


@pytest.mark.parametrize('reverse', [False, True])
def test_searoute_dateline_seam_connects_pacific_without_world_spanning_lines(reverse):
    graph = nx.DiGraph()
    points = {'tokyo_side': [179, 30], 'east': [180, 30], 'west': [-180, 30], 'la_side': [-179, 30]}
    for node, point in points.items():
        graph.add_node(node, coordinates=point)
    for a, b in [('tokyo_side', 'east'), ('west', 'la_side')]:
        for x, y in [(a, b), (b, a)]:
            graph.add_edge(x, y, distanceNm=distance_nm(points[x], points[y]), coordinates=[points[x], points[y]])
    assert not nx.has_path(graph, 'tokyo_side', 'la_side')
    assert connect_dateline(graph) == 1
    start, end = ('la_side', 'tokyo_side') if reverse else ('tokyo_side', 'la_side')
    path = nx.shortest_path(graph, start, end, weight='distanceNm')
    assert nx.path_weight(graph, path, 'distanceNm') < 110
    coords = densify([points[node] for node in path])
    geometry = line_geometry(coords)
    assert geometry['type'] == 'MultiLineString'
    assert shape(geometry).is_valid
    assert all(abs(a[0] - b[0]) <= 180 for part in geometry['coordinates'] for a, b in zip(part, part[1:]))
    assert not default_land_mask().intersects([[180, 30], [-180, 30]])


def test_dateline_nodes_at_different_latitudes_are_not_connected():
    graph = nx.Graph()
    graph.add_node('east', coordinates=[180, 30])
    graph.add_node('west', coordinates=[-180, 31])
    assert connect_dateline(graph) == 0
    assert not nx.has_path(graph, 'east', 'west')


def test_generic_ship_cannot_take_an_arctic_shortcut():
    graph = nx.DiGraph()
    graph.add_edge('europe', 'asia', distanceNm=7000, passageIds=['northeast'])
    graph.add_edge('europe', 'cape', distanceNm=6000, passageIds=[])
    graph.add_edge('cape', 'asia', distanceNm=6000, passageIds=[])
    graph.add_edge('atlantic', 'pacific', distanceNm=7000, passageIds=['northwest'])
    assert exclude_unsupported_passages(graph) == 2
    assert nx.shortest_path(graph, 'europe', 'asia', weight='distanceNm') == ['europe', 'cape', 'asia']
