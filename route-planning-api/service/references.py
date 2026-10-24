"""Versioned Mongo planning inputs, pinned for the duration of each calculation."""
import gzip
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

import gridfs
from shapely import from_wkb

from service.models import RouteError

_active = ContextVar('planning_references', default=None)


@dataclass(frozen=True)
class PlanningReferences:
    version: str
    vessel: dict
    canals: dict
    land: object


def active_references():
    return _active.get()


@contextmanager
def use_references(references):
    token = _active.set(references)
    try:
        yield references
    finally:
        _active.reset(token)


def reference_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def publish_references(db):
    """Publish only a complete bundle; one pointer switches readers atomically."""
    records = {r['_id']: r for r in db.planning_reference.find(
        {'_id': {'$in': ['vessel', 'canals', 'land-screen']}})}
    if set(records) != {'vessel', 'canals', 'land-screen'}:
        raise ValueError('Store vessel, canal and land references before publishing.')
    land = {k: v for k, v in records['land-screen'].items() if k not in ['_id', 'importedAt']}
    if not db.reference_files.files.find_one({'_id': land['gridFsFileId']}):
        raise ValueError('Land reference file is missing.')
    data = {'vessel': records['vessel']['data'], 'canals': records['canals']['data'], 'land': land}
    version = reference_hash(data)
    now = datetime.now(UTC)
    db.planning_versions.update_one({'_id': version}, {'$setOnInsert': {'data': data, 'publishedAt': now}}, upsert=True)
    db.planning_reference.replace_one({'_id': 'active'},
        {'_id': 'active', 'version': version, 'activatedAt': now}, upsert=True)
    return version


def load_references(db, directory, version):
    from service.navigation import LandMask
    if not re.fullmatch(r'[a-f0-9]{64}', version):
        raise RouteError('references_invalid', 'The active reference version is invalid.', 503)
    record = db.planning_versions.find_one({'_id': version})
    if not record or reference_hash(record['data']) != version:
        raise RouteError('references_corrupt', 'Planning references failed their integrity check.', 503)
    data = record['data']
    manifest = data['land']
    digest = manifest['sha256']
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise RouteError('references_corrupt', 'Land reference checksum is invalid.', 503)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'land-{digest}.json'
    payload = path.read_bytes() if path.exists() else None
    if payload is None or hashlib.sha256(payload).hexdigest() != digest:
        bucket = gridfs.GridFSBucket(db, bucket_name='reference_files')
        try:
            with bucket.open_download_stream(manifest['gridFsFileId']) as stream:
                payload = gzip.decompress(stream.read())
        except (gridfs.errors.NoFile, OSError, EOFError):
            raise RouteError('references_corrupt', 'The stored land reference cannot be read.', 503) from None
        if hashlib.sha256(payload).hexdigest() != digest:
            raise RouteError('references_corrupt', 'The stored land reference failed its checksum.', 503)
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
            temporary.write(payload)
            temporary_path = temporary.name
        os.replace(temporary_path, path)
    land = LandMask(from_wkb(json.loads(payload)))
    land.source_sha256 = digest
    land.name = manifest['name']
    return PlanningReferences(version, data['vessel'], data['canals'], land)
