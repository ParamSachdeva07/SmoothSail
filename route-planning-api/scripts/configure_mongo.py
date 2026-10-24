"""Configure Mongo indexes/validation; optionally build Atlas port autocomplete."""
import argparse
import json

from service.config import settings
from service.data import connect, ensure_indexes

SEARCH_NAME = 'tideline_ports_v1'
SEARCH_DEFINITION = {'mappings': {'dynamic': False, 'fields': {
    'name': {'type': 'autocomplete', 'tokenization': 'edgeGram', 'minGrams': 2, 'maxGrams': 20, 'foldDiacritics': True},
    'locode': {'type': 'autocomplete', 'tokenization': 'edgeGram', 'minGrams': 2, 'maxGrams': 5},
    'supported': {'type': 'boolean'},
}}}


def configure(db, atlas_search=False):
    ensure_indexes(db)
    schema = {'bsonType': 'object', 'required': ['_id', 'data', 'publishedAt'], 'properties': {
        '_id': {'bsonType': 'string', 'pattern': '^[a-f0-9]{64}$'},
        'data': {'bsonType': 'object', 'required': ['vessel', 'canals', 'land'], 'properties': {
            'vessel': {'bsonType': 'object'}, 'canals': {'bsonType': 'object'},
            'land': {'bsonType': 'object', 'required': ['sha256', 'name', 'gridFsFileId']}}},
        'publishedAt': {'bsonType': 'date'},
    }}
    if 'planning_versions' not in db.list_collection_names():
        db.create_collection('planning_versions', validator={'$jsonSchema': schema})
    else:
        db.command('collMod', 'planning_versions', validator={'$jsonSchema': schema},
                   validationLevel='strict', validationAction='error')
    result = {'indexes': 'configured', 'referenceValidation': 'enabled'}
    if atlas_search:
        indexes = list(db.ports.list_search_indexes(SEARCH_NAME))
        if not indexes:
            db.ports.create_search_index({'name': SEARCH_NAME, 'definition': SEARCH_DEFINITION})
        db.source_status.update_one({'_id': 'atlas_search_ports'},
            {'$set': {'enabled': True, 'indexName': SEARCH_NAME}}, upsert=True)
        result['atlasSearch'] = {'indexName': SEARCH_NAME,
                                'status': indexes[0].get('status') if indexes else 'build_requested',
                                'note': 'API falls back to literal search while the index is unavailable.'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--atlas-search', action='store_true')
    args = parser.parse_args()
    client, db = connect(settings)
    try:
        print(json.dumps(configure(db, args.atlas_search)))
    finally:
        client.close()


if __name__ == '__main__':
    main()
