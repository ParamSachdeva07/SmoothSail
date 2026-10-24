"""Deterministic, format-aware imports. Source files are never executed."""
import csv
import hashlib
import json
import math
import re
import stat
import tempfile
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import networkx as nx
from pyproj import CRS, Transformer
from pymongo import ReplaceOne
from shapely.geometry import mapping, shape
from shapely.ops import transform

from service.data import ensure_indexes, graph_snapshot
from service.geo import distance_nm

PARSER_VERSION = '2'
MAX_ARCHIVE_BYTES = 2 * 1024**3


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def archive_members(path):
    with zipfile.ZipFile(path) as archive:
        total = 0
        result = []
        for member in archive.infolist():
            name = member.filename.replace('\\', '/')
            part = PurePosixPath(name)
            total += member.file_size
            if part.is_absolute() or '..' in part.parts or ':' in name or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f'Unsafe archive member: {name}')
            if total > MAX_ARCHIVE_BYTES or member.file_size > MAX_ARCHIVE_BYTES:
                raise ValueError('Archive exceeds the 2 GiB extraction budget.')
            if member.file_size > 10_000_000 and member.file_size / max(member.compress_size, 1) > 500:
                raise ValueError('Archive compression ratio exceeds the extraction budget.')
            result.append({'name': name, 'bytes': member.file_size})
        return result


