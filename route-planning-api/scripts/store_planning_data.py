"""Store reviewed planning references and compressed coastline in MongoDB.

Local JSON supplies reviewed seed data. A complete versioned Mongo bundle is
activated only after its referenced files have been stored successfully.
"""
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import gridfs

from service.config import settings
from service.data import connect
from service.references import publish_references


def main():
    client, db = connect(settings)
    root = Path(__file__).resolve().parents[1]
    try:
        references = {'canals': 'data/planning/canals.json', 'vessel': 'data/planning/vessel.json',
                      'fuel-benchmarks': 'data/validation/fuel-benchmarks.json'}
        for name, relative_path in references.items():
            path = root / relative_path
            raw = path.read_bytes()
            db.planning_reference.replace_one({'_id': name}, {'_id': name, 'data': json.loads(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'importedAt': datetime.now(UTC)}, upsert=True)
        manifest = json.loads((root / 'data/geography/manifest.json').read_text())
        bucket = gridfs.GridFSBucket(db, bucket_name='reference_files')
        old = db.planning_reference.find_one({'_id': 'land-screen'})
        if not old or old.get('sha256') != manifest['sha256']:
            payload = gzip.compress((root / 'data/geography/gshhg-h.wkb.json').read_bytes(), mtime=0)
            file_id = bucket.upload_from_stream('gshhg-h.wkb.json.gz', payload,
                metadata={'sha256': manifest['sha256'], 'encoding': 'gzip', 'license': manifest['license']})
            db.planning_reference.replace_one({'_id': 'land-screen'}, dict(manifest, _id='land-screen',
                gridFsFileId=file_id, importedAt=datetime.now(UTC)), upsert=True)
        for path in (root / 'data/raw/canals').glob('*'):
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if db.reference_sources.find_one({'_id': digest}):
                continue
            file_id = bucket.upload_from_stream(path.name + '.gz', gzip.compress(raw, mtime=0))
            db.reference_sources.insert_one({'_id': digest, 'filename': path.name, 'gridFsFileId': file_id,
                'sha256': digest, 'retrievedAt': datetime.now(UTC), 'interpretation': 'Source evidence; not automatically executable restrictions'})
        version = publish_references(db)
        print(json.dumps({'activeReferenceVersion': version, 'planningReferences': db.planning_reference.count_documents({}),
                          'sourceArchives': db.reference_sources.count_documents({})}))
    finally:
        client.close()


if __name__ == '__main__':
    main()
