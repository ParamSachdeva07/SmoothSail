"""Review WPI-matched UN/LOCODE ports against the active, land-screened sea graph.

The WPI position is evidence for port identity, never a sailing endpoint. Only
an existing node in the graph's main strongly connected component is used as
an approximate offshore approach. Apply is opt-in and follows route checks.
"""
import argparse
import json
import math
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import httpx
import networkx as nx
from pymongo import UpdateOne
from scipy.spatial import cKDTree

from service.canals import catalog
from service.config import Settings
from service.data import Repository
from service.geo import distance_nm
from service.models import Port, RouteRequest
from service.navigation import default_land_mask
from service.routing import calculate

WPI_URL = 'https://gis.unocha.org/server/rest/services/Hosted/global_world_seaport_index_202511/FeatureServer/0'
ROOT = Path(__file__).resolve().parents[1]
PILOT = ('BEANR', 'USLGB', 'ZACPT', 'MYTPP', 'FRMRS', 'LKCMB', 'MACAS', 'GBLIV',
         'ARBUE', 'DEWVN', 'DECUX', 'BRRIO', 'CNGGZ', 'FRCQF', 'ITSPE', 'ITBRI',
         'EETLL', 'TRIZT', 'FRLRH', 'FRTLN', 'NLHAR', 'KRPUS', 'CNQIN', 'ESPMI',
         'USHOU', 'GBBEL', 'SEGRH', 'NOLAR', 'NOHAL', 'CIABJ', 'NLAMS', 'NOBGO',
         'DEBRV', 'PLGDY', 'ITGOA', 'SEGOT', 'ILHFA', 'FIHEL', 'USHNL', 'TRIZM',
         'JPUKB', 'FIKTK', 'TRMER', 'ITNAP', 'JPOSA', 'USPEF', 'ISREY', 'PTSIE',
         'HRSPU', 'ITTAR', 'GBTEE', 'BEZEE', 'GRSKG', 'GBIMM', 'DERSK', 'SEMMA',
         'DEEME', 'GBABD', 'NOSVG', 'KHKOS')
# Reviewed spelling equivalences, not a general fuzzy-name allowance.
ALIASES = {'KRPUS': 'PUSAN', 'CNQIN': 'QINGDAO GANG'}
MAX_CATALOGUE_OFFSET_NM = 25
MAX_GRAPH_OFFSET_NM = 15
BASE_REFERENCE_CODES = frozenset({'DEHAM', 'FRLEH', 'PTLIS', 'USLAX', 'INBOM',
                                  'USNYC', 'NLRTM', 'SGSIN', 'AUSYD', 'JPTYO'})


def normalized(name):
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]', '', plain.replace('port of ', '').replace(' pt', ''))


def unit_vector(point):
    lon, lat = map(math.radians, point)
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)


def download_wpi(path, transport=None):
    records = []
    with httpx.Client(timeout=30, transport=transport) as client:
        for offset in range(0, 10000, 2000):
            response = client.get(f'{WPI_URL}/query', params={'f': 'json', 'where': '1=1',
                'outFields': 'objectid,port_name,country,latitude,longitude,harborsize,harbortype,chan_depth,cargodepth',
                'returnGeometry': 'false', 'orderByFields': 'objectid', 'resultOffset': offset,
                'resultRecordCount': 2000})
            response.raise_for_status()
            payload = response.json()
            if 'error' in payload:
                raise ValueError(f"WPI service rejected page {offset}: {payload['error'].get('message')}")
            page = [feature['attributes'] for feature in payload['features']]
            records.extend(page)
            if len(page) < 2000:
                break
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'source': WPI_URL, 'retrievedAt': datetime.now(UTC).isoformat(),
        'features': records}, separators=(',', ':')))
    return len(records)


def wpi_index(source):
    indexed = {}
    for row in source['features']:
        if row.get('latitude') is None or row.get('longitude') is None:
            continue
        indexed.setdefault((row['country'], normalized(row['port_name'])), []).append(row)
    return indexed


class CandidateRepository:
    def __init__(self, base, port):
        self.base, self.port = base, port

    def resolve_port(self, locode):
        return self.port if locode == self.port.id else self.base.resolve_port(locode)

    def __getattr__(self, name):
        return getattr(self.base, name)


def crosses_land(coordinates, mask):
    return mask.intersects(coordinates)


