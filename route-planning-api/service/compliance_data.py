"""Versioned public references, bounded retrieval and official-source adapters."""
import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlsplit

import gridfs
import httpx
from pymongo import UpdateOne
from pymongo.errors import OperationFailure
from pypdf import PdfReader

from service.compliance_models import Evidence

SOURCES = [
    ('jwc', 'security', 'Joint War Committee', 'https://lmalloyds.com/committee/joint-war-committee/'),
    ('ibf', 'security', 'IBF designated risk areas', 'https://www.itfseafarers.org/en/resources/ibf-warlike-and-high-risk-areas'),
    ('jwc_035', 'security', 'JWC JWLA-035 listed areas, September 2026', 'https://lmalloyds.com/wp-content/uploads/2026/09/JWLA-035-Black-Sea.pdf'),
    ('ibf_oct2026', 'security', 'IBF designated areas, 15 October 2026', 'https://www.itfseafarers.org/sites/default/files/node/resources/files/IBF%20List%20of%20designated%20risk%20Areas%20with%20applicable%20benefits%20%28as%20of%2015th%20of%20October%202026%29%20%28002%29.pdf'),
    ('ets', 'environment', 'European Commission maritime ETS FAQ', 'https://climate.ec.europa.eu/areas-action/transport-decarbonisation/reducing-emissions-shipping-sector/faq-maritime-transport-eu-emissions-trading-system-ets_en'),
    ('fueleu', 'environment', 'European Commission FuelEU questions and answers', 'https://transport.ec.europa.eu/transport-modes/maritime/decarbonising-maritime-transport-fueleu-maritime/questions-and-answers-regulation-eu-20231805-use-renewable-and-low-carbon-fuels-maritime-transport_en'),
    ('cii', 'environment', 'IMO CII guidance', 'https://www.imo.org/en/mediacentre/hottopics/pages/eexi-cii-faq.aspx'),
    ('taric', 'trade', 'European Commission TARIC', 'https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/eu-customs-tariff-taric_en'),
    ('hts', 'trade', 'USITC Harmonized Tariff Schedule', 'https://hts.usitc.gov/'),
    ('ics2', 'trade', 'European Commission ICS2', 'https://taxation-customs.ec.europa.eu/customs/customs-security/import-control-system-2_en'),
    ('uksl', 'sanctions', 'UK Sanctions List', 'https://www.gov.uk/government/publications/the-uk-sanctions-list'),
    ('ofac', 'sanctions', 'OFAC Sanctions List Service', 'https://ofac.treasury.gov/sanctions-list-service'),
    ('ofac_ownership', 'sanctions', 'OFAC 50 Percent Rule', 'https://ofac.treasury.gov/faqs/401'),
    ('eu_sanctions', 'sanctions', 'EU sanctions resources', 'https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures/overview-sanctions-and-related-resources_en'),
    ('imdg', 'dangerous_goods', 'IMO IMDG Code', 'https://www.imo.org/en/publications/pages/imdg%20code.aspx'),
]

OFFICIAL_DOMAINS = {
    'security': ('lmalloyds.com', 'itfseafarers.org', 'iial.co.uk', 'imo.org', 'maritime.dot.gov', 'mscio.eu'),
    'environment': ('europa.eu', 'imo.org', 'eex.com', 'gov.uk'),
    'trade': ('europa.eu', 'gov.uk', 'trade-tariff.service.gov.uk', 'usitc.gov', 'ustr.gov', 'cbp.gov',
              'ecfr.gov', 'portofrotterdam.com', 'haropaport.com', 'hamburg-port-authority.de', 'mpa.gov.sg', 'pancanal.com', 'suezcanal.gov.eg'),
    'sanctions': ('treasury.gov', 'gov.uk', 'europa.eu', 'un.org', 'imo.org', 'ecfr.gov', 'state.gov', 'bis.gov'),
    'dangerous_goods': ('imo.org', 'unece.org', 'phmsa.dot.gov', 'ecfr.gov', 'gov.uk', 'europa.eu'),
}


def official_url(url, category=None):
    parts = urlsplit(str(url))
    domains = OFFICIAL_DOMAINS.get(category, tuple(d for values in OFFICIAL_DOMAINS.values() for d in values))
    return parts.scheme == 'https' and not parts.username and parts.port in (None, 443) and any(
        parts.hostname == d or (parts.hostname or '').endswith('.' + d) for d in domains)


def utc(value):
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def applicable(row, when):
    return (row.get('policyStatus', 'adopted') in ('adopted', 'effective')
            and (not row.get('effectiveFrom') or utc(row['effectiveFrom']) <= when)
            and (not row.get('effectiveTo') or utc(row['effectiveTo']) > when))


