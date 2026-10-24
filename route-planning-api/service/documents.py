"""Bounded, in-memory text extraction; uploads are never stored in Atlas."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader

from service.compliance_models import DocumentReference

MAX_UPLOAD = 10 * 1024 * 1024
MAX_TEXT = 200000


def extract_document(name, content):
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError('Upload a non-empty file of up to 10 MiB.')
    title = Path(name).name[:200]
    digest = sha256(content).hexdigest()
    suffix = Path(title).suffix.lower()
    pages = []
    if suffix == '.pdf':
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError('Use an unencrypted PDF of at most 200 pages.')
        for index, page in enumerate(reader.pages):
            pages.append((index + 1, page.extract_text() or ''))
    elif suffix == '.docx':
        try:
            with ZipFile(BytesIO(content)) as archive:
                info = archive.getinfo('word/document.xml')
                if info.file_size > MAX_UPLOAD:
                    raise ValueError('The document is too large when expanded.')
                root = ElementTree.fromstring(archive.read(info))
                pages = [(None, '\n'.join(''.join(p.itertext()) for p in root.iter()
                    if p.tag.endswith('}p')))]
        except (BadZipFile, KeyError, ParseError, DefusedXmlException) as exc:
            raise ValueError('Unreadable DOCX file.') from exc
    elif suffix in ('.txt', '.csv', '.md'):
        pages = [(None, content.decode('utf-8-sig'))]
    else:
        raise ValueError('Supported files: PDF, DOCX, TXT, CSV and Markdown. Paste OCR text for scanned images.')
    text = '\n\n'.join(value for _, value in pages).strip()
    if not text:
        raise ValueError('No readable text found. This may be a scanned document; paste its OCR text instead.')
    if len(text) > MAX_TEXT:
        raise ValueError('Extracted text exceeds 200,000 characters. Use a smaller document; nothing was truncated.')
    references = [DocumentReference(id=f'upload:{digest}:{page or 1}:{offset}', title=title, page=page, text=value[offset:offset + 8000])
                  for page, value in pages if value.strip() for offset in range(0, len(value), 8000)]
    return {'text': text, 'sha256': digest, 'references': [r.model_dump(mode='json', by_alias=True) for r in references],
            'stored': False}
