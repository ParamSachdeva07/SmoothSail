"""Conservative land screening shared by imports, demo routes and verification."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from shapely import STRtree, prepare, intersects, from_wkb
from shapely.geometry import shape

from service.geo import densify, line_geometry
from service.references import active_references

LAND_FILE = Path(__file__).resolve().parents[1] / 'data/geography/land.geojson'
DETAIL_FILE = Path(__file__).resolve().parents[1] / 'data/geography/gshhg-h.wkb.json'
EXCLUDED_PASSAGES = frozenset({'northeast', 'northwest', 'kiel', 'corinth'})


def exclude_unsupported_passages(graph):
    """The generic cargo model does not assume polar operating capability."""
    edges = [(a, b) for a, b, edge in graph.edges(data=True)
             if EXCLUDED_PASSAGES.intersection(edge.get('passageIds', []))]
    graph.remove_edges_from(edges)
    return len(edges)


def connect_dateline(graph):
    """Restore SeaRoute's runtime links between identical +/-180° nodes.

    These links are created by SeaRoute Java, not stored in its GeoPackage.
    Only exactly paired latitudes are connected; no ocean shortcuts are added.
    """
    east, west = {}, {}
    for node, data in graph.nodes(data=True):
        lon, lat = data['coordinates']
        if lon == 180:
            east[lat] = node
        elif lon == -180:
            west[lat] = node
    for lat in east.keys() & west.keys():
        a, b = east[lat], west[lat]
        graph.add_edge(a, b, distanceNm=0.0, coordinates=[[180, lat], [-180, lat]],
                       passageIds=[], datelineSeam=True)
        if graph.is_directed():
            graph.add_edge(b, a, distanceNm=0.0, coordinates=[[-180, lat], [180, lat]],
                           passageIds=[], datelineSeam=True)
    return len(east.keys() & west.keys())


class LandMask:
    def __init__(self, geometries):
        polygons = []
        for geometry in geometries:
            geom = shape(geometry) if isinstance(geometry, dict) else geometry
            polygons.extend(list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom])
        self.tree = STRtree(polygons)
        self.polygons = self.tree.geometries
        prepare(self.polygons)

    def intersects(self, coordinates):
        # Match the geodesic segments actually returned/rendered by the simulator.
        geometry = shape(line_geometry(densify(coordinates, max_nm=10)))
        candidates = self.tree.query(geometry)
        return bool(intersects(self.polygons[candidates], geometry).any())

    def remove_crossings(self, graph):
        from service.canals import is_reviewed_canal_edge
        excluded = [(a, b) for a, b, edge in graph.edges(data=True)
                    if not is_reviewed_canal_edge(edge) and self.intersects(edge['coordinates'])]
        graph.remove_edges_from(excluded)
        return len(excluded)


def default_land_mask():
    references = active_references()
    return references.land if references else _local_land_mask()


@lru_cache(maxsize=1)
def _local_land_mask():
    path = DETAIL_FILE if DETAIL_FILE.exists() else LAND_FILE
    payload = path.read_bytes()
    document = json.loads(payload)
    mask = LandMask(from_wkb(document) if path == DETAIL_FILE else
                    (feature['geometry'] for feature in document['features']))
    mask.source_sha256 = hashlib.sha256(payload).hexdigest()
    mask.name = 'GSHHG 2.3.7 high resolution (L1)' if path == DETAIL_FILE else 'Natural Earth 1:10m'
    return mask
