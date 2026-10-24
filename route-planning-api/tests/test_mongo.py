import os
import uuid
import gzip
import hashlib
import json
from copy import deepcopy

import gridfs
import pytest
from pymongo import MongoClient

from service.config import Settings
from service.data import Repository
from service.data import ensure_indexes
from service.importing import ImportBundle
from service.models import RouteRequest
from service.routing import calculate
from service.references import publish_references
from service.costs import vessel_model
from service.canals import catalog
from shapely import to_wkb
from shapely.geometry import box
from shapely.geometry import mapping
from service.models import RouteError
import networkx as nx


def seed_references(db, vessel=None, land=None):
    payload = json.dumps([to_wkb(shape, hex=True) for shape in (land or [box(0, 0, 1, 1)])]).encode()
    file_id = gridfs.GridFSBucket(db, bucket_name='reference_files').upload_from_stream('land.json.gz', gzip.compress(payload))
    for name, data in [('vessel', vessel or deepcopy(vessel_model())), ('canals', deepcopy(catalog()))]:
        db.planning_reference.replace_one({'_id': name}, {'_id': name, 'data': data}, upsert=True)
    db.planning_reference.replace_one({'_id': 'land-screen'}, {'_id': 'land-screen',
        'name': 'Test land from Mongo', 'sha256': hashlib.sha256(payload).hexdigest(), 'gridFsFileId': file_id}, upsert=True)
    return publish_references(db)


@pytest.fixture
def mongo_database():
    uri = os.environ.get('TIDELINE_TEST_MONGO_URI')
    if not uri:
        pytest.skip('Set TIDELINE_TEST_MONGO_URI to test a disposable database.')
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = 'tideline_test_' + uuid.uuid4().hex
    db = client[name]
    seed_references(db)
    yield db
    client.drop_database(name)
    client.close()


def test_real_mongo_import_is_repeatable_and_routes_without_fabricated_weather(mongo_database, import_fixture):
    source, access = import_fixture
    bundle = ImportBundle().load(source, access)
    first = bundle.apply(mongo_database)
    second = bundle.apply(mongo_database)
    assert first['version'] == second['version']
    assert mongo_database.ports.count_documents({}) == 2
    assert mongo_database.routing_nodes.count_documents({}) == 3
    assert mongo_database.routing_edges.count_documents({}) == 3
    repo = Repository(Settings(tideline_mode='mongo'))
    repo.db = mongo_database
    result = calculate(RouteRequest(origin='GBXXX', destination='USXXX'), repo)
    assert result.mode == 'mongo'
    assert len(result.routes) == 3
    assert not result.sources
    assert all(r.forecast_coverage_percent == 0 for r in result.routes)
    assert not result.unavailable_strategies


def test_gridfs_publish_is_repeatable(mongo_database, tmp_path):
    from test_forecast import grid_file
    from service.providers import store_snapshot
    path, meta, now = grid_file(tmp_path)
    meta.update(region='test', bounds={'west': -20, 'east': -18, 'south': 40, 'north': 42})
    first = store_snapshot(mongo_database, path, meta)
    second = store_snapshot(mongo_database, path, meta)
    assert first['_id'] == second['_id']
    assert mongo_database.forecast_cache.count_documents({}) == 1
    assert mongo_database.forecast_files.files.count_documents({}) == 1
    record = mongo_database.forecast_cache.find_one({})
    assert gridfs.GridFSBucket(mongo_database, bucket_name='forecast_files').open_download_stream(record['gridFsFileId']).read() == path.read_bytes()
    repo = Repository(Settings(tideline_mode='mongo', data_dir=tmp_path))
    repo.db = mongo_database
    forecast = repo.forecast(now, (-22, 39, -16, 43))
    assert forecast.sample(-19, 41, now)['wave'] == 2
    assert forecast.sample(-21, 41, now)['wave'] is None
    assert repo.forecast(now, (-22, 39, -16, 43)) is forecast
    # Expiration must invalidate in-memory arrays immediately, without waiting for a minute bucket.
    mongo_database.forecast_cache.update_one({'_id': record['_id']}, {'$set': {'refreshAfter': now}})
    expired = repo.forecast(now, (-22, 39, -16, 43))
    assert expired is not forecast and expired.sample(-19, 41, now)['wave'] is None


