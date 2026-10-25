import hashlib
import json
import os
import re
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from contextlib import contextmanager

import gridfs
import networkx as nx
from pymongo import ASCENDING, GEOSPHERE, MongoClient
from pymongo.errors import OperationFailure

from service.config import Settings
from service.demo import DemoForecast, demo_network
from service.forecast import GridForecast, as_utc
from service.models import Port, RouteError
from service.navigation import connect_dateline, default_land_mask, exclude_unsupported_passages
from service.canals import catalog, decorate_graph
from service.references import active_references, load_references, use_references


def connect(settings: Settings):
    client = MongoClient(settings.connection_uri(), serverSelectionTimeoutMS=4000, tz_aware=True)
    client.admin.command('ping')
    return client, client[settings.mongodb_db]


def ensure_indexes(db):
    db.ports.create_index('locode', unique=True)
    db.ports.create_index([('location', GEOSPHERE)])
    db.ports.create_index([('accessPoint', GEOSPHERE)])
    db.ports.create_index([('supported', ASCENDING), ('name', ASCENDING)])
    db.routing_nodes.create_index([('graphVersion', ASCENDING), ('nodeId', ASCENDING)], unique=True)
    db.routing_edges.create_index([('graphVersion', ASCENDING), ('edgeId', ASCENDING)], unique=True)
    db.forecast_cache.create_index([('datasetId', ASCENDING), ('region', ASCENDING), ('retrievedAt', -1)])
    db.port_activity.create_index([('source', ASCENDING), ('locationId', ASCENDING), ('date', ASCENDING)], unique=True)
    db.restrictions.create_index([('geometry', GEOSPHERE)])
    db.restrictions.create_index([('passageId', ASCENDING), ('cancelled', ASCENDING)])
    db.restrictions.create_index([('action', ASCENDING), ('verified', ASCENDING)])
    db.port_activity.create_index([('locationId', ASCENDING), ('date', -1)])