def prepare_candidate(record, index, nodes, tree, graph, mask, reviewed_edges, safe_nodes):
    code = record['locode']
    name = ALIASES.get(code, record['name'])
    options = index.get((record['country'], normalized(name)), [])
    catalogue = record['location']['coordinates']
    matches = [item for item in options if distance_nm(catalogue,
        [item['longitude'], item['latitude']]) <= MAX_CATALOGUE_OFFSET_NM]
    if len(matches) != 1:
        return None, 'missing_or_ambiguous_wpi_match'
    match = matches[0]
    point = [match['longitude'], match['latitude']]
    # A near-shore node is only usable if every incident sailing edge is clear.
    # Otherwise another voyage may pick a land-crossing edge from the same port.
    node = None
    for _, node_index in zip(*tree.query(unit_vector(point), k=min(80, len(nodes)))):
        candidate = nodes[int(node_index)]
        access = graph.nodes[candidate]['coordinates']
        if distance_nm(point, access) > MAX_GRAPH_OFFSET_NM:
            break
        if candidate not in safe_nodes:
            edges = list(graph.out_edges(candidate, data=True)) + list(graph.in_edges(candidate, data=True))
            safe_nodes[candidate] = all(edge['sourceEdgeId'] in reviewed_edges or
                not crosses_land(edge['coordinates'], mask) for _, _, edge in edges)
        if safe_nodes[candidate]:
            node = candidate
            break
    if node is None:
        return None, 'no_nearby_node_in_main_connected_sea_network'
    access = graph.nodes[node]['coordinates']
    offset = distance_nm(point, access)
    return {'nodeId': node, 'coordinates': list(access), 'method': 'wpi_2025_main_component_snap',
        'target': point, 'offsetNm': round(offset, 3), 'wpiObjectId': match['objectid'],
        'catalogueOffsetNm': round(distance_nm(catalogue, point), 3), 'sourceUrl': WPI_URL}, None


def check_route(repo, record, access, reference, mask):
    port = Port(id=record['locode'], name=record['name'], country=record['country'],
        coordinates=tuple(access['coordinates']), routing_node_id=access['nodeId'])
    candidate_repo = CandidateRepository(repo, port)
    report = calculate(RouteRequest(origin=port.id, destination=reference.id), candidate_repo,
        include_display=False)
    if len(report.routes) != 3 or not all(route.distance_nm > 0 for route in report.routes):
        raise ValueError('Routing service returned incomplete route options.')
    geometry = report.routes[0].geometry
    start = (geometry['coordinates'][0][0] if geometry['type'] == 'MultiLineString'
             else geometry['coordinates'][0])
    if distance_nm(start, access['coordinates']) > 1:
        raise ValueError('Calculated route does not start at the mapped approach point.')
    for route in report.routes:
        for segment in route.segments:
            if segment.kind in ('canal_wait', 'canal_transit'):
                continue
            if crosses_land(segment.geometry['coordinates'], mask):
                raise ValueError('Calculated route has a sailing segment crossing mapped land.')
    return {'reference': reference.id, 'strategies': [route.strategy for route in report.routes],
        'distanceNm': round(report.routes[0].distance_nm, 1)}


def expand(repo, source, codes, route_check=True):
    graph = repo.load_graph()
    mask = default_land_mask()
    reviewed_edges = {edge_id for canal in catalog()['canals'].values()
                      for edge_id in canal['reviewedEdges']}
    safe_nodes = {}
    component = max(nx.strongly_connected_components(graph), key=len)
    nodes = sorted(component)
    tree = cKDTree([unit_vector(graph.nodes[node]['coordinates']) for node in nodes])
    index = wpi_index(source)
    # Keep the gateway test independent of candidates previously enabled in
    # this batch; an unsafe candidate must not taint another port's result.
    references = [repo.resolve_port(code) for code in sorted(BASE_REFERENCE_CODES)]
    results = []
    for code in dict.fromkeys(codes):
        record = repo.database().ports.find_one({'locode': code})
        result = {'locode': code, 'name': record.get('name') if record else None}
        if not record:
            result.update(status='rejected', reason='not_in_imported_unlocode_catalogue')
        elif record.get('supported') and record.get('accessValidation', {}).get('source') != WPI_URL:
            result.update(status='already_supported')
        else:
            access, reason = prepare_candidate(record, index, nodes, tree, graph, mask, reviewed_edges, safe_nodes)
            if reason:
                result.update(status='rejected', reason=reason)
            else:
                result['access'] = access
                if route_check:
                    reference = min((p for p in references if p.id != code),
                        key=lambda p: distance_nm(access['coordinates'], p.coordinates))
                    try:
                        result['routeCheck'] = check_route(repo, record, access, reference, mask)
                    except Exception as error:  # noqa: BLE001 - reject one bad candidate, continue batch
                        result.update(status='rejected', reason=f'route_check_failed:{type(error).__name__}:{error}')
                if 'status' not in result:
                    result['status'] = 'validated'
        results.append(result)
        print(f"{code}: {result['status']} {result.get('reason', '')}", flush=True)
    return results


