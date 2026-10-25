"""One archive: displayed checklist, preparation guides, and retrievable public files.

Only the registered public-reference bucket and approved HTTPS publishers are read.
The package never fabricates an issued vessel certificate or a completed declaration.
"""
import asyncio
import hashlib
import json
import re
from tempfile import SpooledTemporaryFile
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from pymongo.errors import PyMongoError

from service.checklist_pdf import render_pdf
from service.compliance_data import official_url, public_text

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_BYTES = 48 * 1024 * 1024
MAX_FILES = 40


def slug(value):
    return re.sub(r'[^A-Za-z0-9_-]+', '-', str(value)).strip('-_')[:80] or 'document'


def target(source):
    path = source.get('downloadPath') or ''
    if re.fullmatch(r'/compliance/documents/[0-9a-f]{24}/download', path):
        return 'stored:' + path.split('/')[3]
    return 'web:' + str(source.get('url') or '').split('#')[0]


def collect_assets(snapshot):
    assets, requirements = {}, []
    def add(value, document_id=None):
        source = value['evidence']
        if not source.get('downloadPath') and not source.get('url'):
            return None
        key = target(source)
        if key not in assets:
            assets[key] = {'key': key, 'title': value.get('title') or source['title'],
                'kind': value.get('kind', 'reference'), 'source': source, 'documentIds': []}
        asset = assets[key]
        if value.get('kind') == 'blank_form': asset['kind'] = 'blank_form'
        # A single shared source is downloaded once, and related requirements retain their own kind.
        if document_id and document_id not in asset['documentIds']: asset['documentIds'].append(document_id)
        return key
    for index, document in enumerate(snapshot['documents'], 1):
        links = []
        explicit = document.get('downloadAssets') or []
        values = explicit + [{'title': e['title'], 'kind': 'reference', 'evidence': e} for e in document.get('evidence', [])]
        for value in values:
            key = add(value, document['id'])
            if key:
                relation = {'key': key, 'kind': value.get('kind', 'reference')}
                if relation not in links: links.append(relation)
        requirements.append({'id': document['id'], 'title': document['title'],
            'guidePath': f'prepare-or-verify/{index:02d}-{slug(document["title"])}.txt', 'assets': links})
    for action in snapshot['actions']:
        for source in action.get('evidence', []): add({'title': source['title'], 'kind': 'reference', 'evidence': source})
    return assets, requirements


async def read_asset(asset, store, client):
    key, source = asset['key'], asset['source']
    if key.startswith('stored:'):
        def stored():
            result = store.download_document(key.removeprefix('stored:'))
            if result is None: raise ValueError('Stored reference is no longer available.')
            file, filename = result
            try:
                if getattr(file, 'length', 0) > MAX_FILE_BYTES: raise ValueError('File exceeds the package size limit.')
                content = file.read(MAX_FILE_BYTES + 1)
                if len(content) > MAX_FILE_BYTES: raise ValueError('File exceeds the package size limit.')
                return content, filename
            finally:
                file.close()
        content, filename = await asyncio.to_thread(stored)
        return normalize_file(content, filename, asset)
    url = str(source.get('url') or '')
    for _ in range(4):
        if not official_url(url) or urlsplit(url).password is not None:
            raise ValueError('File is not on an approved public publisher; use the cited link.')
        async with client.stream('GET', url, headers={'User-Agent': 'SmoothSail/1.0 public-document-package'}) as response:
            if response.is_redirect:
                url = str(response.url.join(response.headers.get('location', '')))
                continue
            response.raise_for_status()
            if int(response.headers.get('content-length', '0')) > MAX_FILE_BYTES:
                raise ValueError('File exceeds the package size limit.')
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_FILE_BYTES: raise ValueError('File exceeds the package size limit.')
            filename = urlsplit(str(response.url)).path.rsplit('/', 1)[-1] or 'reference.html'
            return normalize_file(bytes(data), filename, asset, response.headers.get('content-type', ''))
    raise ValueError('Publisher redirect could not be resolved within the package budget.')


def normalize_file(content, filename, asset, content_type=''):
    if not content: raise ValueError('Publisher returned an empty file.')
    prefix = content[:1000].lstrip().lower()
    if content.startswith(b'%PDF'):
        return content, 'pdf', 'original_file'
    suffix = filename.rsplit('.', 1)[-1].lower()
    if b'<html' in prefix or b'<!doctype html' in prefix or 'html' in content_type or suffix in ('html', 'htm'):
        if asset['kind'] == 'blank_form':
            raise ValueError('This is an online page, not a downloadable blank form; obtain it at the cited link.')
        pages = public_text(content, 'text/html')
        text = '\n\n'.join(text for _, text in pages)
        if not text.strip(): raise ValueError('Publisher page has no readable reference text.')
        return text.encode('utf-8'), 'txt', 'reference_text'
    if 'wordprocessingml.document' in content_type: suffix = 'docx'
    elif 'spreadsheetml.sheet' in content_type: suffix = 'xlsx'
    if content.startswith(b'PK\x03\x04') and suffix in ('docx', 'xlsx'):
        return content, suffix, 'original_file'
    if suffix in ('txt', 'csv', 'json', 'xml', 'rtf'):
        content.decode('utf-8-sig')  # Reject binary error responses masquerading as text files.
        return content, suffix, 'original_file'
    raise ValueError('No supported downloadable document was returned; use the cited link.')