def normalize_name(value):
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()).strip()


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        elif tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'tr'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def public_text(content, content_type):
    if content.startswith(b'%PDF'):
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > 1000:
            raise ValueError('Source exceeds page limit.')
        return [(str(i + 1), page.extract_text() or '') for i, page in enumerate(reader.pages)]
    text = content.decode('utf-8-sig', errors='replace')
    if 'html' in content_type or '<html' in text[:1000].lower():
        parser = TextHTML()
        parser.feed(text)
        text = '\n'.join(re.sub(r'\s+', ' ', p).strip() for p in ''.join(parser.parts).splitlines() if p.strip())
    return [('document', text)]


async def fetch_official(url, category=None, transport=None):
    """Only approved HTTPS publishers; validate every redirect before following it."""
    async with httpx.AsyncClient(timeout=25, transport=transport) as client:
        for _ in range(5):
            if not official_url(url, category):
                raise ValueError('This publisher is outside the approved source registry.')
            async with client.stream('GET', url, headers={'User-Agent': 'SmoothSail/1.0 public-source-reader'}) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers['location']))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 32 * 1024 * 1024:
                        raise ValueError('Public reference exceeds the download limit.')
                content = bytes(data)
                return str(response.url), content, public_text(content, response.headers.get('content-type', ''))
        raise ValueError('Too many source redirects.')


def ensure_compliance_indexes(db, atlas_search=False):
    db.compliance_sources.create_index('category')
    db.compliance_documents.create_index([('sourceId', 1), ('snapshotId', 1)])
    db.compliance_documents.create_index([('text', 'text')], default_language='none')
    db.sanctions_entities.create_index([('sourceId', 1), ('snapshotId', 1), ('imo', 1)])
    db.sanctions_entities.create_index([('sourceId', 1), ('snapshotId', 1), ('normalizedNames', 1)])
    db.commodity_codes.create_index([('sourceId', 1), ('snapshotId', 1), ('code', 1)])
    db.maritime_zones.create_index([('geometry', '2dsphere')])
    for name in ('compliance_rules', 'tariff_measures', 'port_fee_schedules', 'port_baselines', 'vessel_facts', 'market_observations'):
        db[name].create_index([('sourceId', 1), ('snapshotId', 1)])
    db.market_observations.create_index([('instrument', 1), ('observedAt', -1)])
    db.api_cache.create_index('expiresAt', expireAfterSeconds=0)
    if atlas_search:
        name = 'compliance_documents_v1'
        if not list(db.compliance_documents.list_search_indexes(name)):
            db.compliance_documents.create_search_index({'name': name, 'definition': {'mappings': {
                'dynamic': False, 'fields': {'text': {'type': 'string'}, 'category': {'type': 'token'},
                                           'snapshotId': {'type': 'token'}}}}})


def publish_snapshot(db, source, raw, pages=(), records=None):
    """Immutable snapshot rows, then a single atomic source-pointer publication."""
    raw_digest = hashlib.sha256(raw).hexdigest()
    parser_version = str(source.get('parserVersion', '1'))
    identity = f'{raw_digest}:parser:{parser_version}' + (f':reviewed:{source["reviewed"]}' if 'reviewed' in source else '')
    digest = raw_digest if parser_version == '1' and 'reviewed' not in source else hashlib.sha256(identity.encode()).hexdigest()
    source_id = source['id']
    now = datetime.now(UTC)
    manifest = db.compliance_sources.find_one({'_id': source_id}) or {}
    previous_count = manifest.get('counts', {}).get('sanctions_entities', 0)
    new_entities = (records or {}).get('sanctions_entities')
    if previous_count > 100 and new_entities is not None and len(new_entities) < previous_count * .8:
        raise ValueError('Unexpected sanctions-record decrease; previous active snapshot retained.')
    if manifest.get('activeVersion') == digest:
        db.compliance_sources.update_one({'_id': source_id}, {'$set': {'checkedAt': now,
            'refreshAfter': now + timedelta(hours=source.get('refreshHours', 24))}})
        return {'source': source_id, 'version': digest, 'changed': False}
    bucket = gridfs.GridFS(db, collection='compliance_files')
    file_id = bucket.find_one({'metadata.sha256': raw_digest})
    file_id = file_id._id if file_id else bucket.put(raw, filename=source['title'], metadata={
        'sha256': raw_digest, 'sourceId': source_id, 'url': source['url']})
    base = {'sourceId': source_id, 'snapshotId': digest, 'category': source['category'], 'retrievedAt': now}
    documents = []
    for page, text in pages:
        for offset in range(0, len(text), 3500):
            passage = text[offset:offset + 4000]
            if passage.strip():
                documents.append(base | {'_id': f'{source_id}:{digest}:{page}:{offset}', 'text': passage,
                                        'pageOrSection': page})
    if documents:
        db.compliance_documents.bulk_write([UpdateOne({'_id': d['_id']}, {'$setOnInsert': d}, upsert=True)
                                            for d in documents], ordered=False)
    counts = {'compliance_documents': len(documents)}
    for collection, rows in (records or {}).items():
        if rows:
            normalized = [base | row | {'_id': f'{source_id}:{digest}:{i}'} for i, row in enumerate(rows)]
            db[collection].bulk_write([UpdateOne({'_id': d['_id']}, {'$setOnInsert': d}, upsert=True)
                                      for d in normalized], ordered=False)
        counts[collection] = len(rows)
    db.compliance_sources.replace_one({'_id': source_id}, source | {'_id': source_id,
        'activeVersion': digest, 'gridFsFileId': file_id, 'retrievedAt': now, 'checkedAt': now,
        'refreshAfter': now + timedelta(hours=source.get('refreshHours', 24)), 'counts': counts,
        'contentSha256': raw_digest, 'parserVersion': parser_version}, upsert=True)
    return {'source': source_id, 'version': digest, 'changed': True, 'counts': counts}


