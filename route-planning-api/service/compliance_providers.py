"""Focused public APIs. Public responses are cached; cargo text is never cached."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
from pymongo.errors import PyMongoError

from service.compliance_models import Evidence


async def uk_tariff_lookup(code, db=None, transport=None):
    if not isinstance(code, str) or len(code) != 10 or not code.isdigit():
        return None
    url = f'https://www.trade-tariff.service.gov.uk/api/v2/commodities/{code}'
    key = f'uk-tariff:{code}'
    now = datetime.now(UTC)
    if db is not None:
        cached = await asyncio.to_thread(db.api_cache.find_one, {'_id': key, 'expiresAt': {'$gt': now}})
        if cached:
            return cached['value']
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as client:
            response = await client.get(url, headers={'Accept': 'application/vnd.hmrc.2.0+json'})
            response.raise_for_status()
            data = response.json()
        commodity = data.get('data', {}).get('attributes', {})
        if str(commodity.get('goods_nomenclature_item_id')) != code:
            return None
        # Keep measure conditions and references; don't turn one duty expression into a guessed rate.
        included = [item for item in data.get('included', []) if item.get('type') in (
            'measure', 'duty_expression', 'measure_type', 'measure_condition', 'legal_act', 'geographical_area')]
        text = json.dumps({'commodity': commodity, 'measures': included}, ensure_ascii=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        value = {'code': code, 'commodity': commodity, 'measureCount': len(included),
            'evidence': Evidence(id=f'api:uk-tariff:{code}:{digest[:12]}',
                title=f'UK Trade Tariff commodity {code}', url=url, supporting_passage=text[:16000],
                retrieved_at=now, source_version=digest, authority='official').model_dump(mode='json', by_alias=True),
            'interpretation': 'Current published measures; origin/preferences/quotas/conditions and arrival-date validity need checking. No payable amount inferred.'}
        if db is not None:
            await asyncio.to_thread(db.api_cache.replace_one, {'_id': key},
                {'_id': key, 'expiresAt': now + timedelta(hours=6), 'value': value}, upsert=True)
        return value
    except (httpx.HTTPError, ValueError, PyMongoError):
        return None


async def fetch_voyage_apis(body, store):
    cargo = body.route_request.compliance_context.cargo if body.route_request.compliance_context else None
    # Codes may be supplied through the API; no automatic tariff classification from vague cargo text.
    if not body.route_request.destination.startswith('GB') or not cargo or not cargo.hs_codes:
        return []
    db = store.db()
    results = await asyncio.gather(*(uk_tariff_lookup(code, db) for code in cargo.hs_codes[:3]))
    return [result for result in results if result]