def preparation_guide(document, requirement, files):
    text = [document['title'], '=' * min(80, len(document['title'])), '',
        'This is a preparation/verification guide, not the actual issued or signed document.',
        'Downloaded references and blank forms do not prove that your voyage requirement is satisfied.', '',
        'Applicability: ' + document['applicability'].replace('_', ' '),
        'Port scope: ' + (', '.join(document.get('portIds', [])) or 'See the selected voyage'), '',
        'Purpose: ' + document['purpose'], 'Provider / issuer: ' + (document.get('provider') or 'Confirm with the relevant issuer.'),
        'Timing: ' + (document.get('timing') or 'Confirm with the relevant issuer.'),
        'How to obtain: ' + (document.get('obtainInstructions') or 'Contact the responsible issuer or provider.'), '',
        'Information needed:']
    text.extend('- ' + item for item in document.get('missingInputs', []))
    text.extend(['', 'Available files and cited links:'])
    for relation in requirement['assets']:
        record = files[relation['key']]
        text.extend([f"- {relation['kind'].replace('_', ' ')}: {record['title']}",
            '  Package file: ' + record.get('path', 'Not included'),
            '  Status: ' + record['status'], '  Source: ' + str(record.get('url') or record.get('downloadPath') or ''),
            '  Note: ' + record.get('note', '')])
    if not requirement['assets']: text.append('- No downloadable file identified. Follow the obtaining instructions above.')
    return '\n'.join(text) + '\n'


async def build_bundle(snapshot, checked, notes, store, *, transport=None, pdf_content=None):
    pdf = pdf_content if pdf_content is not None else await asyncio.to_thread(render_pdf, snapshot, checked, notes)
    assets, requirements = collect_assets(snapshot)
    files = {key: {'title': asset['title'], 'kind': asset['kind'], 'documentIds': asset['documentIds'],
        'url': asset['source'].get('url'), 'downloadPath': asset['source'].get('downloadPath'),
        'status': 'unavailable', 'note': 'Package download limit reached; use the cited link.'} for key, asset in assets.items()}
    archive = SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode='w+b')
    pending = set()
    try:
        with ZipFile(archive, 'w', compression=ZIP_DEFLATED, compresslevel=3) as bundle:
            bundle.writestr('SmoothSail-voyage-checklist.pdf', pdf)
            semaphore, total = asyncio.Semaphore(4), 0
            async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=8), transport=transport, follow_redirects=False) as client:
                async def retrieve(asset):
                    async with semaphore:
                        try:
                            content, suffix, representation = await read_asset(asset, store, client)
                            return asset, content, suffix, representation, None
                        except (httpx.HTTPError, ValueError, UnicodeError, PyMongoError) as error:
                            # Errors are per file: the checklist and other available documents still download.
                            note = str(error) if isinstance(error, ValueError) else 'File could not be retrieved; use its cited link or contact the issuer.'
                            return asset, None, None, None, note
                pending = {asyncio.create_task(retrieve(asset)) for asset in list(assets.values())[:MAX_FILES]}
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        asset, content, suffix, representation, error = task.result()
                        record = files[asset['key']]
                        if error:
                            record['note'] = error
                            continue
                        if total + len(content) > MAX_TOTAL_BYTES:
                            record['note'] = 'Total package size limit reached; use the cited link.'
                            continue
                        total += len(content)
                        folder = 'blank-forms' if asset['kind'] == 'blank_form' else 'references'
                        digest = hashlib.sha256(content).hexdigest()
                        path = f'{folder}/{slug(asset["title"])}-{digest[:8]}.{suffix}'
                        if path not in bundle.namelist(): bundle.writestr(path, content)
                        record.update(path=path, status='included', representation=representation, sha256=digest, bytes=len(content), note='')
                    done.clear()
            for document, requirement in zip(snapshot['documents'], requirements):
                bundle.writestr(requirement['guidePath'], preparation_guide(document, requirement, files))
                included = [files[r['key']] for r in requirement['assets'] if files[r['key']]['status'] == 'included']
                requirement['availability'] = ('blank_form_included' if any(r['kind'] == 'blank_form' and files[r['key']]['status'] == 'included' for r in requirement['assets'])
                    else 'references_only' if included else 'obtain_from_issuer')
            index = {'checklistId': snapshot['id'], 'routeId': snapshot['routeId'], 'requirements': requirements,
                'files': list(files.values()), 'notice': 'Blank forms and references are not issued certificates or completed declarations.'}
            bundle.writestr('document-index.json', json.dumps(index, ensure_ascii=False, indent=2))
            included_count = sum(f['status'] == 'included' for f in files.values())
            text = ['SmoothSail voyage document package', '=================================', '',
                'Includes the checklist PDF, one preparation guide for EVERY listed document, and available public blank forms/references.',
                'Issued vessel certificates, signed declarations, insurance endorsements and booking confirmations must come from the operator, shipper or issuer.',
                'A blank form or reference is not a completed or verified voyage document. Checkmarks only record your own checklist progress.', '',
                f'Listed documents: {len(requirements)}', f'Available source files included: {included_count} / {len(files)}', '',
                'Folders: blank-forms/ contains identified blank forms; references/ contains source files or readable reference text;',
                'prepare-or-verify/ contains obtaining instructions and missing information for every recommendation.',
                'document-index.json maps every recommendation to included files, source links and unavailable-file reasons.', '', 'Document availability:']
            text.extend(f'- {r["title"]}: {r["availability"].replace("_", " ")}; guide: {r["guidePath"]}' for r in requirements)
            text.extend(['', 'Files not included:'])
            text.extend(f'- {f["title"]}: {f["note"]}' for f in files.values() if f['status'] != 'included')
            if all(f['status'] == 'included' for f in files.values()): text.append('- None among identified source files. This does not mean all issued voyage documents are available.')
            bundle.writestr('README.txt', '\n'.join(text) + '\n')
        archive.seek(0)
        return archive
    except BaseException:
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        archive.close()
        raise
