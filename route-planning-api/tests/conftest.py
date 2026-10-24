import json

import pytest


@pytest.fixture
def import_fixture(tmp_path):
    source = tmp_path / 'raw'
    source.mkdir()
    (source / 'ports.csv').write_text('locode,name,country,longitude,latitude\nGBXXX,Example East,GB,-15,40\nUSXXX,Example West,US,-25,40\n')
    network = {'type': 'TidelineNetwork', 'nodes': [
        {'id': 'west', 'coordinates': [-25, 40]}, {'id': 'east', 'coordinates': [-15, 40]},
        {'id': 'north', 'coordinates': [-20, 45]},
    ], 'edges': [{'from': 'west', 'to': 'east'}, {'from': 'west', 'to': 'north'}, {'from': 'north', 'to': 'east'}]}
    (source / 'network.json').write_text(json.dumps(network))
    access = tmp_path / 'access.json'
    access.write_text(json.dumps({'GBXXX': {'nodeId': 'east', 'coordinates': [-15, 40]},
                                 'USXXX': {'nodeId': 'west', 'coordinates': [-25, 40]}}))
    return source, access
