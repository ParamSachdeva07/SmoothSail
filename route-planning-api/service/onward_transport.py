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
        self.anchor_cache = {}
        self.geocode_lock = asyncio.Lock()
        self.last_geocode = 0.0

    async def port_anchor(self, locode, client):
        cached = self.anchor_cache.get(locode)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        record = await asyncio.to_thread(self.repository.port_road_anchor, locode)
        if not record:
            raise ValueError('Port access information is unavailable.')
        if record.get('coordinates'):
            result = {'coordinates': record['coordinates'], 'source': 'verified_port_access'}
        else:
            catalogue = record.get('catalogueCoordinates')
            if not catalogue or not record.get('name'):
                raise ValueError('No port-specific road access point is known.')
            # Search a named OSM port feature near the catalogue location. Never
            # route from the catalogue coordinate itself: it may be a city centre.
            lon, lat = map(float, catalogue)
            result = None
            for query in (f"container terminal {record['name']}", f"harbour {record['name']}"):
                async with self.geocode_lock:
                    pause = max(0.0, 1.05 - (time.monotonic() - self.last_geocode))
                    if pause:
                        await asyncio.sleep(pause)
                    self.last_geocode = time.monotonic()
                    response = await client.get('https://nominatim.openstreetmap.org/search', params={
                        'q': query, 'format': 'jsonv2', 'limit': 10,
                        'countrycodes': str(record.get('country') or locode[:2])[:2].lower(),
                        'viewbox': f'{lon-0.6},{lat+0.4},{lon+0.6},{lat-0.4}', 'bounded': 1,
                        'entrances': 1}, headers={'User-Agent': 'SmoothSail/1.0 (port-transfer-planning; contact: you@example.com)'})
                    response.raise_for_status()
                candidates = response.json()
                for feature in candidates if isinstance(candidates, list) else []:
                    kind = str(feature.get('type', '')).lower()
                    title = str(feature.get('display_name', '')).lower()
                    if kind not in {'port', 'harbour', 'terminal', 'dock', 'industrial'} or not any(
                        word in title for word in ('port', 'harbour', 'haven', 'hafen', 'terminal')):
                        continue
                    entrance = next((item for item in feature.get('entrances') or []
                        if item.get('lon') is not None and item.get('lat') is not None), None)
                    point = [float(entrance['lon']), float(entrance['lat'])] if entrance else [float(feature['lon']), float(feature['lat'])]
                    if abs(point[0] - lon) > 0.6 or abs(point[1] - lat) > 0.4:
                        continue
                    result = {'coordinates': point, 'source': 'osm_port_entrance' if entrance else 'osm_port_feature',
                        'osmUrl': f"https://www.openstreetmap.org/{'node' if feature.get('osm_type') == 'node' else 'way'}/{feature.get('osm_id')}"}
                    break
                if result:
                    break
            if not result:
                raise ValueError('No named OSM port feature was found near this port.')
        self.anchor_cache[locode] = (time.monotonic() + 86400, result)
        return result

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
        result = {'originPortId': origin_id, 'destinationPortId': destination_id,
            'status': 'unavailable', 'mode': 'road', 'geometry': None, 'cost': None,
            'checkedAt': datetime.now(UTC).isoformat(), 'distanceKm': None, 'drivingHours': None,
            'basis': 'One standard 40-foot container on one truck, one way, between port access areas.',
            'assumptions': ['Original voyage port is the cargo pickup/delivery proxy; no inland address was supplied.',
                'USD 2–4 per routed kilometre plus USD 150–300 dispatch allowance are planning assumptions, not local freight quotes.',
                'Excludes terminal handling, customs, duties, tolls, ferry charges, storage, waiting, empty return and loading/unloading.',
                'Road geometry uses a car profile from named port features or verified access points. Heavy-goods access, borders, ferry use and terminal gates require confirmation.'],
            'air': {'status': 'needs_quote', 'cost': None,
                'reason': 'Air transfer needs cargo weight/volume, airport availability, handling and an air-freight quote; a container is not an air shipment.'},
            'sources': [{'title': 'OSRM road routing / OpenStreetMap', 'url': 'https://project-osrm.org/docs/v5.24.0/api/'},
                {'title': 'OpenStreetMap port features', 'url': 'https://www.openstreetmap.org/'},
                {'title': 'ATRI 2026 US truck operating-cost benchmark (not a freight quote)', 'url': BENCHMARK_URL}],
            'benchmark': {'usdPerMile': 2.336, 'region': 'US', 'year': 2025, 'kind': 'carrier_operating_cost_not_freight_price'}}
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                anchors = await asyncio.gather(self.port_anchor(origin_id, client), self.port_anchor(destination_id, client))
                coords = ';'.join(','.join(str(float(v)) for v in item['coordinates']) for item in anchors)
                response = await client.get('https://router.project-osrm.org/route/v1/driving/' + coords,
                    params={'overview': 'simplified', 'geometries': 'geojson', 'steps': 'false', 'radiuses': '10000;10000'},
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
                roadAnchors={'origin': anchors[0], 'destination': anchors[1]},
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
