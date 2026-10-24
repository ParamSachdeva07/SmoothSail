import json
import zipfile

import pytest

from service.importing import ImportBundle, archive_members, locode_coordinate


def test_archive_rejects_path_traversal(tmp_path):
    path = tmp_path / 'malicious.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('../outside.csv', 'no')
    with pytest.raises(ValueError, match='Unsafe archive'):
        archive_members(path)
    assert not (tmp_path.parent / 'outside.csv').exists()


def test_port_minutes_and_hemispheres():
    assert locode_coordinate('5130N 00007W') == pytest.approx([-7 / 60, 51.5])
    with pytest.raises(ValueError, match='minutes'):
        locode_coordinate('5160N 00007W')


def test_actual_unlocode_column_order_filters_non_seaports(tmp_path):
    path = tmp_path / 'UNLOCODE CodeListPart1.csv'
    path.write_text(',NL,,.NETHERLANDS,,,,,,,,\n,NL,RTM,Rotterdam,Rotterdam,,1-------,AI,2601,,5155N 00430E,\n,NL,XXX,Inland,Inland,,--3-----,AI,2601,,5155N 00430E,\n')
    bundle = ImportBundle().load(tmp_path)
    assert set(bundle.records['ports']) == {'NLRTM'}
    assert not bundle.rejected


def test_access_points_are_required_to_support_ports(import_fixture):
    source, access = import_fixture
    raw = ImportBundle().load(source)
    assert raw.report()['supportedPorts'] == 0
    reviewed = ImportBundle().load(source, access)
    assert reviewed.report()['supportedPorts'] == 2
    assert len(reviewed.records['routing_nodes']) == 3
    assert reviewed.report()['networkComponents'] == 1
    assert not reviewed.rejected


def test_rejects_edges_with_unknown_nodes(import_fixture):
    source, access = import_fixture
    path = source / 'network.json'
    data = json.loads(path.read_text())
    data['edges'].append({'from': 'west', 'to': 'missing'})
    path.write_text(json.dumps(data))
    bundle = ImportBundle().load(source, access)
    assert len(bundle.rejected) == 1
    with pytest.raises(ValueError, match='rejected records'):
        bundle.apply(None)


def test_zip_import_preserves_source_bytes(import_fixture, tmp_path):
    source, access = import_fixture
    archive_dir = tmp_path / 'archives'
    archive_dir.mkdir()
    archive = archive_dir / 'inputs.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for path in source.iterdir():
            output.write(path, path.name)
    original = archive.read_bytes()
    bundle = ImportBundle().load(archive_dir, access)
    assert bundle.report()['supportedPorts'] == 2
    assert archive.read_bytes() == original


def test_geopackage_retains_canal_passage_properties(tmp_path):
    import sqlite3
    import struct
    from shapely.geometry import LineString
    path = tmp_path / 'marnet.gpkg'
    blob = b'GP\x00\x01' + struct.pack('<i', 4326) + LineString([[-20, 40], [-19, 40]]).wkb
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE gpkg_geometry_columns (table_name, column_name, srs_id)')
        db.execute("INSERT INTO gpkg_geometry_columns VALUES ('network', 'geometry', 4326)")
        db.execute('CREATE TABLE network (geometry BLOB, pass TEXT)')
        db.execute('INSERT INTO network VALUES (?, ?)', (blob, 'suez'))
    bundle = ImportBundle().load(tmp_path)
    assert not bundle.rejected
    assert next(iter(bundle.records['routing_edges'].values()))['passageIds'] == ['suez']
