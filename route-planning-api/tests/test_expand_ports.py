import networkx as nx
from scipy.spatial import cKDTree
from shapely.geometry import Polygon

from scripts.expand_ports import prepare_candidate, unit_vector, wpi_index
from service.navigation import LandMask


def test_expansion_chooses_safe_approach_instead_of_nearest_land_crossing_node():
    graph = nx.DiGraph()
    points = {'near': [0, 0], 'unsafe_exit': [0.1, 0],
              'safe': [0, 0.1], 'safe_exit': [0, 0.2]}
    for key, coordinates in points.items():
        graph.add_node(key, coordinates=coordinates)
    graph.add_edge('near', 'unsafe_exit', sourceEdgeId='land', coordinates=[[0, 0], [0.1, 0]])
    graph.add_edge('safe', 'safe_exit', sourceEdgeId='sea', coordinates=[[0, 0.1], [0, 0.2]])
    mask = LandMask([Polygon([(0.04, -0.01), (0.06, -0.01), (0.06, 0.01), (0.04, 0.01)])])
    nodes = list(points)
    tree = cKDTree([unit_vector(points[node]) for node in nodes])
    source = {'features': [{'country': 'XX', 'port_name': 'Test Port', 'longitude': 0,
                            'latitude': 0, 'objectid': 1}]}
    record = {'locode': 'XXTST', 'name': 'Test Port', 'country': 'XX',
              'location': {'coordinates': [0, 0]}}

    access, reason = prepare_candidate(record, wpi_index(source), nodes, tree, graph,
                                       mask, set(), {})

    assert reason is None
    assert access['nodeId'] == 'safe'
    assert access['offsetNm'] < 15