def test_mongo_references_pin_one_version_and_reload_on_publication(mongo_database, import_fixture, tmp_path):
    source, access = import_fixture
    ImportBundle().load(source, access).apply(mongo_database)
    repo = Repository(Settings(tideline_mode='mongo', data_dir=tmp_path))
    repo.db = mongo_database
    request = RouteRequest(origin='GBXXX', destination='USXXX')
    before = calculate(request, repo)
    original_price = before.routes[0].cost.fuel_usd_per_tonne
    with repo.planning_context() as pinned:
        revised = deepcopy(vessel_model())
        revised['fuelUsdPerTonne'] = original_price * 2
        new_version = seed_references(mongo_database, revised)
        assert new_version != pinned.version
        assert vessel_model()['fuelUsdPerTonne'] == original_price
    after = calculate(request, repo)
    assert after.routes[0].cost.fuel_usd_per_tonne == original_price * 2
    assert after.metadata.data_provenance['planningReferenceVersion'] == new_version
    assert after.assumptions['landScreen'] == 'Test land from Mongo'
    assert after.routes[0].cost.fuel_usd == pytest.approx(before.routes[0].cost.fuel_usd * 2, abs=.02)
    assert list((tmp_path / 'cache').glob('land-*.json'))


def test_reference_land_change_rebuilds_screened_graph(mongo_database, import_fixture, tmp_path):
    source, access = import_fixture
    ImportBundle().load(source, access).apply(mongo_database)
    repo = Repository(Settings(tideline_mode='mongo', data_dir=tmp_path))
    repo.db = mongo_database
    graph = repo.load_graph()
    assert graph.has_edge('west', 'east')
    seed_references(mongo_database, land=[box(-21, 39, -19, 41)])
    updated = repo.load_graph()
    assert not updated.has_edge('west', 'east')
    assert updated.has_edge('west', 'north')


def test_corrupted_reference_bundle_fails_instead_of_using_local_defaults(mongo_database, tmp_path):
    version = mongo_database.planning_reference.find_one({'_id': 'active'})['version']
    mongo_database.planning_versions.update_one({'_id': version}, {'$set': {'data.vessel.fuelUsdPerTonne': 1}})
    repo = Repository(Settings(tideline_mode='mongo', data_dir=tmp_path))
    repo.db = mongo_database
    with pytest.raises(RouteError, match='integrity'):
        repo.load_graph()


def test_geo_near_uses_supported_approaches_across_dateline(mongo_database):
    ensure_indexes(mongo_database)
    for code, lon, supported in [('USAAA', -179.9, True), ('USBBB', 178, True), ('USCCC', 179.95, False)]:
        mongo_database.ports.insert_one({'locode': code, 'name': code, 'country': 'US', 'supported': supported,
            'routingNodeId': code, 'location': {'type': 'Point', 'coordinates': [0, 0]},
            'accessPoint': {'type': 'Point', 'coordinates': [lon, 35]}})
    repo = Repository(Settings(tideline_mode='mongo'))
    repo.db = mongo_database
    ports = repo.nearby_ports(179.9, 35, radius_nm=20)
    assert [p['id'] for p in ports] == ['USAAA']
    assert 9 < ports[0]['distanceNm'] < 11


def test_geo_restrictions_include_dateline_sides_and_passage_only_records(mongo_database):
    ensure_indexes(mongo_database)
    notices = [
        {'id': 'east', 'geometry': mapping(box(179.5, 34.9, 179.7, 35.1))},
        {'id': 'west-future', 'geometry': mapping(box(-179.7, 34.9, -179.5, 35.1)),
         'validFrom': '2099-01-01T00:00:00Z'},
        {'id': 'far', 'geometry': mapping(box(0, 34.9, 1, 35.1))},
        {'id': 'passage', 'passageId': 'test-passage'},
        {'id': 'cancelled', 'passageId': 'test-passage', 'cancelled': True},
        {'id': 'permanent', 'geometry': mapping(box(10, 10, 11, 11)), 'action': 'exclude', 'verified': True},
    ]
    mongo_database.restrictions.insert_many(notices)
    graph = nx.DiGraph()
    graph.add_edge('a', 'b', coordinates=[[179, 35], [-179, 35]], passageIds=['test-passage'])
    repo = Repository(Settings(tideline_mode='mongo'))
    repo.db = mongo_database
    assert [n['id'] for n in repo.restrictions()] == ['permanent']
    matched = repo.route_restrictions(graph, [['a', 'b']], [])
    assert {n['id'] for n in matched} == {'east', 'west-future', 'passage'}


def test_search_fallback_and_database_status(mongo_database, import_fixture):
    from scripts.configure_mongo import configure
    from pymongo.errors import WriteError
    source, access = import_fixture
    ImportBundle().load(source, access).apply(mongo_database)
    configure(mongo_database)
    mongo_database.source_status.insert_one({'_id': 'atlas_search_ports', 'enabled': True, 'indexName': 'missing'})
    repo = Repository(Settings(tideline_mode='mongo'))
    repo.db = mongo_database
    assert [p.id for p in repo.search_ports('Example East')] == ['GBXXX']
    assert [p.id for p in repo.search_ports('gbxxx')] == ['GBXXX']
    assert repo.data_status()['ports'] == {'catalogue': 2, 'supported': 2}
    with pytest.raises(WriteError):
        mongo_database.planning_versions.insert_one({'_id': 'bad-version'})
