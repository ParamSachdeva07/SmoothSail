"""Reproducible warm-route timings and a separate CPU profile; never log credentials."""
import argparse
import cProfile
import json
import pstats
import time
from datetime import datetime
from pathlib import Path

from service.config import settings
from service.data import Repository
from service.models import RouteRequest
from service.routing import calculate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--departure', default='2026-10-24T18:00:00+00:00')
    args = parser.parse_args()
    repo = Repository(settings.model_copy(update={'route_timeout_seconds': 180}))
    started = time.perf_counter()
    repo.load_graph()
    repo.forecast(datetime.fromisoformat(args.departure), (-180, -60, 180, 70))
    output = {'departureTime': args.departure, 'initializationSeconds': time.perf_counter() - started,
              'runs': []}
    for origin, destination in [('NLRTM', 'USNYC'), ('NLRTM', 'SGSIN'), ('USNYC', 'USLAX')]:
        request = RouteRequest(origin=origin, destination=destination, departure_time=args.departure)
        for iteration in range(2):
            started = time.perf_counter()
            response = calculate(request, repo)
            calculated = time.perf_counter()
            payload = response.model_dump_json(by_alias=True)
            output['runs'].append({'origin': origin, 'destination': destination, 'iteration': iteration,
                'calculationSeconds': calculated - started,
                'serializationSeconds': time.perf_counter() - calculated,
                'responseBytes': len(payload.encode()),
                'routes': [{'strategy': r.strategy, 'distanceNm': r.distance_nm, 'hours': r.duration_hours,
                            'fuelTonnes': r.cost.fuel_tonnes, 'costUsd': r.cost.total_usd}
                           for r in response.routes]})
            print(origin, destination, iteration, round(calculated - started, 3), flush=True)
    profile = cProfile.Profile()
    profile.runcall(calculate, RouteRequest(origin='NLRTM', destination='SGSIN', departure_time=args.departure), repo)
    stats = pstats.Stats(profile)
    output['profile'] = [{'function': f'{Path(key[0]).name}:{key[1]}:{key[2]}', 'calls': value[1],
                          'selfSeconds': round(value[2], 4), 'cumulativeSeconds': round(value[3], 4)}
                         for key, value in sorted(stats.stats.items(), key=lambda row: -row[1][3])[:40]]
    args.report.parent.mkdir(exist_ok=True, parents=True)
    args.report.write_text(json.dumps(output, indent=2) + '\n')
    if repo.client:
        repo.client.close()


if __name__ == '__main__':
    main()
