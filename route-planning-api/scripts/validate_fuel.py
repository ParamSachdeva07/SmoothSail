"""Compare the generic curve with external evidence without claiming calibration."""
import json
from pathlib import Path

from service.costs import fuel_tonnes, main_fuel_per_day, resolve_vessel, vessel_model
from service.models import VesselParameters


def compare_points(reference, model):
    rows = []
    for speed, consumption in reference['points']:
        estimate = fuel_tonnes(24, speed, model=model) - model['auxiliaryFuelTonnesPerDay']
        rows.append({'speedKnots': speed, 'genericMainFuelTonnesPerDay': round(estimate, 3),
                     'publishedMainFuelTonnesPerDay': consumption,
                     'differencePercent': round((estimate / consumption - 1) * 100, 2)})
    return rows


def interpolation_checks(reference):
    """Hold out interior published points; do not call this voyage validation."""
    points = reference['points']
    rows = []
    for index in range(1, len(points) - 1):
        speed, published = points[index]
        model = resolve_vessel(VesselParameters(fuel_curve=[
            {'speedKnots': s, 'mainFuelTonnesPerDay': f}
            for i, (s, f) in enumerate(points) if i != index]))
        estimated = main_fuel_per_day(speed, model)
        rows.append({'heldOutSpeedKnots': speed, 'publishedMainFuelTonnesPerDay': published,
                     'interpolatedMainFuelTonnesPerDay': round(estimated, 3),
                     'differencePercent': round((estimated / published - 1) * 100, 2)})
    return {'sourceUrl': reference['sourceUrl'], 'checks': rows,
            'interpretation': 'Interpolation between supplied specification points only; not measured voyage validation, a fleet error bound, or a test of weather response.'}


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = json.loads((root / 'data/validation/fuel-benchmarks.json').read_text())
    model = vessel_model()
    rows = compare_points(evidence['consumption'], model)
    price = evidence['price']['usdPerTonne']
    report = {'evidence': evidence, 'modelId': model['id'], 'comparisons': rows,
              'additionalComparisons': [{'sourceUrl': reference['sourceUrl'],
                                         'conditions': reference['conditions'],
                                         'limitations': reference['limitations'],
                                         'comparisons': compare_points(reference, model)}
                                        for reference in evidence.get('additionalConsumptionReferences', [])],
              'empiricalVoyageAccuracyValidated': False, 'statisticalErrorBoundPercent': None,
              'suppliedCurveInterpolationChecks': [interpolation_checks(reference) for reference in
                  [evidence['consumption'], *evidence.get('additionalConsumptionReferences', [])]],
              'speedRuleCheck': {
                  'sourceUrl': 'https://greenvoyage2050.imo.org/technology/speed-management/',
                  'speedReductionPercent': 10,
                  'propulsionFuelPerDayReductionPercent': round((1 - .9 ** 3) * 100, 1),
                  'fixedDistancePropulsionFuelReductionPercent': round((1 - .9 ** 2) * 100, 1),
                  'scope': 'IMO cubic rule of thumb, propulsion only; auxiliary fuel and added voyage time are accounted for separately in the service.'},
              'priceCheck': {'previousAssumptionUsdPerTonne': 650, 'currentDefaultUsdPerTonne': model['fuelUsdPerTonne'],
                             'datedReferenceUsdPerTonne': price, 'increaseFromPreviousPercent': round((price / 650 - 1) * 100, 2)},
              'unitCheck': {'at16KnotsTonnesPerDayIncludingAuxiliary': fuel_tonnes(24, 16),
                            'at16KnotsFuelUsdPerDay': fuel_tonnes(24, 16) * model['fuelUsdPerTonne'],
                            'tenDaysAt16KnotsFuelUsd': fuel_tonnes(240, 16) * model['fuelUsdPerTonne'],
                            'conditions': 'constant 16 kn, no waves/currents/canals; fuel cost only'},
              'interpretation': evidence['conclusion']}
    target = root / 'reports/fuel-validation.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['comparisons', 'priceCheck', 'unitCheck', 'interpretation']}, indent=2))


if __name__ == '__main__':
    main()
