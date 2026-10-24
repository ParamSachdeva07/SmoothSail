"""Voyage simulation: geometry, passage time, environment and fuel in one pass."""
import hashlib
import math
import time
from datetime import UTC, datetime, timedelta

from shapely.geometry import shape

from service.canals import catalog, toll
from service.costs import breakdown, emissions, fuel_tonnes, resolve_vessel, speed_loss
from service.forecast import KNOTS_PER_MS, as_utc
from service.geo import bearing, densify, distance_nm, interpolate, line_geometry
from service.models import CanalTransit, Route, RouteError, Segment

def active_notice(notice, geometry, entry, exit, passages):
    if notice.get('cancelled'):
        return False
    start = as_utc(notice['validFrom']) if notice.get('validFrom') else datetime.min.replace(tzinfo=UTC)
    end = as_utc(notice['validTo']) if notice.get('validTo') else datetime.max.replace(tzinfo=UTC)
    if entry >= end or exit <= start:
        return False
    if notice.get('passageId') in passages:
        return True
    return bool(notice.get('geometry') and shape(notice['geometry']).intersects(shape(geometry)))


def check_deadline(deadline):
    if time.monotonic() > deadline:
        raise RouteError('calculation_timeout', 'This route exceeded the calculation budget. Try a shorter voyage.', 504)


def prepare_path(graph, path, cache=None):
    """Compute invariant geometry once, then reuse it at each operating speed."""
    cache = {} if cache is None else cache
    prepared = []
    for origin, destination in zip(path, path[1:]):
        key = origin, destination
        if key not in cache:
            edge = graph[origin][destination]
            coords = densify(edge['coordinates'], max_nm=1 if edge.get('canalId') else 10)
            legs = [(a, b, distance_nm(a, b), interpolate(a, b, .5), math.radians(bearing(a, b)),
                     line_geometry([a, b])) for a, b in zip(coords, coords[1:])]
            reference = {'fromNodeId': origin, 'toNodeId': destination,
                         'sourceEdgeId': edge.get('sourceEdgeId'), 'passageIds': edge.get('passageIds', [])}
            cache[key] = edge, coords, legs, reference, sum(leg[2] for leg in legs)
        prepared.append(cache[key])
    return prepared


def environment_at(forecast, midpoint, timestamp):
    if hasattr(forecast, 'sample_with_provenance'):
        return forecast.sample_with_provenance(*midpoint, timestamp)
    return forecast.sample(*midpoint, timestamp), {}