def graph_snapshot(nodes, edges):
    """Canonical compact representation, independent of Mongo storage fields."""
    node_fields = ['nodeId', 'location']
    edge_fields = ['edgeId', 'from', 'to', 'geometry', 'distanceNm', 'passageIds', 'bidirectional']
    value = {'nodes': [{k: n[k] for k in node_fields} for n in sorted(nodes, key=lambda n: n['nodeId'])],
             'edges': [{k: e[k] for k in edge_fields} for e in sorted(edges, key=lambda e: e['edgeId'])]}
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = self.db = None
        self.lock = Lock()
        self.forecast_lock = Lock()
        self.reference_lock = Lock()
        self.planning = None
        self.graph_reference_version = None
        self.search_config = None
        self.search_config_until = 0
        self.version = None
        self.graph = nx.DiGraph()
        self.forecast_cache = None
        self.forecast_key = None
        if settings.tideline_mode == 'demo':
            self.graph, self.ports = demo_network()
            self.version = 'illustrative-atlantic-v1'
        else:
            self.ports = []

    def database(self):
        if self.db is None:
            self.client, self.db = connect(self.settings)
        return self.db

    @contextmanager
    def planning_context(self):
        if self.settings.tideline_mode == 'demo':
            with use_references(None):
                yield None
            return
        db = self.database()
        pointer = db.planning_reference.find_one({'_id': 'active'})
        if not pointer:
            raise RouteError('references_missing', 'Publish planning references with scripts.store_planning_data first.', 503)
        with self.reference_lock:
            if self.planning is None or self.planning.version != pointer['version']:
                self.planning = load_references(db, self.settings.data_dir / 'cache', pointer['version'])
            references = self.planning
        with use_references(references):
            yield references

    def nearby_ports(self, longitude, latitude, radius_nm=100, limit=20):
        if self.settings.tideline_mode == 'demo':
            from service.geo import distance_nm
            ranked = sorted(((distance_nm([longitude, latitude], port.coordinates), port) for port in self.ports),
                            key=lambda item: item[0])
            return [port.model_dump(by_alias=True) | {'distanceNm': round(distance, 3)}
                    for distance, port in ranked if distance <= radius_nm][:limit]
        rows = self.database().ports.aggregate([
            {'$geoNear': {'near': {'type': 'Point', 'coordinates': [longitude, latitude]},
                          'key': 'accessPoint', 'distanceField': 'distanceMetres', 'spherical': True,
                          'maxDistance': radius_nm * 1852, 'query': {'supported': True}}},
            {'$limit': limit}])
        return [self.port_record(row).model_dump(by_alias=True) | {'distanceNm': round(row['distanceMetres'] / 1852, 3)}
                for row in rows]

    def search_ports(self, query='', limit=20):
        if self.settings.tideline_mode == 'demo':
            return [p for p in self.ports if query.lower() in f'{p.name} {p.country} {p.id}'.lower()][:limit]
        db = self.database()
        if query and re.fullmatch(r'[A-Za-z]{2}[A-Za-z0-9]{3}', query):
            exact = db.ports.find_one({'supported': True, 'locode': query.upper()})
            if exact:
                return [self.port_record(exact)]
        if len(query) >= 2:
            if time.monotonic() >= self.search_config_until:
                self.search_config = db.source_status.find_one({'_id': 'atlas_search_ports', 'enabled': True})
                self.search_config_until = time.monotonic() + 60
            if self.search_config:
                name_query = {'query': query, 'path': 'name', 'tokenOrder': 'sequential'}
                if len(query) >= 4:
                    name_query['fuzzy'] = {'maxEdits': 1, 'prefixLength': 1, 'maxExpansions': 20}
                try:
                    matches = list(db.ports.aggregate([
                        {'$search': {'index': self.search_config['indexName'], 'compound': {
                            'filter': [{'equals': {'path': 'supported', 'value': True}}],
                            'should': [{'autocomplete': name_query},
                                       {'autocomplete': {'query': query, 'path': 'locode'}}],
                            'minimumShouldMatch': 1}}},
                        {'$match': {'supported': True}}, {'$limit': limit}], maxTimeMS=1500))
                    if matches:
                        return [self.port_record(p) for p in matches]
                except OperationFailure:
                    # An absent/building Search index must not disable ordinary port lookup.
                    pass
        filters = {'supported': True}
        if query:
            regex = {'$regex': re.escape(query), '$options': 'i'}
            filters['$or'] = [{'name': regex}, {'locode': regex}]
        return [self.port_record(p) for p in db.ports.find(filters).sort('name', 1).limit(limit)]

    @staticmethod
    def port_record(p):
        return Port(id=p['locode'], name=p['name'], country=p.get('country', ''),
                    coordinates=tuple(p['accessPoint']['coordinates']), routing_node_id=p['routingNodeId'])

    def resolve_port(self, locode):
        if self.settings.tideline_mode == 'demo':
            port = next((p for p in self.ports if p.id == locode), None)
        else:
            record = self.database().ports.find_one({'locode': locode, 'supported': True})
            port = self.port_record(record) if record else None
        if not port:
            raise RouteError('unsupported_port', 'This port has no supported routing access point.')
        return port

    def port_land_coordinates(self, locode):
        """Catalogue location for landside planning; never use offshore routing nodes."""
        if self.settings.tideline_mode == 'demo':
            return None
        record = self.database().ports.find_one({'locode': locode, 'supported': True}, {'location': 1}) or {}
        return record.get('location', {}).get('coordinates')

    def port_road_anchor(self, locode):
        """Use a verified port gate when available; otherwise provide search context only.

        UN/LOCODE locations may be city centres and must not become road endpoints.
        """
        if self.settings.tideline_mode == 'demo':
            return None
        record = self.database().ports.find_one({'locode': locode, 'supported': True},
            {'name': 1, 'country': 1, 'location': 1, 'landAccessPoint': 1}) or {}
        if not record:
            return None
        return {'name': record.get('name'), 'country': record.get('country'),
            'catalogueCoordinates': record.get('location', {}).get('coordinates'),
            'coordinates': (record.get('landAccessPoint') or {}).get('coordinates'),
            'source': 'verified_port_access' if record.get('landAccessPoint') else None}

    def load_graph(self):
        if self.settings.tideline_mode == 'mongo' and active_references() is None:
            with self.planning_context():
                return self._load_graph()
        return self._load_graph()

    def _load_graph(self):
        if self.settings.tideline_mode == 'demo':
            return self.graph
        db = self.database()
        active = db.data_imports.find_one({'_id': 'active_graph'})
        if not active:
            raise RouteError('graph_missing', 'Import and activate a routing graph first.', 503)
        version = active['graphVersion']
        if not re.fullmatch(r'[a-f0-9]{20}', version):
            raise RouteError('invalid_graph_version', 'The active graph version is invalid.', 503)
        with self.lock:
            reference_version = active_references().version
            if version != self.version or reference_version != self.graph_reference_version:
                cache = self.settings.data_dir / 'cache' / f'graph-{version}.json'
                expected = active.get('graphSha256')
                payload = cache.read_bytes() if cache.exists() and expected else None
                if payload is None or hashlib.sha256(payload).hexdigest() != expected:
                    payload = graph_snapshot(list(db.routing_nodes.find({'graphVersion': version})),
                                             list(db.routing_edges.find({'graphVersion': version})))
                    if expected and hashlib.sha256(payload).hexdigest() != expected:
                        raise RouteError('graph_corrupt', 'The stored network does not match its checksum.', 503)
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache.with_suffix('.tmp')
                    temporary.write_bytes(payload)
                    os.replace(temporary, cache)
                snapshot = json.loads(payload)
                graph = nx.DiGraph()
                for node in snapshot['nodes']:
                    graph.add_node(node['nodeId'], coordinates=node['location']['coordinates'])
                for edge in snapshot['edges']:
                    attrs = {'sourceEdgeId': edge['edgeId'], 'distanceNm': edge['distanceNm'], 'coordinates': edge['geometry']['coordinates'],
                             'passageIds': edge.get('passageIds', [])}
                    a, b = edge['from'], edge['to']
                    tagged = set(attrs['passageIds']).intersection(catalog()['canals'])
                    if tagged and not any(edge['edgeId'] in catalog()['canals'][cid]['reviewedEdges'] for cid in tagged):
                        continue
                    if a not in graph or b not in graph:
                        raise RouteError('invalid_graph', 'Graph contains unresolved edge endpoints.', 503)
                    if not graph.has_edge(a, b) or attrs['distanceNm'] < graph[a][b]['distanceNm']:
                        graph.add_edge(a, b, **attrs)
                    if edge.get('bidirectional', True):
                        reverse = dict(attrs, coordinates=list(reversed(attrs['coordinates'])))
                        if not graph.has_edge(b, a) or attrs['distanceNm'] < graph[b][a]['distanceNm']:
                            graph.add_edge(b, a, **reverse)
                connect_dateline(graph)
                exclude_unsupported_passages(graph)
                decorate_graph(graph)
                default_land_mask().remove_crossings(graph)
                self.graph, self.version = graph, version
                self.graph_reference_version = reference_version
        return self.graph

    def forecast(self, departure, bounds):
        if self.settings.tideline_mode == 'demo':
            return DemoForecast(departure)
        with self.forecast_lock:
            return self._load_forecast()

    def _load_forecast(self):
        db = self.database()
        bucket = gridfs.GridFSBucket(db, bucket_name='forecast_files')
        cache_dir = self.settings.data_dir / 'cache'
        cache_dir.mkdir(parents=True, exist_ok=True)
        snapshots = list(db.forecast_cache.find({'status': 'ready'}).sort('retrievedAt', -1).limit(200))
        now = datetime.now(UTC)
        cache_key = tuple((str(e['_id']), e['sha256'], as_utc(e['refreshAfter']) <= now)
                          for e in snapshots)
        if cache_key == self.forecast_key:
            return self.forecast_cache
        entries, seen = [], set()
        for entry in snapshots:
            key = entry['datasetId'], entry.get('region', 'custom')
            # Partial regional coverage is useful. The sampler, rather than
            # this bounding-box query, determines each segment's coverage.
            if key in seen:
                continue
            file_id = entry['gridFsFileId']
            path = cache_dir / f'{file_id}.nc'
            if not path.exists():
                import tempfile
                with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        bucket.download_to_stream(file_id, stream)
                    except Exception:
                        temporary.unlink(missing_ok=True)
                        raise
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != entry['sha256']:
                    temporary.unlink(missing_ok=True)
                    raise RouteError('forecast_corrupt', 'A cached forecast failed its checksum.', 503)
                os.replace(temporary, path)
            entries.append((path, entry))
            seen.add(key)
        self.forecast_cache = GridForecast(entries, now)
        self.forecast_key = cache_key
        return self.forecast_cache

    def restrictions(self):
        """Permanent verified exclusions needed while generating candidate paths."""
        if self.settings.tideline_mode == 'demo':
            return []
        return self._restriction_query({'cancelled': {'$ne': True}, 'action': 'exclude', 'verified': True,
                                        'validFrom': {'$in': [None, '']}, 'validTo': {'$in': [None, '']}})

    def _restriction_query(self, query):
        records = list(self.database().restrictions.find(query, {'_id': 0}).limit(10001))
        if len(records) > 10000:
            raise RouteError('restriction_limit', 'Too many restrictions match this calculation; narrow the dataset.', 503)
        return records

    def route_restrictions(self, graph, paths, initial):
        """Mongo spherical prefilter, followed by exact segment/time checks in Python.

        Padded envelopes include all candidates, not just the shortest path. Broad
        boxes avoid losing a notice due to spherical/ellipsoidal/planar differences.
        Split at the dateline and into <=90-degree longitude spans so GeoJSON never
        accidentally describes the complement of a greater-than-hemisphere region.
        Passage-only notices are included independently of geometry.
        """
        if self.settings.tideline_mode == 'demo':
            return initial
        from service.geo import densify, line_geometry
        boxes, passages = set(), set()
        for path in paths:
            points = []
            for a, b in zip(path, path[1:]):
                edge = graph[a][b]
                points.extend(densify(edge['coordinates'], max_nm=10))
                passages.update(edge.get('passageIds', []))
            geometry = line_geometry(points)
            parts = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']
            for part in parts:
                west = max(-180, min(p[0] for p in part) - .1)
                east = min(180, max(p[0] for p in part) + .1)
                south = max(-89.9, min(p[1] for p in part) - .1)
                north = min(89.9, max(p[1] for p in part) + .1)
                while west < east:
                    right = min(east, west + 90)
                    boxes.add((west, south, right, north))
                    west = right
        clauses = []
        for w, s, e, n in sorted(boxes):
            # Mongo joins vertices by great circles. Subdivide horizontal sides
            # so their bow is much smaller than the envelope's 0.1-degree margin.
            steps = max(1, math.ceil(e - w))
            longitudes = [w + (e - w) * i / steps for i in range(steps + 1)]
            ring = [[lon, s] for lon in longitudes] + [[lon, n] for lon in reversed(longitudes)] + [[w, s]]
            clauses.append({'geometry': {'$geoIntersects': {'$geometry': {'type': 'Polygon', 'coordinates': [ring]}}}})
        if passages:
            clauses.append({'passageId': {'$in': sorted(passages)}})
        return self._restriction_query({'cancelled': {'$ne': True}, '$or': clauses}) if clauses else []

    def activity_notices(self, ports):
        if self.settings.tideline_mode == 'demo':
            return []
        result = []
        for port in ports:
            record = self.database().ports.find_one({'locode': port.id})
            source_id = record.get('portwatchId') if record else None
            if source_id:
                observation = self.database().port_activity.find_one({'locationId': source_id}, sort=[('date', -1)])
                if observation:
                    result.append(f"PortWatch {port.name}: {observation['date']} observation available; activity does not establish a closure or delay.")
        return result

    def port_context(self, port):
        record = observation = {}
        if self.settings.tideline_mode == 'mongo':
            record = self.database().ports.find_one({'locode': port.id}) or {}
            if record.get('portwatchId'):
                observation = self.database().port_activity.find_one(
                    {'locationId': record['portwatchId']}, sort=[('date', -1)]) or {}
        return {'locode': port.id, 'name': port.name, 'countryCode': port.id[:2],
                'catalogueCoordinates': record.get('location', {}).get('coordinates'),
                'approachCoordinates': list(port.coordinates), 'routingNodeId': port.routing_node_id,
                'catalogueImportVersion': record.get('importVersion'),
                'portwatchLocationId': record.get('portwatchId'), 'latestActivityDate': observation.get('date')}

    def provenance(self):
        active, imported = {}, {}
        if self.settings.tideline_mode == 'mongo':
            active = self.database().data_imports.find_one({'_id': 'active_graph'}) or {}
            imported = self.database().data_imports.find_one({'_id': self.version},
                {'createdAt': 1, 'counts': 1, 'parserVersion': 1, 'sources.path': 1, 'sources.sha256': 1, 'sources.bytes': 1}) or {}
        return {'mode': self.settings.tideline_mode, 'graphVersion': self.version,
                'planningReferenceVersion': active_references().version if active_references() else None,
                'planningReferenceStorage': 'mongodb' if active_references() else 'local_demo',
                'graphSha256': active.get('graphSha256'),
                'runtimeLandGeometrySha256': default_land_mask().source_sha256,
                'graphActivatedAt': active.get('activatedAt'), 'importedAt': imported.get('createdAt'),
                'importParserVersion': imported.get('parserVersion'), 'importedRecordCounts': imported.get('counts'),
                'sourceArchives': [{'name': Path(source['path']).name, 'sha256': source.get('sha256'), 'bytes': source.get('bytes')}
                                   for source in imported.get('sources', [])],
                'referenceSources': [
                    {'id': 'ports', 'name': 'UNECE UN/LOCODE', 'url': 'https://unlocode.unece.org/publications/'},
                    {'id': 'network', 'name': 'Eurostat SeaRoute', 'url': 'https://github.com/eurostat/searoute'},
                    {'id': 'land', 'name': default_land_mask().name,
                     'url': 'https://github.com/GenericMappingTools/gshhg-gmt/releases/tag/2.3.7'},
                    {'id': 'canals', 'name': catalog()['version'], 'retrievedAt': catalog()['retrievedAt']}
                ] if self.settings.tideline_mode == 'mongo' else [],
                'jurisdictionBoundariesLoaded': False, 'sanctionsListsLoaded': False,
                'bathymetryLoaded': False, 'authoritativeClosureFeedLoaded': False}

    def health(self):
        if self.settings.tideline_mode == 'demo':
            from service.costs import vessel_model
            return {'status': 'ready', 'mode': 'demo', 'graphVersion': self.version, 'ports': len(self.ports),
                    'vesselModel': vessel_model()}
        self.database()
        with self.planning_context() as references:
            self.load_graph()
        return {'status': 'ready', 'mode': 'mongo', 'graphVersion': self.version,
                'planningReferenceVersion': references.version,
                'vesselModel': references.vessel,
                'ports': self.db.ports.count_documents({'supported': True}),
                'freshForecasts': self.db.forecast_cache.count_documents({'status': 'ready', 'refreshAfter': {'$gt': datetime.now(UTC)}})}

    def data_status(self):
        """Database aggregations over source data only; no stored voyage analytics."""
        if self.settings.tideline_mode == 'demo':
            return {'mode': 'demo', 'simulated': True}
        db, now = self.database(), datetime.now(UTC)
        snapshots = list(db.forecast_cache.aggregate([
            {'$match': {'status': 'ready'}},
            {'$group': {'_id': {'datasetId': '$datasetId', 'region': '$region'}, 'snapshots': {'$sum': 1},
                        'freshSnapshots': {'$sum': {'$cond': [{'$gt': ['$refreshAfter', now]}, 1, 0]}},
                        'lastRetrievedAt': {'$max': '$retrievedAt'}, 'latestValidUntil': {'$max': '$validUntil'}}},
            {'$sort': {'_id.datasetId': 1, '_id.region': 1}}]))
        activity = list(db.port_activity.aggregate([
            {'$group': {'_id': '$locationId', 'observations': {'$sum': 1}, 'latestObservationDate': {'$max': '$date'}}},
            {'$sort': {'_id': 1}}]))
        return {'mode': 'mongo', 'generatedAt': now, 'planning': db.planning_reference.find_one(
                    {'_id': 'active'}, {'_id': 0}),
                'ports': {'catalogue': db.ports.count_documents({}), 'supported': db.ports.count_documents({'supported': True})},
                'forecasts': snapshots, 'portActivity': activity,
                'restrictions': {'nonCancelledRecords': db.restrictions.count_documents({'cancelled': {'$ne': True}})},
                'atlasSearch': db.source_status.find_one({'_id': 'atlas_search_ports'}, {'_id': 0}),
                'interpretation': 'Source inventory and freshness, not route coverage or a compliance assessment.'}