class ComplianceStore:
    def __init__(self, repository):
        self.repository = repository

    def db(self):
        return self.repository.database() if self.repository.settings.tideline_mode == 'mongo' else None

    def retrieve(self, context):
        """One shared retrieval pass; agents never receive arbitrary database access."""
        db = self.db()
        result = {'evidence': [], 'zones': [], 'entities': [], 'rules': [], 'tariffs': [], 'commodities': [],
                  'fees': [], 'prices': [], 'vesselFacts': [], 'versions': {}, 'coverage': {}}
        if db is None:
            return result
        report = context['routeReport']
        now = datetime.now(UTC)
        sources = list(db.compliance_sources.find({}, {'gridFsFileId': 0}))
        current = {s['_id']: s for s in sources if s.get('activeVersion') and utc(s['refreshAfter']) > now}
        active = [{ 'sourceId': s['_id'], 'snapshotId': s['activeVersion']} for s in current.values()]
        result['versions'] = {s['_id']: s['activeVersion'] for s in current.values()}
        result['coverage'] = {s['_id']: {'fresh': s['_id'] in current, 'counts': s.get('counts', {})} for s in sources}
        if not active:
            return result
        base = {'$or': active}
        # One bounded aggregate, rather than a round trip for every source.
        documents = db.compliance_documents.aggregate([{'$match': base}, {'$sort': {'sourceId': 1, '_id': 1}},
            {'$group': {'_id': '$sourceId', 'documents': {'$firstN': {'input': '$$ROOT', 'n': 2}}}},
            {'$unwind': '$documents'}, {'$replaceRoot': {'newRoot': '$documents'}}])
        for doc in documents:
                source = current[doc['sourceId']]
                result['evidence'].append(Evidence(id=doc['_id'], title=source['title'], url=source['url'],
                    supporting_passage=doc['text'], page_or_section=doc.get('pageOrSection'),
                    retrieved_at=doc['retrievedAt'], source_version=doc['snapshotId'], authority='official'
                    if official_url(source['url']) else 'unverified').model_dump(mode='json', by_alias=True)
                    | {'category': source['category']})
        query_text = re.sub(r'[^\w\s-]', ' ', context['cargoText'])[:1000]
        if query_text.strip():
            try:
                rows = db.compliance_documents.aggregate([{'$search': {'index': 'compliance_documents_v1',
                    'compound': {'must': [{'text': {'path': 'text', 'query': query_text}}],
                    'filter': [{'in': {'path': 'snapshotId', 'value': list(result['versions'].values())}}]}}},
                    {'$limit': 12} ], maxTimeMS=1200)
                rows = list(rows)
            except OperationFailure:
                rows = list(db.compliance_documents.find(base | {'$text': {'$search': query_text}}).limit(12))
            seen = {e['id'] for e in result['evidence']}
            for doc in rows:
                if doc['_id'] not in seen and doc['sourceId'] in current:
                    source = current[doc['sourceId']]
                    result['evidence'].append(Evidence(id=doc['_id'], title=source['title'], url=source['url'],
                        supporting_passage=doc['text'], page_or_section=doc.get('pageOrSection'),
                        retrieved_at=doc['retrievedAt'], source_version=doc['snapshotId'], authority='official'
                        if official_url(source['url']) else 'unverified').model_dump(mode='json', by_alias=True)
                        | {'category': source['category']})
        for route in report['routes']:
            for zone in db.maritime_zones.find(base | {'geometry': {'$geoIntersects': {'$geometry': route['geometry']}}}).limit(100):
                result['zones'].append({k: v for k, v in zone.items() if k != '_id'} | {'routeId': route['id']})
        declared = context.get('suppliedVesselInformation') or {}
        imo = declared.get('imoNumber')
        declared_context = report.get('metadata', {}).get('complianceHandoff', {}).get('declaredContext') or {}
        names = [normalize_name(p['name']) for p in declared_context.get('parties', []) if p.get('name')]
        if declared.get('name'):
            names.append(normalize_name(declared['name']))
        matches = ([{'imo': imo}] if imo else []) + ([{'normalizedNames': {'$in': names}}] if names else [])
        if matches:
            result['entities'] = list(db.sanctions_entities.find({'$and': [base, {'$or': matches}]}, {'_id': 0}).limit(40))
            for entity in result['entities']:
                source = current[entity['sourceId']]
                evidence_id = f'{entity["sourceId"]}:{entity["snapshotId"]}:entity:{entity["id"]}'
                entity['evidenceIds'] = [evidence_id]
                entity['matchBasis'] = 'exact_imo' if imo in entity.get('imo', []) else 'name_candidate_requires_identity_review'
                result['evidence'].append(Evidence(id=evidence_id, title=source['title'], url=source['url'],
                    supporting_passage=str({k: v for k, v in entity.items() if k not in ('normalizedNames', 'sourceFields')})[:12000],
                    retrieved_at=entity['retrievedAt'], source_version=entity['snapshotId'], authority='official'
                    if official_url(source['url']) else 'unverified').model_dump(mode='json', by_alias=True) | {'category': 'sanctions'})
        if imo:
            result['vesselFacts'] = list(db.vessel_facts.find(base | {'imo': imo}, {'_id': 0}).limit(10))
        cargo = declared_context.get('cargo') or {}
        codes = list(dict.fromkeys(cargo.get('hsCodes', []) + re.findall(r'\bHS\s*:?\s*(\d{6,10})\b', context['cargoText'], re.IGNORECASE)))
        if codes:
            result['commodities'] = list(db.commodity_codes.find(base | {'code': {'$in': codes}}, {'_id': 0}).limit(30))
        for collection, key in [('compliance_rules', 'rules'), ('tariff_measures', 'tariffs'), ('port_fee_schedules', 'fees'),
                                ('market_observations', 'prices')]:
            rows = db[collection].find(base, {'_id': 0}).limit(300)
            result[key] = [r for r in rows if applicable(r, utc(report['departureTime']))]
        return result

    def route_zones(self, report, data):
        db = self.db()
        if db is None or not data.get('versions'):
            return []
        active = [{'sourceId': key, 'snapshotId': value} for key, value in data['versions'].items()]
        return [{k: v for k, v in zone.items() if k != '_id'} | {'routeId': route['id']}
                for route in report['routes'] for zone in db.maritime_zones.find({'$or': active,
                    'geometry': {'$geoIntersects': {'$geometry': route['geometry']}}}).limit(100)]

    def search_references(self, query, sourceId=None, limit=5):
        """Agent/chat retrieval tool; fixed public collections and current source versions only."""
        if not isinstance(query, str) or not 1 <= len(query) <= 1000 or not isinstance(limit, int) or not 1 <= limit <= 8:
            return []
        db = self.db()
        if db is None:
            return []
        filters = {'refreshAfter': {'$gt': datetime.now(UTC)}}
        if sourceId:
            filters['_id'] = sourceId
        sources = {s['_id']: s for s in db.compliance_sources.find(filters)}
        if not sources:
            return []
        active = {'$or': [{'sourceId': key, 'snapshotId': value['activeVersion']} for key, value in sources.items()]}
        try:
            rows = list(db.compliance_documents.aggregate([{'$search': {'index': 'compliance_documents_v1',
                'compound': {'must': [{'text': {'path': 'text', 'query': query}}],
                'filter': [{'in': {'path': 'snapshotId', 'value': [s['activeVersion'] for s in sources.values()]}}]}}},
                {'$match': active}, {'$limit': limit}], maxTimeMS=1500))
        except OperationFailure:
            rows = list(db.compliance_documents.find(active | {'$text': {'$search': query}}).limit(limit))
        return [Evidence(id=row['_id'], title=sources[row['sourceId']]['title'], url=sources[row['sourceId']]['url'],
            page_or_section=row.get('pageOrSection'), supporting_passage=row['text'], retrieved_at=row['retrievedAt'],
            source_version=row['snapshotId'], authority='official' if official_url(sources[row['sourceId']]['url'])
            else 'unverified').model_dump(mode='json', by_alias=True) for row in rows]

    def status(self):
        db = self.db()
        return {'sources': [] if db is None else list(db.compliance_sources.find({}, {'gridFsFileId': 0})),
                'voyagesStored': False, 'uploadsStored': False}
