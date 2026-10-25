"""Indicative port-to-port road transfer, separate from whole-vessel ocean costs."""
import asyncio
import math
import time
from datetime import UTC, datetime

import httpx

BENCHMARK_URL = 'https://truckingresearch.org/2026/07/new-atri-report-details-accelerating-costs-and-low-profitability-despite-cuts/'


class OnwardTransport:
    def __init__(self, repository, transport=None):
        self.repository, self.transport = repository, transport
        self.cache, self.pending = {}, {}

    async def estimate(self, origin_id, destination_id):
        key = (origin_id, destination_id)
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if key not in self.pending:
            task = asyncio.create_task(self._estimate(*key))
            self.pending[key] = task
            task.add_done_callback(lambda _: self.pending.pop(key, None))
        result = await asyncio.shield(self.pending[key])
        self.cache[key] = (time.monotonic() + (1800 if result['status'] == 'estimated' else 60), result)
        while len(self.cache) > 128: self.cache.pop(next(iter(self.cache)))
        return result

    async def _estimate(self, origin_id, destination_id):
        locations = await asyncio.to_thread(lambda: [self.repository.port_land_coordinates(p) for p in (origin_id, destination_id)])
        result = {'originPortId': origin_id, 'destinationPortId': destination_id,
            'status': 'unavailable', 'mode': 'road', 'geometry': None, 'cost': None,
            'checkedAt': datetime.now(UTC).isoformat(), 'distanceKm': None, 'drivingHours': None,
            'basis': 'One standard 40-foot container on one truck, one way, between port access areas.',
            'assumptions': ['Original voyage port is the cargo pickup/delivery proxy; no inland address was supplied.',
                'USD 2–4 per routed kilometre plus USD 150–300 dispatch allowance are planning assumptions, not local freight quotes.',
                'Excludes terminal handling, customs, duties, tolls, ferry charges, storage, waiting, empty return and loading/unloading.',
                'Road geometry uses a car profile. Heavy-goods access, borders, ferry use and terminal gates require confirmation.'],
            'air': {'status': 'needs_quote', 'cost': None,
                'reason': 'Air transfer needs cargo weight/volume, airport availability, handling and an air-freight quote; a container is not an air shipment.'},
            'sources': [{'title': 'OSRM road routing / OpenStreetMap', 'url': 'https://project-osrm.org/docs/v5.24.0/api/'},
                {'title': 'ATRI 2026 US truck operating-cost benchmark (not a freight quote)', 'url': BENCHMARK_URL}],
            'benchmark': {'usdPerMile': 2.336, 'region': 'US', 'year': 2025, 'kind': 'carrier_operating_cost_not_freight_price'}}
        try:
            if any(not isinstance(p, (tuple, list)) or len(p) != 2 for p in locations):
                raise ValueError('Landside port coordinates are unavailable.')
            coords = ';'.join(','.join(str(float(v)) for v in p) for p in locations)
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                response = await client.get('https://router.project-osrm.org/route/v1/driving/' + coords,
                    params={'overview': 'simplified', 'geometries': 'geojson', 'steps': 'false', 'radiuses': '5000;5000'},
                    headers={'User-Agent': 'SmoothSail/1.0 port-transfer-planning'})
                response.raise_for_status()
                data = response.json()
            if data.get('code') != 'Ok' or not data.get('routes'): raise ValueError('No connected road route returned.')
            route = data['routes'][0]
            distance, hours = float(route['distance']) / 1000, float(route['duration']) / 3600
            geometry = route['geometry']
            if not all(math.isfinite(v) and v >= 0 for v in (distance, hours)) or distance > 3000:
                raise ValueError('Road transfer is outside the 3,000 km planning range.')
            if geometry.get('type') != 'LineString' or len(geometry.get('coordinates', [])) < 2:
                raise ValueError('No usable road geometry returned.')
            result.update(status='estimated', geometry=geometry, distanceKm=round(distance, 1), drivingHours=round(hours, 1),
                cost={'currency': 'USD', 'low': round(distance * 2 + 150), 'high': round(distance * 4 + 300),
                    'basis': 'per_40ft_container_one_way', 'rateUsdPerKm': [2, 4], 'dispatchAllowanceUsd': [150, 300],
                    'method': 'explicit_planning_scenario', 'isQuote': False},
                note='Indicative road transfer; terminal availability and truck access are unverified.')
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            result['note'] = 'No usable road connection was obtained. Arrange a local road, feeder or air quote; no straight line is presented as a road.'
        return result

    async def close(self):
        tasks = list(self.pending.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