def simulate(graph, path, speed, departure, forecast, notices, deadline, model=None, prepared=None):
    model = model or resolve_vessel()
    timestamp = departure
    segments, points, passages, transits = [], [], set(), []
    exposure = covered = distance = rough = missing_current = total_fuel = 0.0
    sailing_hours = canal_hours = waiting_hours = 0.0
    waves, winds, notice_ids = [], [], set()
    previous_canal = None
    unconverged = 0
    for edge, coords, legs, reference, edge_nm in prepared or prepare_path(graph, path):
        cid = edge.get('canalId')
        passages.update(edge.get('passageIds', []))
        points.extend(coords if not points else coords[1:])
        if cid and cid != previous_canal:
            canal = catalog()['canals'][cid]
            tariff = toll(cid, model, timestamp)
            wait_end = timestamp + timedelta(hours=canal['waitingHours'])
            wait_fuel = fuel_tonnes(canal['waitingHours'], 0, waiting=True, model=model)
            matched = [n for n in notices if active_notice(n, line_geometry([coords[0], coords[0]]),
                                                         timestamp, wait_end, edge.get('passageIds', []))]
            if any(n.get('action') == 'exclude' and n.get('verified') for n in matched):
                return None
            notice_ids.update(n['id'] for n in matched)
            segments.append(Segment(geometry=line_geometry([coords[0], coords[0]]), entry_time=timestamp,
                exit_time=wait_end, distance_nm=0, speed_through_water_knots=0, wave_height_m=None,
                wind_knots=None, along_track_current_knots=None, notice_ids=[n['id'] for n in matched],
                sample_time=timestamp + (wait_end - timestamp) / 2, network_reference=reference,
                kind='canal_wait', fuel_tonnes=round(wait_fuel, 8)))
            transits.append(CanalTransit(canal_id=cid, name=canal['name'], entry_time=timestamp,
                transit_start_time=wait_end, exit_time=wait_end, waiting_hours=canal['waitingHours'],
                transit_hours=0, toll_usd=tariff['amountUsd'], service_allowance_usd=canal['serviceAllowanceUsd'],
                tariff=tariff, timing_basis=canal['timingBasis'], operational_status=canal['status']))
            timestamp = wait_end
            total_fuel += wait_fuel
            waiting_hours += canal['waitingHours']
        for a, b, nm, midpoint, angle, geometry in legs:
            check_deadline(deadline)
            if nm < .00001:
                continue
            hours = nm / speed
            current = None
            through_water = speed
            if cid:
                hours = catalog()['canals'][cid]['transitHours'] * edge['canalFraction'] * nm / edge_nm
                sample_time = timestamp + timedelta(hours=hours / 2)
                sample, source_ids = environment_at(forecast, midpoint, sample_time)
                through_water = nm / hours
            else:
                for _ in range(8):
                    sample_time = timestamp + timedelta(hours=hours / 2)
                    sample, source_ids = environment_at(forecast, midpoint, sample_time)
                    if sample['u'] is not None and sample['v'] is not None:
                        current = (sample['u'] * math.sin(angle) + sample['v'] * math.cos(angle)) * KNOTS_PER_MS
                    else:
                        current = None
                    through_water = speed * (1 - speed_loss(sample['wave']))
                    ground_speed = through_water + (current if current is not None else 0)
                    if ground_speed <= 0:
                        return None
                    updated = nm / ground_speed
                    converged = abs(updated - hours) < 1 / 3600  # one second on a <=10 nm leg
                    hours = updated
                    if converged:
                        break
                if not converged:
                    unconverged += 1
            exit_time = timestamp + timedelta(hours=hours)
            matched = [n for n in notices if active_notice(n, geometry, timestamp, exit_time, edge.get('passageIds', []))]
            if any(n.get('action') == 'exclude' and n.get('verified') for n in matched):
                return None
            ids = [n['id'] for n in matched]
            notice_ids.update(ids)
            wave, wind = sample['wave'], sample['wind']
            if wave is not None and wind is not None:
                exposure += hours * ((wave / 3)**2 + (wind / 20)**2)
                covered += hours
            if wave is not None:
                waves.append(wave)
                if wave > 3:
                    rough += hours
            if wind is not None:
                winds.append(wind)
            if current is None and not cid:
                missing_current += hours
            fuel = fuel_tonnes(hours, through_water if cid else speed, model=model)
            total_fuel += fuel
            if cid:
                canal_hours += hours
                transits[-1].transit_hours += hours
                transits[-1].exit_time = exit_time
            else:
                sailing_hours += hours
            distance += nm
            segments.append(Segment(geometry=geometry, entry_time=timestamp, exit_time=exit_time,
                distance_nm=round(nm, 3), speed_through_water_knots=round(through_water, 4),
                wave_height_m=round(wave, 2) if wave is not None else None,
                wind_knots=round(wind, 2) if wind is not None else None,
                along_track_current_knots=round(current, 3) if current is not None else None,
                notice_ids=ids, sample_time=sample_time, network_reference=reference,
                kind='canal_transit' if cid else 'sailing', fuel_tonnes=round(fuel, 8)))
            segments[-1]._environment = sample
            segments[-1]._environment_sources = source_ids
            timestamp = exit_time
        previous_canal = cid
    if not segments:
        return None
    duration = (timestamp - departure).total_seconds() / 3600
    coverage = covered / duration * 100
    warnings = []
    if unconverged:
        warnings.append(f'Environmental timing did not converge within one second on {unconverged} segments; those estimates need review.')
    if model.get('fuelCurve') and transits:
        warnings.append('Canal propulsion below the supplied fuel-curve range uses cubic extrapolation from its lowest point; canal fuel remains uncertain.')
    if coverage < 99.99:
        warnings.append(f'{duration - covered:.1f} voyage hours have incomplete wind/wave coverage, including any canal waiting. Unknown conditions are not scored as calm.')
    if missing_current > .01:
        warnings.append(f'Current assistance is unknown for {missing_current:.1f} sailing hours; no current adjustment is applied then.')
    if transits:
        warnings.append('Canal waiting times and service allowances are assumptions. Base toll estimates exclude listed adjustments; actual permission, bookings and security are not verified.')
    if notice_ids:
        warnings.append('Intersects advisory notices: ' + ', '.join(sorted(notice_ids)))
    for transit in transits:
        transit.transit_hours = round(transit.transit_hours, 6)
    return Route(id=hashlib.sha256(('|'.join(path) + str(speed)).encode()).hexdigest()[:12], strategy='fastest',
        geometry=line_geometry(points), distance_nm=round(distance, 1), duration_hours=round(duration, 2),
        eta=timestamp, speed_knots=speed,
        exposure_score=round(exposure, 2) if coverage >= 99.99 else None,
        forecast_coverage_percent=round(coverage, 2), unknown_weather_hours=round(duration - covered, 2),
        max_wave_height_m=round(max(waves), 2) if waves else None,
        max_wind_knots=round(max(winds), 2) if winds else None, rough_sea_hours=round(rough, 1),
        segments=segments, passage_ids=sorted(passages), explanations=[], warnings=warnings,
        cost=breakdown(total_fuel, duration, transits, model), emissions=emissions(total_fuel, model), canal_transits=transits,
        sailing_hours=round(sailing_hours, 6), canal_hours=round(canal_hours, 6), waiting_hours=waiting_hours)
