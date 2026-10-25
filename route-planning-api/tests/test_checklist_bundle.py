import asyncio
import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
from fastapi.testclient import TestClient

from service.checklist_bundle import build_bundle, normalize_file, MAX_FILE_BYTES
from service.main import app
from test_checklist import body, generate, service, displayed_snapshot, EVIDENCE

FILE_ID = '0123456789abcdef01234567'
FORM_ID = '1123456789abcdef01234567'


def source(file_id=FILE_ID):
    return EVIDENCE | {'id': file_id, 'downloadPath': f'/compliance/documents/{file_id}/download'}


def snapshot():
    result = asyncio.run(generate(service(), body()))
    result['documents'][0]['evidence'] = [source()]
    result['documents'][0]['downloadAssets'] = [
        {'title': 'Official blank form', 'kind': 'blank_form', 'evidence': source(FORM_ID)},
        {'title': 'Official guidance', 'kind': 'reference', 'evidence': source()}]
    result['documents'].append(result['documents'][0] | {'id': 'd-issued', 'title': 'Issued vessel certificate',
        'evidence': [], 'downloadAssets': [], 'provider': 'Vessel operator / issuing authority'})
    for action in result['actions']: action['evidence'] = []
    return result


class Store:
    def __init__(self): self.reads = []; self.files = []
    def download_document(self, file_id):
        self.reads.append(file_id)
        stream = BytesIO(b'%PDF-original-' + file_id.encode())
        stream.length = len(stream.getvalue()); self.files.append(stream)
        return stream, '../unsafe-filename.pdf'


def test_package_contains_pdf_every_preparation_guide_and_original_deduplicated_sources():
    data = snapshot(); store = Store()
    # Same file used for another requirement should be included only once.
    data['documents'][1]['evidence'] = [source()]
    archive = asyncio.run(build_bundle(data, [], {}, store, pdf_content=b'%PDF-checklist'))
    with archive, ZipFile(archive) as package:
        names = package.namelist()
        assert package.read('SmoothSail-voyage-checklist.pdf') == b'%PDF-checklist'
        assert len([n for n in names if n.startswith('prepare-or-verify/')]) == 2
        assert len([n for n in names if n.startswith('blank-forms/')]) == 1
        assert len([n for n in names if n.startswith('references/')]) == 1
        assert all('..' not in n and not n.startswith('/') for n in names)
        assert sorted(store.reads) == sorted([FILE_ID, FORM_ID])
        assert all(f.closed for f in store.files)
        index = json.loads(package.read('document-index.json'))
        assert index['requirements'][0]['availability'] == 'blank_form_included'
        assert index['requirements'][1]['availability'] == 'references_only'
        guide = package.read(index['requirements'][1]['guidePath']).decode()
        assert 'not the actual issued or signed document' in guide
        assert 'Vessel operator / issuing authority' in guide
        assert 'Issued vessel certificates' in package.read('README.txt').decode()
        for item in index['files']:
            assert package.read(item['path']).startswith(b'%PDF-original-')


def test_missing_or_oversized_sources_do_not_break_package_or_fabricate_certificates():
    data = snapshot()
    class Missing:
        def download_document(self, file_id):
            if file_id == FILE_ID: return None
            stream = BytesIO(b'not read'); stream.length = MAX_FILE_BYTES + 1
            return stream, 'big.pdf'
    archive = asyncio.run(build_bundle(data, [], {}, Missing(), pdf_content=b'%PDF-checklist'))
    with archive, ZipFile(archive) as package:
        index = json.loads(package.read('document-index.json'))
        assert all(item['status'] == 'unavailable' for item in index['files'])
        assert len(package.namelist()) == 5  # PDF, 2 preparation guides, JSON index, README.
        assert all(r['availability'] == 'obtain_from_issuer' for r in index['requirements'])
        assert 'size limit' in package.read('README.txt').decode()
        assert not any('Issued-vessel-certificate.pdf' in n for n in package.namelist())


def test_web_download_validates_every_redirect_and_does_not_follow_to_private_hosts():
    data = snapshot(); requests = []
    src = EVIDENCE | {'url': 'https://www.gov.uk/document.pdf'}
    data['documents'][0]['evidence'] = [src]; data['documents'][0]['downloadAssets'] = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'Location': 'https://127.0.0.1/private'})
    archive = asyncio.run(build_bundle(data, [], {}, Store(), transport=httpx.MockTransport(handler), pdf_content=b'%PDF-checklist'))
    with archive, ZipFile(archive) as package:
        index = json.loads(package.read('document-index.json'))
        assert index['files'][0]['status'] == 'unavailable'
        assert requests == ['https://www.gov.uk/document.pdf']


def test_html_guidance_is_readable_text_but_portal_is_not_mislabelled_as_blank_form():
    import pytest
    raw = b'<html><script>secret script</script><body><p>Reference guidance</p></body></html>'
    data, extension, representation = normalize_file(raw, 'guide.html', {'kind': 'reference'})
    assert b'Reference guidance' in data and b'secret script' not in data
    assert extension == 'txt' and representation == 'reference_text'
    with pytest.raises(ValueError, match='online page'):
        normalize_file(raw, 'form.html', {'kind': 'blank_form'})


def test_bundle_endpoint_works_after_context_expiry_and_streams_a_zip_attachment(monkeypatch):
    data = snapshot(); store = Store()
    monkeypatch.setattr(app.state, 'compliance', SimpleNamespace(contexts={}, store=store), raising=False)
    payload = body().model_dump(by_alias=True) | {'checklistId': data['id'], 'snapshot': displayed_snapshot(data)}
    response = TestClient(app).post('/voyages/checklist/bundle', json=payload)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert 'attachment' in response.headers['content-disposition']
    with ZipFile(BytesIO(response.content)) as package:
        assert package.read('SmoothSail-voyage-checklist.pdf').startswith(b'%PDF')
        assert package.testzip() is None
        assert len([n for n in package.namelist() if n.startswith('prepare-or-verify/')]) == 2