def apply(repo, results, mapping_path):
    validated = [result for result in results if result['status'] == 'validated' and result.get('routeCheck')]
    rejected_existing = [result for result in results if result['status'] == 'rejected' and
        repo.database().ports.find_one({'locode': result['locode'], 'supported': True,
            'accessValidation.source': WPI_URL}, {'_id': 1})]
    mapping = json.loads(mapping_path.read_text())
    updates = []
    for item in validated:
        code, access = item['locode'], item['access']
        mapping[code] = access
        updates.append(UpdateOne({'locode': code}, {'$set': {
            'supported': True, 'routingNodeId': access['nodeId'],
            'accessPoint': {'type': 'Point', 'coordinates': access['coordinates']},
            'accessValidation': {'source': WPI_URL, 'wpiObjectId': access['wpiObjectId'],
                'catalogueOffsetNm': access['catalogueOffsetNm'], 'graphOffsetNm': access['offsetNm'],
                'routeCheck': item['routeCheck'], 'validatedAt': datetime.now(UTC)}}}))
    for item in rejected_existing:
        code = item['locode']
        mapping.pop(code, None)
        updates.append(UpdateOne({'locode': code, 'accessValidation.source': WPI_URL},
            {'$set': {'supported': False}, '$unset': {'routingNodeId': '', 'accessPoint': '', 'accessValidation': ''}}))
    if not updates:
        return 0, 0
    outcome = repo.database().ports.bulk_write(updates, ordered=True)
    if outcome.matched_count != len(updates):
        raise RuntimeError('Port records changed while applying the validated batch.')
    temporary = mapping_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(mapping, indent=2, sort_keys=True) + '\n')
    temporary.replace(mapping_path)
    return len(validated), len(rejected_existing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-file', type=Path, default=ROOT / 'data/raw/wpi-ocha-2025.json')
    parser.add_argument('--download-wpi', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--access-points', type=Path, default=ROOT / 'data/access_points.json')
    parser.add_argument('--ports', default=','.join(PILOT), help='Comma-separated UN/LOCODE pilot batch')
    parser.add_argument('--report', type=Path, default=ROOT / 'reports/port-expansion.json')
    parser.add_argument('--apply', action='store_true', help='Enable only ports passing all checks')
    args = parser.parse_args()
    if args.download_wpi:
        print(f'Downloaded {download_wpi(args.source_file)} WPI-derived records.', flush=True)
    source = json.loads(args.source_file.read_text())
    if source.get('source') != WPI_URL:
        raise ValueError('Unexpected WPI source file.')
    repo = Repository(Settings(_env_file=args.env_file) if args.env_file else Settings())
    try:
        # Match the graph loader and route service's pinned Mongo land reference.
        # Falling back to the local Natural Earth mask can falsely reject ports.
        with repo.planning_context():
            results = expand(repo, source, [code.strip().upper() for code in args.ports.split(',') if code.strip()])
        output = {'source': source['source'], 'graphVersion': repo.version,
            'checkedAt': datetime.now(UTC).isoformat(), 'results': results}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(output, indent=2, default=str) + '\n')
        applied, disabled = apply(repo, results, args.access_points) if args.apply else (0, 0)
        print(json.dumps({'validated': sum(r['status'] == 'validated' for r in results),
            'rejected': sum(r['status'] == 'rejected' for r in results), 'applied': applied,
            'disabled': disabled,
            'report': str(args.report)}, indent=2))
    finally:
        if repo.client:
            repo.client.close()


if __name__ == '__main__':
    main()
