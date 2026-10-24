"""Transparent generic-vessel estimates, not an operator quotation."""
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from bisect import bisect_left

from service.canals import catalog
from service.references import active_references


def vessel_model():
    references = active_references()
    return references.vessel if references else _local_vessel_model()


@lru_cache(maxsize=1)
def _local_vessel_model():
    return json.loads((Path(__file__).resolve().parents[1] / 'data/planning/vessel.json').read_text())


def resolve_vessel(parameters=None):
    model = deepcopy(vessel_model())
    supplied = parameters.model_dump(by_alias=True, exclude_none=True) if parameters else {}
    mapping = {'serviceSpeedKnots': 'referenceSpeedKnots',
               'mainFuelTonnesPerDay': 'mainFuelTonnesPerDayAtReferenceSpeed',
               'auxiliaryFuelTonnesPerDay': 'auxiliaryFuelTonnesPerDay',
               'dailyVesselCostUsd': 'dailyVesselCostUsd', 'fuelUsdPerTonne': 'fuelUsdPerTonne'}
    for key, target in mapping.items():
        if key in supplied:
            model[target] = supplied[key]
    if 'fuelUsdPerTonne' in supplied:
        model['fuelPriceReference'] = {'basis': 'user_supplied_unverified', 'usdPerTonne': supplied['fuelUsdPerTonne']}
        model['priceBasis'] = 'user_supplied_fuel_price_other_costs_and_exchange_rates_assumed'
    elif supplied.get('fuelCategory') not in [None, 'residual_hfo']:
        model['fuelPriceReference'] = dict(model['fuelPriceReference'],
            gradeMismatch=True, limitation='VLSFO reference retained; supply the selected fuel grade price for a better estimate')
    if 'serviceSpeedKnots' in supplied:
        model['speedKnots'] = [round(model['referenceSpeedKnots'] * factor, 3) for factor in [.75, .875, 1]]
    if supplied.get('fuelCurve'):
        model['fuelCurve'] = supplied['fuelCurve']
        low = model['fuelCurve'][0]['speedKnots']
        high = supplied.get('serviceSpeedKnots', model['fuelCurve'][-1]['speedKnots'])
        model['referenceSpeedKnots'] = high
        model['mainFuelTonnesPerDayAtReferenceSpeed'] = main_fuel_per_day(high, model)
        model['speedKnots'] = [low, (low + high) / 2, high]
    model['fuelCurveBasis'] = ('user_supplied_piecewise_linear_unverified' if model.get('fuelCurve')
                              else 'single_reference_cubic_rule_of_thumb_not_vessel_calibrated')
    if 'fuelCategory' in supplied:
        factors = {'residual_hfo': (3.114, 'HFO-category residual fuel'),
                   'light_fuel_oil': (3.151, 'Light fuel oil'), 'marine_diesel': (3.206, 'Marine diesel/gas oil')}
        factor, name = factors[supplied['fuelCategory']]
        model['emissions'].update(factorTonnesCo2PerTonneFuel=factor, fuelCategory=name + '; user supplied, unverified')
        model['fuelGrade'] = name + '; fuel switching not modelled'
        model['emissions']['sourceReference'] = 'IMO MEPC.395(82), Annex 7 section 5; selected fuel category'
    model['inputProvenance'] = {'userSupplied': supplied,
                                'defaultedFields': [key for key in [*mapping, 'fuelCategory'] if key not in supplied],
                                'physicalParticularsAndCanalTariffClass': 'generic_defaults_not_actual_vessel_clearance'}
    model['basis'] = 'generic_model_with_unverified_user_parameters' if supplied else model['basis']
    return model


def main_fuel_per_day(speed, model):
    curve = model.get('fuelCurve')
    if curve:
        index = bisect_left([point['speedKnots'] for point in curve], speed)
        if 0 < index < len(curve):
            a, b = curve[index - 1], curve[index]
            fraction = (speed - a['speedKnots']) / (b['speedKnots'] - a['speedKnots'])
            return a['mainFuelTonnesPerDay'] + fraction * (b['mainFuelTonnesPerDay'] - a['mainFuelTonnesPerDay'])
        # Canal speeds may fall below the supplied curve; retain an explicit extrapolation assumption.
        point = curve[0 if index == 0 else -1]
        return point['mainFuelTonnesPerDay'] * (speed / point['speedKnots']) ** 3
    return model['mainFuelTonnesPerDayAtReferenceSpeed'] * (speed / model['referenceSpeedKnots']) ** 3


def fuel_tonnes(hours, propulsion_speed, waiting=False, model=None):
    vessel = model or vessel_model()
    main = 0 if waiting else main_fuel_per_day(propulsion_speed, vessel)
    # Weather affects achievable speed in the simulator; do not charge the
    # same resistance again as an additional fuel multiplier.
    return hours / 24 * (main + vessel['auxiliaryFuelTonnesPerDay'])


def speed_loss(wave_height):
    return min(.35, .025 * max(0, (wave_height or 0) - 1) ** 2)


def fuel_and_time_cost(fuel, hours, model):
    return fuel * model['fuelUsdPerTonne'], hours / 24 * model['dailyVesselCostUsd']


def canal_edge_estimate(edge, model):
    canal = catalog()['canals'][edge['canalId']]
    transit = canal['transitHours'] * edge['canalFraction']
    waiting = canal['waitingHours'] * edge['canalFraction']
    fuel = (fuel_tonnes(transit, edge['distanceNm'] / transit, model=model)
            + fuel_tonnes(waiting, 0, waiting=True, model=model))
    return transit + waiting, fuel


def breakdown(fuel, hours, transits, model=None):
    model = model or vessel_model()
    fuel_cost, time_cost = (round(value, 2) for value in fuel_and_time_cost(fuel, hours, model))
    tolls = round(sum(t.toll_usd for t in transits), 2)
    fees = round(sum(t.service_allowance_usd for t in transits), 2)
    return {'currency': 'USD', 'fuelTonnes': round(fuel, 6), 'fuelUsd': fuel_cost,
            'fuelUsdPerTonne': model['fuelUsdPerTonne'],
            'averageFuelTonnesPerDay': round(fuel * 24 / hours, 6),
            'averageFuelUsdPerDay': round(fuel_cost * 24 / hours, 2),
            'timeUsd': time_cost, 'canalTollsUsd': tolls, 'canalServiceAllowanceUsd': fees,
            'totalUsd': round(fuel_cost + time_cost + tolls + fees, 2),
            'basis': 'generic_vessel_planning_estimate', 'modelId': model['id'],
            'excludedCosts': model['excludedCosts']}


def emissions(fuel, model=None):
    model = (model or vessel_model())['emissions']
    return {'co2Tonnes': round(fuel * model['factorTonnesCo2PerTonneFuel'], 6),
            'factorTonnesCo2PerTonneFuel': model['factorTonnesCo2PerTonneFuel'],
            'fuelCategory': model['fuelCategory'], 'boundary': 'tank_to_wake_CO2',
            'basis': 'estimated_fuel_burn_with_selected_fuel_category_factor_not_measured_emissions',
            'sourceUrl': model['sourceUrl'], 'excludedImpacts': model['excludedImpacts']}
