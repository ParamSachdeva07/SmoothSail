"""Exercise every ordered pair of currently supported ports against the running API."""
import argparse
from datetime import datetime
import itertools
import json
import math
from pathlib import Path
import statistics
import time

import httpx
from shapely import intersects
from shapely.geometry import shape

from service.geo import densify, distance_nm, line_geometry
from service.navigation import default_land_mask
from service.canals import catalog


def validate(result, origin, destination, mask):
    assert result['schemaVersion'] == '1.4.0'
    phases = result['metadata']['phaseSeconds']
    assert phases and all(value >= 0 for value in phases.values())
    assert abs(sum(phases.values()) - result['metadata']['calculationSeconds']) < .1
    grid = result.get('waveGrid')
    if grid:
        assert grid['projection'] == 'mercator' and grid['rowOrder'] == 'north_to_south'
        assert grid['bounds'][0] < grid['bounds'][2] and grid['bounds'][1] < grid['bounds'][3]
        for frame in grid['frames']:
            assert len(frame['values']) == grid['columns'] * grid['rows']
            assert all(v is None or (math.isfinite(v) and v >= 0) for v in frame['values'])
            assert abs((datetime.fromisoformat(frame['validAt']) - datetime.fromisoformat(result['departureTime'])).total_seconds() / 3600 - frame['hour']) < .001
    assert result['origin'] == origin['id'] and result['destination'] == destination['id']
    assert result['routes']
    by_strategy = {route['strategy']: route for route in result['routes']}
    assert {'fastest', 'economical', 'lowest_emissions'} == by_strategy.keys()
    assert by_strategy['fastest']['durationHours'] <= by_strategy['economical']['durationHours'] + .01
    assert by_strategy['economical']['cost']['totalUsd'] <= by_strategy['fastest']['cost']['totalUsd'] + .01
    assert by_strategy['lowest_emissions']['emissions']['co2Tonnes'] <= min(r['emissions']['co2Tonnes'] for r in result['routes'])
    # Wide bounds catch missing global connectivity, not precise voyage targets.
    pair = frozenset([origin['id'], destination['id']])
    distance_limits = {frozenset(['JPTYO', 'USLAX']): (4000, 7000),
                       frozenset(['AUSYD', 'USLAX']): (5000, 9000),
                       frozenset(['NLRTM', 'USNYC']): (2800, 4500),
                       frozenset(['NLRTM', 'SGSIN']): (7500, 9500),
                       frozenset(['USNYC', 'USLAX']): (4000, 6500)}
    if pair in distance_limits:
        lower, upper = distance_limits[pair]
        assert lower <= by_strategy['fastest']['distanceNm'] <= upper, 'Implausible ocean route length'
    if pair in [frozenset(['JPTYO', 'USLAX']), frozenset(['AUSYD', 'USLAX'])]:
        assert by_strategy['fastest']['geometry']['type'] == 'MultiLineString', 'Pacific route must cross dateline'
    for route in result['routes']:
        assert 'relativeFuelUse' not in route
        assert not {'northeast', 'northwest'}.intersection(route['passageIds']), 'Unsupported Arctic passage'
        for segment in route['segments']:
            geom = shape(segment['geometry'])
            if segment['kind'] in ['canal_wait', 'canal_transit']:
                ref = segment['networkReference']
                reviewed = [e for c in catalog()['canals'].values()
                            for key, e in c['reviewedEdges'].items() if key == ref['sourceEdgeId']]
                assert len(reviewed) == 1, 'Unreviewed canal exemption'
                corridor = shape(line_geometry(densify(reviewed[0]['coordinates'], max_nm=1))).buffer(.00001)
                assert corridor.covers(geom), 'Canal segment left its pinned source geometry'
            else:
                assert not intersects(mask.polygons[mask.tree.query(geom)], geom).any(), 'Route intersects mapped land'
        parts = ([route['geometry']['coordinates']] if route['geometry']['type'] == 'LineString'
                 else route['geometry']['coordinates'])
        assert distance_nm(parts[0][0], origin['coordinates']) < .001, 'Wrong departure point'
        assert distance_nm(parts[-1][-1], destination['coordinates']) < .001, 'Wrong destination point'
        assert all(abs(a[0] - b[0]) <= 180 for part in parts for a, b in zip(part, part[1:])), 'Dateline world-spanning line'
        assert all(-180 <= p[0] <= 180 and -90 <= p[1] <= 90 for part in parts for p in part)
        segments = route['segments']
        assert segments[0]['entryTime'] == result['departureTime']
        assert segments[-1]['exitTime'] == route['eta']
        assert all(a['exitTime'] == b['entryTime'] for a, b in zip(segments, segments[1:]))
        assert all(datetime.fromisoformat(s['exitTime']) > datetime.fromisoformat(s['entryTime']) for s in segments)
        assert all(datetime.fromisoformat(s['entryTime']) <= datetime.fromisoformat(s['sampleTime']) <= datetime.fromisoformat(s['exitTime']) for s in segments)
        hours = (datetime.fromisoformat(route['eta']) - datetime.fromisoformat(result['departureTime'])).total_seconds() / 3600
        assert abs(hours - route['durationHours']) < .011
        assert abs(sum(s['distanceNm'] for s in segments) - route['distanceNm']) < .1 + len(segments) * .0005
        assert 0 <= route['forecastCoveragePercent'] <= 100
        cost = route['cost']
        assert abs(cost['totalUsd'] - sum(cost[k] for k in ['fuelUsd', 'timeUsd', 'canalTollsUsd', 'canalServiceAllowanceUsd'])) < .011
        assert abs(sum(s['fuelTonnes'] for s in segments) - cost['fuelTonnes']) < .0001
        assert len(route['canalTransits']) == len([s for s in segments if s['kind'] == 'canal_wait'])
        assert abs(route['sailingHours'] + route['canalHours'] + route['waitingHours'] - hours) < .001
        if route['forecastCoveragePercent'] < 99.99:
            assert route['exposureScore'] is None, 'Missing conditions were scored as known'
        emissions = route['emissions']
        assert abs(emissions['co2Tonnes'] - cost['fuelTonnes'] * emissions['factorTonnesCo2PerTonneFuel']) < .00001
    return {'routes': len(result['routes']), 'distanceNm': by_strategy['fastest']['distanceNm'],
            'segments': len(by_strategy['fastest']['segments']),
            'crossesDateline': by_strategy['fastest']['geometry']['type'] == 'MultiLineString'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--report', type=Path, default=Path('reports/route-matrix.json'))
    args = parser.parse_args()
    mask = default_land_mask()
    report = {'passed': [], 'failed': []}
    with httpx.Client(base_url=args.base_url, timeout=150) as client:
        health = client.get('/health')
        health.raise_for_status()
        report['health'] = health.json()
        response = client.get('/ports', params={'limit': 50})
        response.raise_for_status()
        ports = response.json()['ports']
        report['ports'] = [p['id'] for p in ports]
        pairs = list(itertools.permutations(ports, 2))
        for index, (origin, destination) in enumerate(pairs, 1):
            start = time.monotonic()
            item = {'origin': origin['id'], 'destination': destination['id']}
            try:
                response = client.post('/routes', json={'origin': origin['id'], 'destination': destination['id']})
                assert response.status_code == 200, f'HTTP {response.status_code}'
                assert 'voyageSimulation;dur=' in response.headers.get('server-timing', '')
                item.update(validate(response.json(), origin, destination, mask))
                item['seconds'] = round(time.monotonic() - start, 3)
                report['passed'].append(item)
            except (AssertionError, ValueError, KeyError, httpx.HTTPError) as error:
                item['error'] = str(error) or type(error).__name__
                report['failed'].append(item)
                print('FAIL', json.dumps(item), flush=True)
            if index % 10 == 0 or index == len(pairs):
                print(f'{index}/{len(pairs)} pairs checked; {len(report["failed"])} failures.', flush=True)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + '\n')
    timings = [item['seconds'] for item in report['passed']]
    report['summary'] = {'passed': len(report['passed']), 'failed': len(report['failed']),
                         'medianSeconds': round(statistics.median(timings), 3) if timings else None,
                         'maxSeconds': max(timings, default=None)}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary']), flush=True)
    return bool(report['failed'])


if __name__ == '__main__':
    raise SystemExit(main())
