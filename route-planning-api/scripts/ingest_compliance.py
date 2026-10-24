"""Import public references into versioned Atlas snapshots. Dry-run unless --publish."""
import argparse
import asyncio
import csv
import json
import re
import unicodedata
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import httpx
from defusedxml import ElementTree
from pymongo.errors import PyMongoError
from pypdf.errors import PyPdfError
from shapely.geometry import shape

from service.compliance_data import (
    SOURCES,
    ensure_compliance_indexes,
    fetch_official,
    public_text,
    publish_snapshot,
    utc,
)
from service.config import Settings, settings
from service.data import connect


def normalized_name(value):
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()).strip()


def parse_uk_sanctions(raw):
    text = raw.decode('utf-8-sig')
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines[:15]) if 'Unique ID' in line and 'Name 1' in line), None)
    if header is None:
        raise ValueError('UKSL header not recognized; source was not published.')
    groups = {}
    for row in csv.DictReader(StringIO('\n'.join(lines[header:]))):
        key = row.get('Unique ID', '').strip()
        if not key:
            continue
        name = ' '.join(row.get(f'Name {i}', '').strip() for i in range(1, 7)).strip()
        record = groups.setdefault(key, {'id': key, 'names': [], 'normalizedNames': [], 'imo': [],
            'jurisdiction': 'UK', 'measures': row.get('Sanctions Imposed', ''), 'regime': row.get('Regime Name', ''),
            'entityType': row.get('Type of entity', row.get('Individual, Entity, Ship', '')), 'sourceFields': {k: v for k, v in row.items()
                if k in ('IMO number', 'Current owner/operator', 'Current believed flag of ship', 'UK Statement of Reasons')}})
        if name and name not in record['names']:
            record['names'].append(name)
            record['normalizedNames'].append(normalized_name(name))
        for field, value in row.items():
            if field and 'imo' in field.lower():
                record['imo'].extend(re.findall(r'(?<!\d)\d{7}(?!\d)', value or ''))
        record['imo'] = sorted(set(record['imo']))
    if not groups:
        raise ValueError('Empty UK sanctions list.')
    return {'sanctions_entities': list(groups.values())}


def parse_ofac(raw):
    header = raw[:12000].decode(errors='ignore').lower()
    if ('historical' in header or 'historic dataset' in header) and ('removed' in header or 'not be used' in header):
        raise ValueError('Historical/removed OFAC export cannot be published as active screening data.')
    root = ElementTree.fromstring(raw)
    rows = []
    def tag(element):
        return element.tag.rsplit('}', 1)[-1]
    def value(element, name):
        return next((c.text or '' for c in element if tag(c) == name), '')
    for entry in root.iter():
        if tag(entry) != 'sdnEntry':
            continue
        name = ' '.join(filter(None, [value(entry, 'firstName'), value(entry, 'lastName')]))
        names, imo = [name] if name else [], []
        for child in entry.iter():
            if tag(child) == 'aka':
                names.append(' '.join(filter(None, [value(child, 'firstName'), value(child, 'lastName')])))
            if tag(child) == 'id' and ('imo' in value(child, 'idType').lower()
                    or re.search(r'\bIMO[\s:-]*\d{7}', value(child, 'idNumber'), re.IGNORECASE)):
                imo.extend(re.findall(r'(?<!\d)\d{7}(?!\d)', value(child, 'idNumber')))
        rows.append({'id': value(entry, 'uid'), 'names': list(dict.fromkeys(names)),
            'normalizedNames': list({normalized_name(n) for n in names if n}), 'imo': sorted(set(imo)),
            'entityType': value(entry, 'sdnType'), 'jurisdiction': 'US',
            'programs': [c.text for c in entry.iter() if tag(c) == 'program'], 'remarks': value(entry, 'remarks')})
    if not rows:
        raise ValueError('Expected current OFAC SDN XML schema; no records were imported.')
    return {'sanctions_entities': rows}


