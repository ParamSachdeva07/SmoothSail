"""Calculations stay in Python; language models cannot invent payable amounts."""
import math
from datetime import UTC, datetime

from shapely.geometry import shape

from service.compliance_data import applicable, utc
from service.geo import GEOD


def calculate_compliance(context, data):
    report = context['routeReport']
    encounters, costs = [], {}
    for zone in data.get('zones', []):
        if not zone.get('reviewed'):
            continue
        polygon = shape(zone['geometry'])
        for route in report['routes']:
            if route['id'] != zone['routeId']:
                continue
            for index, segment in enumerate(route['segments']):
                if not applicable(zone, utc(segment['entryTime'])):
                    continue
                line = shape(segment['geometry'])
                inside = line.intersection(polygon)
                metres = abs(GEOD.geometry_length(line))
                covered = abs(GEOD.geometry_length(inside)) if not inside.is_empty else 0
                if metres < 0.01 or covered < 0.01:
                    continue
                fraction = min(1, covered / metres)
                hours = (utc(segment['exitTime']) - utc(segment['entryTime'])).total_seconds() / 3600 * fraction
                encounters.append({'routeId': route['id'], 'zoneId': zone['id'], 'name': zone['name'],
                    'category': zone['category'], 'segmentIndex': index, 'distanceNm': covered / 1852,
                    'hours': hours, 'fuelTonnes': segment.get('fuelTonnes', 0) * fraction,
                    'segmentEntryTime': segment['entryTime'], 'segmentExitTime': segment['exitTime'],
                    'timeBasis': 'Distance-proportional time/fuel within a timed segment; not exact crossing instants.',
                    'evidenceIds': zone.get('evidenceIds', [])})
    declared = report.get('metadata', {}).get('complianceHandoff', {}).get('declaredContext') or {}
    cargo = declared.get('cargo') or {}
    vessel = declared.get('vessel') or {}
    destination = report['destination']
    for fee in data.get('fees', []):
        if not fee.get('reviewed') or fee.get('portId') not in (report['origin'], destination):
            continue
        rate = fee.get('rate')
        if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
            continue
        basis = fee.get('feeBasis')
        units = vessel.get('grossTonnage') if basis == 'per_gt' else cargo.get('quantity') if (
            basis == 'per_container' and cargo.get('quantityUnit') == 'containers') else 1 if basis == 'fixed' else None
        if units is None or not isinstance(units, (int, float)) or not math.isfinite(units) or units < 0:
            continue
        for route in report['routes']:
            when = utc(report['departureTime'] if fee['portId'] == report['origin'] else route['eta'])
            if not applicable(fee, when):
                continue
            key = f'port-fee:{fee["id"]}:{route["id"]}'
            costs[key] = {'amount': round(rate * units, 2), 'currency': fee['currency'], 'basis': 'port_call',
                'calculationId': key, 'routeIds': [route['id']], 'portIds': [fee['portId']],
                'evidenceIds': fee.get('evidenceIds', []), 'assumptions': [
                    f'{units} × published {basis} rate {rate}; user-declared particulars.',
                    'Only this fee is included. Terminal handling, pilotage/tugs, rebates and other fees need separate schedules.']}
    for measure in data.get('tariffs', []):
        # Only reviewed, explicit ad-valorem scenarios; complex duties need their own adapter.
        if not measure.get('reviewed') or measure.get('rateType') != 'ad_valorem':
            continue
        if (measure.get('destinationPortId') != destination or measure.get('hsCode') not in cargo.get('hsCodes', [])
                or measure.get('originCountryCode') != cargo.get('originCountryCode')
                or measure.get('currency') != cargo.get('currency') or cargo.get('customsValue') is None):
            continue
        # Duty is assessed at the arrival date, not the date the user presses Calculate.
        for route in report['routes']:
            if not applicable(measure, utc(route['eta'])):
                continue
            rate = measure.get('ratePercent')
            if not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0 <= rate <= 1000:
                continue
            key = f'tariff:{measure["id"]}:{route["id"]}'
            costs[key] = {'amount': round(cargo['customsValue'] * rate / 100, 2), 'currency': cargo['currency'],
                'basis': 'cargo_shipment', 'calculationId': key, 'assumptions': [
                    f'{rate}% × declared customs value. Origin/classification/value are user declarations.',
                    'Only this measure is included; preferences, other duties, VAT and excise may require further data.'],
                'routeIds': [route['id']], 'evidenceIds': measure.get('evidenceIds', [])}
    for rule in data.get('rules', []):
        if rule.get('type') != 'ets_co2_scenario' or not rule.get('reviewed'):
            continue
        eligible = set(rule.get('eligiblePortIds', []))
        share = 1 if report['origin'] in eligible and destination in eligible else 0.5 if (
            report['origin'] in eligible or destination in eligible) else 0
        market = next((p for p in data.get('prices', []) if p.get('reviewed') and p.get('instrument') == 'EUA'
                       and p.get('currency') == 'EUR'), {})
        price = rule.get('allowancePriceEUR', market.get('value'))
        phase_in = rule.get('phaseIn', 1)
        observed = utc(rule.get('priceObservedAt', market.get('observedAt')))
        if not share or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0 or not observed:
            continue
        if not isinstance(phase_in, (int, float)) or not math.isfinite(phase_in) or not 0 <= phase_in <= 1:
            continue
        if not 0 <= (datetime.now(UTC) - observed).total_seconds() <= 7 * 86400:
            continue
        for route in report['routes']:
            if not applicable(rule, utc(report['departureTime'])):
                continue
            co2 = route.get('emissions', {}).get('co2Tonnes')
            if not isinstance(co2, (int, float)) or not math.isfinite(co2) or co2 < 0:
                continue
            key = f'ets:{rule["id"]}:{route["id"]}'
            costs[key] = {'amount': round(co2 * share * price * phase_in, 2), 'currency': 'EUR',
                'basis': 'vessel_voyage', 'calculationId': key, 'assumptions': [
                    f'CO₂-only scenario: {co2:.3f} t × {share} scope × €{price}/EUA.',
                    'Assumes vessel eligibility and no applicable derogation; not verified vessel liability.',
                    'CH₄/N₂O, port emissions outside the report and other compliance schemes excluded.',
                    f'Allowance observation: {observed.isoformat()}.'],
                'routeIds': [route['id']], 'evidenceIds': rule.get('evidenceIds', [])}
    return {'zoneEncounters': encounters, 'costs': costs,
            'existingVoyageCosts': 'Fuel, vessel time and canal amounts already in routeReport; never add them twice.',
            'unsupportedCosts': ['Insurance premium without quote/rate and insured value',
                'Actual annual FuelEU liability or CII grade from one voyage',
                'Demurrage/detention without free time, tariff and container events']}
