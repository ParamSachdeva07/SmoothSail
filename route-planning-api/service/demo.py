import math
from datetime import timedelta

import networkx as nx

from service.geo import circle, distance_nm
from service.models import Port


def demo_network():
    from service.navigation import default_land_mask
    nodes = {
        'rotterdam': (3.7, 51.95), 'dover': (1.55, 50.9), 'channel': (-2.5, 49.7),
        'brest': (-6.5, 48.5), 'lisbon': (-9.7, 38.65), 'iberia': (-12, 42),
        'newyork': (-73.55, 40.25), 'approach': (-70.5, 39.0),
        'halifax': (-63.1, 44.1), 'shelf': (-60.0, 41.0),
    }
    for row, lat in enumerate([35, 39, 43, 47, 51]):
        for col, lon in enumerate([-58, -48, -38, -28, -18]):
            nodes[f'o{row}_{col}'] = (lon, lat)
    graph = nx.DiGraph()
    for node, coordinate in nodes.items():
        graph.add_node(node, coordinates=coordinate)

    def connect(a, b, passage=None):
        for origin, destination in [(a, b), (b, a)]:
            graph.add_edge(origin, destination, distanceNm=distance_nm(nodes[a], nodes[b]),
                           coordinates=[nodes[origin], nodes[destination]], passageIds=[passage] if passage else [])

    for a, b in [('rotterdam', 'dover'), ('dover', 'channel'), ('channel', 'brest'),
                 ('lisbon', 'iberia'), ('iberia', 'brest'), ('newyork', 'approach'),
                 ('approach', 'shelf'), ('halifax', 'shelf')]:
        connect(a, b, 'English Channel' if a == 'dover' else None)
    for row in range(5):
        connect('brest', f'o{row}_4')
        connect('iberia', f'o{row}_4')
        connect('shelf', f'o{row}_0')
        for col in range(4):
            for next_row in range(max(0, row - 1), min(5, row + 2)):
                connect(f'o{row}_{col}', f'o{next_row}_{col + 1}')
    ports = [
        Port(id='NLRTM', name='Rotterdam', country='Netherlands', coordinates=nodes['rotterdam'], routing_node_id='rotterdam'),
        Port(id='USNYC', name='New York', country='United States', coordinates=nodes['newyork'], routing_node_id='newyork'),
        Port(id='PTLIS', name='Lisbon', country='Portugal', coordinates=nodes['lisbon'], routing_node_id='lisbon'),
        Port(id='CAHAL', name='Halifax', country='Canada', coordinates=nodes['halifax'], routing_node_id='halifax'),
    ]
    default_land_mask().remove_crossings(graph)
    return graph, ports


class DemoForecast:
    """Analytic fixture, deliberately labelled as simulated in every response."""
    def __init__(self, departure):
        self.departure = departure
        self.sources = [{'name': 'Illustrative weather scenario', 'snapshotId': 'illustrative-weather-v1', 'retrievedAt': departure.isoformat(),
                         'validUntil': (departure + timedelta(days=10)).isoformat(), 'simulated': True}]

    def sample(self, lon, lat, time):
        hours = (time - self.departure).total_seconds() / 3600
        if not 0 <= hours <= 240:
            return {'wave': None, 'wind': None, 'u': None, 'v': None}
        centre = -40 + hours * 0.035
        storm = math.exp(-(((lon - centre) / 8)**2 + ((lat - 45) / 3.3)**2))
        return {'wave': 1.15 + 5.1 * storm, 'wind': 10 + 30 * storm,
                'u': 0.65 * math.exp(-((lat - 38) / 3)**2), 'v': 0.12 * math.sin(lon / 8)}

    def sample_with_provenance(self, lon, lat, time):
        values = self.sample(lon, lat, time)
        return values, {key: 'illustrative-weather-v1' for key, value in values.items() if value is not None}

    def overlays(self, bounds=None):
        features = []
        for hour in range(0, 241, 24):
            features.append({'type': 'Feature', 'geometry': circle(-40 + hour * .035, 45, 230),
                             'properties': {'kind': 'rough_seas', 'name': 'Simulated rough-sea area',
                                            'hour': hour, 'validAt': (self.departure + timedelta(hours=hour)).isoformat(),
                                            'simulated': True}})
        return {'type': 'FeatureCollection', 'features': features}