def parse_records(kind, raw, reviewed=False):
    if kind == 'uk_sanctions':
        return parse_uk_sanctions(raw)
    if kind == 'ofac_sdn':
        return parse_ofac(raw)
    if kind == 'hs':
        data = json.loads(raw)
        rows = data.get('results', data) if isinstance(data, dict) else data
        return {'commodity_codes': [{'code': str(row['id']), 'description': row.get('text', row.get('text', '')),
                                     'edition': 'HS2022'} for row in rows if row.get('id') and str(row['id']).isdigit()]}
    if kind in ('zones', 'rules', 'tariffs', 'fees', 'vessel_facts', 'port_baselines', 'prices'):
        value = json.loads(raw)
        rows = value['features'] if isinstance(value, dict) and 'features' in value else value
        if not isinstance(rows, list) or not rows:
            raise ValueError('Expected a non-empty JSON array or GeoJSON FeatureCollection.')
        collection = {'zones': 'maritime_zones', 'rules': 'compliance_rules', 'tariffs': 'tariff_measures',
                      'fees': 'port_fee_schedules', 'vessel_facts': 'vessel_facts', 'port_baselines': 'port_baselines',
                      'prices': 'market_observations'}[kind]
        records = []
        for index, row in enumerate(rows):
            item = (row.get('properties', {}) | {'geometry': row['geometry']}) if kind == 'zones' and row.get('type') == 'Feature' else row.copy()
            item['id'] = str(item.get('id', index))
            item['reviewed'] = reviewed
            if kind == 'zones':
                geometry = shape(item['geometry'])
                bounds = geometry.bounds
                if (geometry.geom_type not in ('Polygon', 'MultiPolygon') or not geometry.is_valid
                        or bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90):
                    raise ValueError('Zone polygons must be valid; nothing was published.')
                if not item.get('name') or item.get('category') not in ('jwc', 'ibf', 'eca'):
                    raise ValueError('Every zone needs a name and jwc/ibf/eca category.')
            records.append(item)
        return {collection: records}
    if kind == 'eu_sanctions':
        text = raw.decode('utf-8-sig')
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=';,\t')
        grouped = {}
        for row in csv.DictReader(StringIO(text), dialect=dialect):
            def pick(ending, row=row):
                return next((v for k, v in row.items() if k and k.lower().endswith(ending.lower())), '')
            key = pick('logicalId') or pick('euReferenceNumber')
            if not key:
                continue
            record = grouped.setdefault(key, {'id': key, 'names': [], 'normalizedNames': [], 'imo': [], 'jurisdiction': 'EU'})
            name = pick('nameAlias.wholeName') or pick('wholeName')
            if name and name not in record['names']:
                record['names'].append(name); record['normalizedNames'].append(normalized_name(name))
        if not grouped:
            raise ValueError('EU sanctions schema not recognized; use one official CSV schema per source.')
        return {'sanctions_entities': list(grouped.values())}
    return {}


async def refresh_sources(db, selected=None):
    results = []
    for source_id, category, title, url in SOURCES:
        if selected and source_id not in selected:
            continue
        previous = db.compliance_sources.find_one({'_id': source_id})
        if previous and utc(previous['refreshAfter']) > datetime.now(UTC):
            results.append({'source': source_id, 'status': 'fresh'}); continue
        try:
            final_url, raw, pages = await fetch_official(url)
            results.append(publish_snapshot(db, {'id': source_id, 'category': category, 'title': title,
                'url': final_url, 'refreshHours': 24 if category in ('security', 'sanctions') else 168}, raw, pages))
        except (httpx.HTTPError, ValueError, PyMongoError, PyPdfError) as error:
            results.append({'source': source_id, 'status': 'unavailable', 'reason': type(error).__name__})
    return results