def inventory(directory):
    records = []
    for path in sorted(Path(directory).rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        record = {'path': str(path.relative_to(directory)), 'bytes': path.stat().st_size, 'sha256': checksum(path)}
        if path.suffix.lower() == '.zip':
            record['members'] = archive_members(path)
        records.append(record)
    return records


def coordinate(value):
    if len(value) < 2:
        raise ValueError('Coordinate must contain longitude and latitude.')
    lon, lat = float(value[0]), float(value[1])
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError('Coordinates must be finite WGS84 longitude/latitude.')
    return [lon, lat]


def locode_coordinate(value):
    match = re.fullmatch(r'\s*(\d{2})(\d{2})([NS])\s+(\d{3})(\d{2})([EW])\s*', value.upper())
    if not match:
        raise ValueError('Missing or malformed UN/LOCODE coordinates.')
    ld, lm, ns, od, om, ew = match.groups()
    if int(lm) >= 60 or int(om) >= 60:
        raise ValueError('Coordinate minutes must be below 60.')
    return coordinate([(int(od) + int(om) / 60) * (-1 if ew == 'W' else 1),
                       (int(ld) + int(lm) / 60) * (-1 if ns == 'S' else 1)])


def node_id(point):
    return 'n_' + hashlib.sha256(json.dumps([round(x, 6) for x in point]).encode()).hexdigest()[:16]


class ImportBundle:
    def __init__(self):
        self.records = defaultdict(dict)
        self.rejected = []
        self.skipped = []
        self.inventory = []

    def reject(self, source, row, error):
        self.rejected.append({'source': source, 'row': row, 'reason': str(error)[:200]})

    def add_port(self, row, source):
        row = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in row.items() if k is not None}
        country = str(row.get('country', '')).strip().upper()
        if not row.get('location') and not row.get('locode') and not row.get('unlocode'):
            return  # UN/LOCODE country-heading rows are not locations.
        locode = str(row.get('locode') or row.get('unlocode') or (country + str(row.get('location', '')).strip())).replace(' ', '').upper()
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}', locode):
            raise ValueError('Missing or invalid UN/LOCODE.')
        function = str(row.get('function', ''))
        if function and not function.startswith('1'):
            return
        if row.get('longitude') not in [None, ''] and row.get('latitude') not in [None, '']:
            point = coordinate([row['longitude'], row['latitude']])
        else:
            point = locode_coordinate(str(row.get('coordinates', '')))
        self.records['ports'][locode] = {'_id': locode, 'locode': locode, 'name': str(row.get('name') or locode),
                                          'country': country or locode[:2], 'location': {'type': 'Point', 'coordinates': point},
                                          'supported': False, 'sourceFile': source}

    def add_edge(self, coords, properties, source, a=None, b=None):
        coords = [coordinate(p) for p in coords]
        if len(coords) < 2 or coords[0] == coords[-1]:
            raise ValueError('Network edges require distinct endpoints.')
        a, b = str(a or node_id(coords[0])), str(b or node_id(coords[-1]))
        for identifier, point in [(a, coords[0]), (b, coords[-1])]:
            existing = self.records['routing_nodes'].get(identifier)
            if existing and distance_nm(existing['location']['coordinates'], point) > .01:
                raise ValueError('A node ID refers to inconsistent coordinates.')
            self.records['routing_nodes'][identifier] = {'nodeId': identifier, 'location': {'type': 'Point', 'coordinates': point}}
        edge_id = hashlib.sha256(json.dumps([a, b, coords], sort_keys=True).encode()).hexdigest()[:24]
        passage = properties.get('passageIds', properties.get('passage', properties.get('pass', [])))
        if isinstance(passage, str):
            passage = [passage] if passage else []
        if not isinstance(passage, list):
            passage = [str(passage)] if passage is not None else []
        bidirectional = properties.get('bidirectional', True)
        if isinstance(bidirectional, str):
            bidirectional = bidirectional.lower() not in ['false', '0', 'no']
        self.records['routing_edges'][edge_id] = {
            'edgeId': edge_id, 'from': a, 'to': b, 'geometry': {'type': 'LineString', 'coordinates': coords},
            'distanceNm': sum(distance_nm(x, y) for x, y in zip(coords, coords[1:])),
            'passageIds': [str(p) for p in passage], 'bidirectional': bool(bidirectional), 'sourceFile': source,
        }

    def parse_feature(self, feature, source, index):
        geometry = feature.get('geometry')
        if not geometry:
            raise ValueError('Feature has no geometry.')
        geom = shape(geometry)
        if geom.is_empty or not geom.is_valid:
            raise ValueError('Feature has invalid or empty geometry.')
        west, south, east, north = geom.bounds
        if west < -180 or east > 180 or south < -90 or north > 90:
            raise ValueError('Feature is not in WGS84 degrees.')
        properties = feature.get('properties') or {}
        is_network = any(token in source.lower() for token in ['network', 'marnet', 'searoute', 'routing'])
        if geom.geom_type in ['LineString', 'MultiLineString'] and is_network:
            lines = [geom] if geom.geom_type == 'LineString' else list(geom.geoms)
            for line in lines:
                self.add_edge(list(line.coords), properties, source)
        elif geom.geom_type == 'Point' and any(k in properties for k in ['locode', 'UNLOCODE']):
            self.add_port(properties | {'longitude': geom.x, 'latitude': geom.y}, source)
        elif geom.geom_type in ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString']:
            key = hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()
            self.records['geography'][key] = {'_id': key, 'geometry': geometry, 'sourceFile': source,
                                              'kind': 'land' if 'land' in source.lower() else 'geography'}
        else:
            self.skipped.append({'source': source, 'reason': f'Unsupported feature type {geom.geom_type}'})

    def parse(self, path, source):
        suffix = path.suffix.lower()
        if suffix == '.csv':
            if not any(token in source.lower() for token in ['port', 'locode', 'code-list', 'codelist']):
                self.skipped.append({'source': source, 'reason': 'CSV is not identified as a port catalogue.'})
                return
            try:
                text = path.read_text(encoding='utf-8-sig')
            except UnicodeDecodeError:
                text = path.read_text(encoding='latin-1')
            rows = list(csv.reader(text.splitlines()))
            if not rows:
                return
            normalized = [re.sub('[^a-z]', '', value.lower()) for value in rows[0]]
            if 'coordinates' in normalized or 'locode' in normalized or 'longitude' in normalized:
                headers, rows = rows[0], rows[1:]
            else:
                headers = ['Change', 'Country', 'Location', 'Name', 'NameWoDiacritics', 'Subdivision', 'Function', 'Status', 'Date', 'IATA', 'Coordinates', 'Remarks']
            for index, values in enumerate(rows):
                try:
                    self.add_port(dict(zip(headers, values)), source)
                except (ValueError, TypeError) as error:
                    self.reject(source, index + 1, error)
        elif suffix in ['.geojson', '.json']:
            document = json.loads(path.read_text())
            if document.get('type') == 'TidelineNetwork':
                nodes = {str(n['id']): coordinate(n['coordinates']) for n in document['nodes']}
                for index, edge in enumerate(document['edges']):
                    try:
                        a, b = str(edge['from']), str(edge['to'])
                        coords = edge.get('geometry', {}).get('coordinates', [nodes[a], nodes[b]])
                        if distance_nm(coords[0], nodes[a]) > .01 or distance_nm(coords[-1], nodes[b]) > .01:
                            raise ValueError('Edge geometry does not match its named nodes.')
                        self.add_edge(coords, edge, source, a, b)
                    except (ValueError, KeyError, TypeError) as error:
                        self.reject(source, index + 1, error)
            elif document.get('type') == 'FeatureCollection':
                for index, feature in enumerate(document['features']):
                    try:
                        self.parse_feature(feature, source, index)
                    except (ValueError, KeyError, TypeError) as error:
                        self.reject(source, index + 1, error)
            else:
                self.skipped.append({'source': source, 'reason': 'JSON is not a recognized dataset.'})
        elif suffix == '.shp':
            import shapefile
            crs_file = path.with_suffix('.prj')
            if not crs_file.exists():
                raise ValueError('Shapefile is missing its CRS .prj sidecar.')
            crs = CRS.from_wkt(crs_file.read_text())
            transformer = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
            with shapefile.Reader(str(path), encoding='utf-8', encodingErrors='replace') as reader:
                for index, record in enumerate(reader.iterShapeRecords()):
                    try:
                        geom = transform(transformer.transform, shape(record.shape.__geo_interface__))
                        self.parse_feature({'geometry': mapping(geom), 'properties': record.record.as_dict()}, source, index)
                    except (ValueError, TypeError) as error:
                        self.reject(source, index + 1, error)
        elif suffix == '.gpkg':
            import sqlite3
            from shapely import from_wkb
            with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as connection:
                connection.row_factory = sqlite3.Row
                layers = connection.execute('SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns').fetchall()
                for table, column, srs in layers:
                    quoted_table = table.replace('"', '""')
                    if srs not in [4326]:
                        raise ValueError('GeoPackage importer currently requires EPSG:4326; convert other layers first.')
                    for index, row in enumerate(connection.execute(f'SELECT * FROM "{quoted_table}"')):
                        try:
                            blob = row[column]
                            if not blob or blob[:2] != b'GP':
                                raise ValueError('Invalid GeoPackage geometry header.')
                            envelope = (blob[3] >> 1) & 7
                            envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope)
                            if envelope_bytes is None:
                                raise ValueError('Unsupported GeoPackage envelope.')
                            geom = from_wkb(blob[8 + envelope_bytes:])
                            properties = {key: row[key] for key in row.keys() if key != column}
                            self.parse_feature({'geometry': mapping(geom), 'properties': properties}, source + '/' + table, index)
                        except (ValueError, TypeError) as error:
                            self.reject(source, index + 1, error)
        elif suffix not in ['.dbf', '.prj', '.shx', '.cpg', '.qix', '.sbn', '.sbx']:
            self.skipped.append({'source': source, 'reason': 'Not used by the initial route pipeline.'})

    def load(self, directory, access_points=None):
        directory = Path(directory)
        self.inventory = inventory(directory)
        for item in self.inventory:
            path = directory / item['path']
            if path.suffix.lower() == '.zip':
                with tempfile.TemporaryDirectory(prefix='tideline-import-') as temporary:
                    root = Path(temporary)
                    with zipfile.ZipFile(path) as archive:
                        # Inventory validated all members before extraction.
                        archive.extractall(root)
                    for extracted in sorted(root.rglob('*')):
                        if extracted.is_file():
                            if path.name == 'searoute-master.zip' and str(extracted.relative_to(root)) != 'searoute-master/modules/core/src/main/resources/marnet/marnet_plus_5km.gpkg':
                                continue  # One resolution, one copy; never mix source/test/release networks.
                            self.parse(extracted, item['path'] + '/' + str(extracted.relative_to(root)))
            else:
                self.parse(path, item['path'])
        if access_points:
            mapping_data = json.loads(Path(access_points).read_text())
            for locode, access in mapping_data.items():
                node = self.records['routing_nodes'].get(str(access['nodeId']))
                port = self.records['ports'].get(locode)
                if not node or not port:
                    raise ValueError(f'Access mapping {locode} references a missing port or node.')
                point = coordinate(access['coordinates'])
                if distance_nm(point, node['location']['coordinates']) > .01:
                    raise ValueError(f'Access point {locode} must coincide with the reviewed graph node.')
                port.update(supported=True, routingNodeId=str(access['nodeId']), accessPoint={'type': 'Point', 'coordinates': point})
                if access.get('portwatchId'):
                    port['portwatchId'] = str(access['portwatchId'])
        return self

    def report(self):
        graph = nx.Graph()
        graph.add_nodes_from(self.records['routing_nodes'])
        graph.add_edges_from((edge['from'], edge['to']) for edge in self.records['routing_edges'].values())
        return {'parserVersion': PARSER_VERSION, 'inventory': self.inventory,
                'counts': {name: len(records) for name, records in self.records.items()},
                'supportedPorts': sum(p.get('supported', False) for p in self.records['ports'].values()),
                'networkComponents': nx.number_connected_components(graph) if graph else 0,
                'rejected': self.rejected, 'skipped': self.skipped}

    def apply(self, db, allow_rejected=False, cache_dir=None):
        if self.rejected and not allow_rejected:
            raise ValueError('Import contains rejected records. Review the report before using --allow-rejected.')
        ensure_indexes(db)
        payload = json.dumps({name: records for name, records in sorted(self.records.items()) if records}, sort_keys=True)
        version = hashlib.sha256((PARSER_VERSION + payload).encode()).hexdigest()[:20]
        counts = {}
        # Prepare graph first. The active pointer moves only after all writes succeed.
        for name in ['routing_nodes', 'routing_edges', 'geography', 'ports']:
            docs = []
            for key, original in self.records[name].items():
                doc = dict(original)
                if name.startswith('routing_'):
                    doc.update(_id=f'{version}:{key}', graphVersion=version)
                doc['importVersion'] = version
                docs.append(doc)
            existing = {d['_id']: d.get('importVersion') for d in db[name].find({}, {'_id': 1, 'importVersion': 1})}
            inserts = [doc for doc in docs if doc['_id'] not in existing]
            updates = [doc for doc in docs if doc['_id'] in existing and existing[doc['_id']] != version]
            for start in range(0, len(inserts), 2000):
                db[name].insert_many(inserts[start:start + 2000], ordered=False)
            for start in range(0, len(updates), 500):
                db[name].bulk_write([ReplaceOne({'_id': d['_id']}, d, upsert=True) for d in updates[start:start + 500]], ordered=False)
            counts[name] = len(docs)
        now = datetime.now(UTC)
        payload = graph_snapshot(list(self.records['routing_nodes'].values()), list(self.records['routing_edges'].values()))
        graph_hash = hashlib.sha256(payload).hexdigest()
        if cache_dir is not None:
            directory = Path(cache_dir)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f'graph-{version}.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(payload)
            temporary.replace(target)
        db.data_imports.replace_one({'_id': version}, {'_id': version, 'createdAt': now, 'counts': counts,
                                                       'parserVersion': PARSER_VERSION, 'sources': self.inventory}, upsert=True)
        if counts['routing_edges']:
            if db.routing_edges.count_documents({'graphVersion': version}) != counts['routing_edges']:
                raise ValueError('Written graph count does not match its manifest.')
            db.data_imports.replace_one({'_id': 'active_graph'}, {'_id': 'active_graph', 'graphVersion': version,
                                                                  'graphSha256': graph_hash, 'activatedAt': now}, upsert=True)
        return {'version': version, 'counts': counts}
