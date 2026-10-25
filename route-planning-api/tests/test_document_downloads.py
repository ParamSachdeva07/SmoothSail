from io import BytesIO
from types import SimpleNamespace

import gridfs
from bson import ObjectId
from fastapi.testclient import TestClient

from service.compliance_data import ComplianceStore, stored_document_link
from service.main import app

FILE_ID = '0123456789abcdef01234567'


def test_download_uses_only_registered_compliance_files_and_preserves_original_bytes(monkeypatch):
    raw = b'%PDF-1.7\noriginal document\n'
    document = BytesIO(raw)
    document.metadata = {'sourceId': 'public-rule', 'url': 'https://publisher.example/rule'}
    calls = []
    db = SimpleNamespace(compliance_sources=SimpleNamespace(find_one=lambda query:
        calls.append(query) or {'title': 'Public rule\r\nunsafe/header'}))
    class Bucket:
        def get(self, file_id):
            assert file_id == ObjectId(FILE_ID)
            return document
    def bucket(database, collection):
        assert database is db and collection == 'compliance_files'
        return Bucket()
    monkeypatch.setattr(gridfs, 'GridFS', bucket)
    store = ComplianceStore(SimpleNamespace(settings=SimpleNamespace(tideline_mode='mongo'), database=lambda: db))
    assert store.download_document('../forecast_files') is None
    content, filename = store.download_document(FILE_ID)
    assert content.read() == raw
    assert filename.endswith('.pdf') and '\r' not in filename and '/' not in filename
    assert calls == [{'_id': 'public-rule'}]  # No current-version requirement: older cited bytes remain accessible.
    content.close()


def test_unregistered_and_missing_files_are_not_downloadable(monkeypatch):
    db = SimpleNamespace(compliance_sources=SimpleNamespace(find_one=lambda query: None))
    document = BytesIO(b'not a registered public document')
    document.metadata = {'sourceId': 'unknown'}
    monkeypatch.setattr(gridfs, 'GridFS', lambda *args, **kwargs: SimpleNamespace(get=lambda file_id: document))
    store = ComplianceStore(SimpleNamespace(settings=SimpleNamespace(tideline_mode='mongo'), database=lambda: db))
    assert store.download_document(FILE_ID) is None and document.closed
    def missing(file_id):
        raise gridfs.NoFile()
    monkeypatch.setattr(gridfs, 'GridFS', lambda *args, **kwargs: SimpleNamespace(get=missing))
    assert store.download_document(FILE_ID) is None


def test_download_endpoint_streams_attachment_and_closes_file():
    raw = b'%PDF-1.7\n' + b'x' * 600000
    document = BytesIO(raw)
    document.length = len(raw)
    with TestClient(app) as client:
        app.state.compliance.store.download_document = lambda file_id: (document, 'source.pdf') if file_id == FILE_ID else None
        response = client.get(f'/compliance/documents/{FILE_ID}/download', headers={'Accept-Encoding': 'identity'})
        assert response.content == raw and document.closed
        assert response.headers['content-disposition'] == 'attachment; filename="source.pdf"'
        assert response.headers['content-type'] == 'application/octet-stream'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['content-length'] == str(len(raw))
        assert client.get('/compliance/documents/missing/download').status_code == 404


def test_download_link_is_pinned_to_gridfs_not_a_mutable_publisher_url():
    assert stored_document_link({'gridFsFileId': ObjectId(FILE_ID)}) == {
        'download_path': f'/compliance/documents/{FILE_ID}/download'}
    assert stored_document_link({}) == {}
