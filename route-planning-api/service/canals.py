"""Narrow, source-pinned canal permissions and explicit planning charges."""
import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from service.references import active_references

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    references = active_references()
    return references.canals if references else _local_catalog()


@lru_cache(maxsize=1)
def _local_catalog():
    return json.loads((ROOT / 'data/planning/canals.json').read_text())


def coordinate_hash(coordinates):
    forward = json.dumps(coordinates, separators=(',', ':'))
    reverse = json.dumps(list(reversed(coordinates)), separators=(',', ':'))
    return hashlib.sha256(min(forward, reverse).encode()).hexdigest()


def canal_for_edge(edge):
    for canal_id, canal in catalog()['canals'].items():
        expected = canal['reviewedEdges'].get(edge.get('sourceEdgeId'))
        if expected and coordinate_hash(edge['coordinates']) == expected['coordinatesSha256']:
            return canal_id
    return None


def is_reviewed_canal_edge(edge):
    return canal_for_edge(edge) is not None


def decorate_graph(graph):
    """Mark only known geometry. A passage label by itself never bypasses land."""
    for _, _, edge in graph.edges(data=True):
        cid = canal_for_edge(edge)
        if cid:
            canal = catalog()['canals'][cid]
            edge['canalId'] = cid
            edge['passageIds'] = sorted(set(edge.get('passageIds', [])) | {cid})
            edge['canalFraction'] = edge['distanceNm'] / canal['networkDistanceNm']


def toll(canal_id, vessel, when=None):
    canal = catalog()['canals'][canal_id]
    tariff = canal['tariff']
    if canal_id == 'panama':
        items = [
            {'label': 'Super vessel fixed toll', 'amountUsd': tariff['fixedUsd']},
            {'label': 'TEU capacity', 'amountUsd': vessel['capacityTeu'] * tariff['capacityUsdPerTeu']},
            {'label': 'Loaded TEU', 'amountUsd': vessel['loadedTeu'] * tariff['loadedUsdPerTeu']},
            {'label': 'Empty TEU', 'amountUsd': vessel['emptyTeu'] * tariff['emptyUsdPerTeu']},
        ]
    else:
        remaining, sdr = vessel['suezNetTonnage'], 0.0
        for band in tariff['ladenSdrBands']:
            units = min(remaining, band['tonnage']) if band['tonnage'] else remaining
            sdr += units * band['rate']
            remaining -= units
            if remaining <= 0:
                break
        items = [{'label': 'Suez laden container base toll, assumed SDR/USD conversion',
                  'amountUsd': round(sdr * vessel['usdPerSdr'], 2)}]
        if (when or datetime.now(UTC)).date().isoformat() >= tariff['surchargeEffectiveFrom']:
            items.append({'label': 'Circular 2/2026 surcharge on included base dues (deck-tier dues excluded)',
                          'amountUsd': round(items[0]['amountUsd'] * tariff['surchargeRate'], 2),
                          'sourceUrl': tariff['surchargeSourceUrl']})
    return {'amountUsd': round(sum(i['amountUsd'] for i in items), 2), 'items': items,
            'basis': 'published_base_tariff_with_generic_vessel_assumptions',
            'sourceUrl': tariff['sourceUrl'], 'sourceRetrievedAt': catalog()['retrievedAt'],
            'effectiveFrom': tariff['effectiveFrom'], 'excludedAdjustments': tariff['excludedAdjustments']}
