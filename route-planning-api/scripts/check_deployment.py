"""Exercise a deployed API with Atlas data and browser-style CORS requests."""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time

import httpx

from service.models import RouteResponse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--output', default='reports/cloudflare-live-checks.json')
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit = {'baseUrl': args.base_url, 'checkedAt': datetime.now(UTC).isoformat(), 'checks': []}

    def save():
        output.write_text(json.dumps(audit, indent=2) + '\n')

    with httpx.Client(base_url=args.base_url.rstrip('/'), timeout=190) as client:
        def check(name, method, path, expected=200, **kwargs):
            started = time.monotonic()
            response = client.request(method, path, **kwargs)
            item = {'check': name, 'status': response.status_code,
                    'seconds': round(time.monotonic() - started, 2),
                    'allowOrigin': response.headers.get('access-control-allow-origin')}
            audit['checks'].append(item)
            save()
            print(json.dumps(item), flush=True)
            assert response.status_code == expected, f'{name}: expected {expected}, received {response.status_code}'
            assert item['allowOrigin'] == '*', f'{name}: missing public CORS header'
            assert 'access-control-allow-credentials' not in response.headers
            return response, item

        origins = ['http://localhost:3000', 'https://frontend.example']
        for origin in origins:
            response, _ = check('preflight ' + origin, 'OPTIONS', '/routes', expected=204, headers={
                'Origin': origin, 'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'Content-Type'})
            assert 'POST' in response.headers['access-control-allow-methods']

        response, item = check('health', 'GET', '/health')
        item['health'] = response.json()
        save()
        for index, (origin, destination) in enumerate([
            ('DEHAM', 'FRLEH'), ('NLRTM', 'SGSIN'), ('USNYC', 'USLAX'),
        ]):
            response, item = check(f'{origin}-{destination}', 'POST', '/routes',
                                   headers={'Origin': origins[index % len(origins)]},
                                   json={'origin': origin, 'destination': destination})
            report = RouteResponse.model_validate(response.json())
            assert report.mode == 'mongo'
            assert {route.strategy for route in report.routes} == {'fastest', 'economical', 'lowest_emissions'}
            assert report.metadata.data_provenance
            assert response.headers.get('server-timing')
            assert 'Server-Timing' in response.headers['access-control-expose-headers']
            item['calculationSeconds'] = report.metadata.calculation_seconds
            item['serverTiming'] = response.headers['server-timing']
            item['routes'] = []
            for route in report.routes:
                assert route.distance_nm > 0 and route.duration_hours > 0 and route.cost.total_usd > 0
                assert route.geometry['type'] in {'LineString', 'MultiLineString'}
                assert route.segments and route.metadata and route.metadata.geometry_sha256
                assert route.compliance_status == 'not_assessed'
                item['routes'].append({
                    'strategy': route.strategy, 'distanceNm': route.distance_nm,
                    'durationHours': route.duration_hours, 'costUsd': route.cost.total_usd,
                    'co2Tonnes': route.emissions.co2_tonnes,
                    'canals': [canal.canal_id for canal in route.canal_transits],
                    'forecastCoveragePercent': route.forecast_coverage_percent,
                })
            save()
        for path in ['/ports?q=Roterdam', '/api/ports/nearby?longitude=3.7&latitude=51.95',
                     '/data-status', '/route-schema', '/docs']:
            response, item = check(path, 'GET', path, headers={'Origin': origins[1]})
            if path == '/data-status':
                item['dataStatus'] = response.json()
            elif path.startswith('/ports') or path.startswith('/api/ports'):
                assert response.json()['ports']
            save()
        for path in ['/internal/refresh', '/api/internal/refresh']:
            check(path, 'POST', path, expected=404)
        check('invalid_route', 'POST', '/routes', expected=422,
              headers={'Origin': origins[0]}, json={'origin': 'BAD', 'destination': 'SGSIN'})
    audit['passed'] = True
    save()
    print(f'Passed. Report: {output}', flush=True)


if __name__ == '__main__':
    main()