async def refresh_structured(db):
    feeds = [
        ('uksl_data', 'uk_sanctions', 'sanctions', 'UK Sanctions List current CSV',
         'https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv'),
        ('ofac_sdn', 'ofac_sdn', 'sanctions', 'OFAC current SDN list', 'https://www.treasury.gov/ofac/downloads/sdn.xml'),
        ('hs2022', 'hs', 'trade', 'UN HS2022 commodity classification', 'https://comtradeapi.un.org/files/v1/app/reference/H6.json'),
    ]
    results = []
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        for source_id, kind, category, title, url in feeds:
            parser_version = '2' if kind in ('uk_sanctions', 'ofac_sdn') else '1'
            previous = db.compliance_sources.find_one({'_id': source_id})
            if (previous and utc(previous['refreshAfter']) > datetime.now(UTC)
                    and previous.get('parserVersion', '1') == parser_version):
                results.append({'source': source_id, 'status': 'fresh'}); continue
            try:
                # Fixed publisher URLs, never a caller-controlled download/proxy.
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > 128 * 1024 * 1024:
                    raise ValueError('Feed exceeds 128 MiB.')
                records = parse_records(kind, response.content)
                results.append(publish_snapshot(db, {'id': source_id, 'title': title, 'url': url,
                    'category': category, 'refreshHours': 6 if category == 'sanctions' else 720,
                    'parserVersion': parser_version},
                    response.content, records=records))
            except (httpx.HTTPError, ValueError, PyMongoError) as error:
                results.append({'source': source_id, 'status': 'unavailable', 'reason': type(error).__name__})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Fetch the registered official public reference pages.')
    parser.add_argument('--env-file', type=Path, help='Explicit backend environment file; values are never printed.')
    parser.add_argument('--structured', action='store_true', help='Also refresh current UK/OFAC feeds and HS2022.')
    parser.add_argument('--source', help='Source identifier; comma-separated filter with --refresh.')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--title')
    parser.add_argument('--category', choices=['security', 'environment', 'trade', 'sanctions', 'dangerous_goods', 'congestion'])
    parser.add_argument('--kind', default='document', choices=['document', 'hs', 'uk_sanctions', 'ofac_sdn',
        'eu_sanctions', 'zones', 'rules', 'tariffs', 'fees', 'vessel_facts', 'port_baselines', 'prices'])
    parser.add_argument('--reviewed', action='store_true', help='Activate reviewed structured rules/geometry.')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--atlas-search', action='store_true')
    args = parser.parse_args()
    config = Settings(_env_file=args.env_file) if args.env_file else settings
    if args.refresh:
        if not args.publish:
            print(json.dumps({'dryRun': True, 'sources': [s[0] for s in SOURCES]})); return
        client, db = connect(config)
        try:
            ensure_compliance_indexes(db, args.atlas_search)
            print(json.dumps(asyncio.run(refresh_sources(db, args.source.split(',') if args.source else None))))
            if args.structured:
                print(json.dumps(asyncio.run(refresh_structured(db))))
        finally:
            client.close()
        return
    if not all([args.file, args.source, args.url, args.category]):
        parser.error('Use --refresh or --file, --source, --url and --category.')
    raw = args.file.read_bytes()
    records = parse_records(args.kind, raw, args.reviewed)
    pages = public_text(raw, 'application/pdf' if args.file.suffix == '.pdf' else 'text/plain') if args.kind == 'document' else []
    if not args.publish:
        print(json.dumps({'dryRun': True, 'counts': {k: len(v) for k, v in records.items()}, 'pages': len(pages)})); return
    client, db = connect(config)
    try:
        ensure_compliance_indexes(db, args.atlas_search)
        print(json.dumps(publish_snapshot(db, {'id': args.source, 'category': args.category,
            'title': args.title or args.file.name, 'url': args.url, 'refreshHours': 24,
            **({'reviewed': args.reviewed} if args.kind in ('zones', 'rules', 'tariffs', 'fees', 'prices') else {})},
            raw, pages, records)))
    finally:
        client.close()


if __name__ == '__main__':
    main()
