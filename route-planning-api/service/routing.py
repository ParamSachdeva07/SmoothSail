import time
from datetime import UTC, datetime, timedelta

import networkx as nx

from service.geo import distance_nm, interpolate, line_geometry
from service.models import RouteError, RouteRequest, RouteResponse
from service.metadata import enrich_route, report_metadata
from service.navigation import EXCLUDED_PASSAGES, default_land_mask
from service.canals import catalog, toll
from service.costs import canal_edge_estimate, fuel_and_time_cost, fuel_tonnes, resolve_vessel
from service.simulation import active_notice, check_deadline, prepare_path, simulate

def candidates(graph, origin, destination, forecast, departure, notices, count, deadline, model=None):
    result, used, costs, weather_costs = [], {}, {}, {}
    # A straight-line arrival guess cannot safely prune a temporary closure.
    # Effective-dated restrictions are checked at the actual simulated passage time.
    exclusions = [n for n in notices if n.get('action') == 'exclude' and n.get('verified')
                  and not n.get('validFrom') and not n.get('validTo')]
    model = model or resolve_vessel()
    search_speed = model['speedKnots'][1]
    hourly_fuel = fuel_tonnes(1, search_speed, model=model)
    canal_costs = {cid: toll(cid, model, departure)['amountUsd'] + c['serviceAllowanceUsd']
                   for cid, c in catalog()['canals'].items()}

    def cost(a, b, data):
        cid = data.get('canalId')
        if cid in avoid:
            return None
        if (a, b) not in costs:
            if len(costs) % 1000 == 0:
                check_deadline(deadline)
            hours = data['distanceNm'] / search_speed
            fuel = hours * hourly_fuel
            fee = 0
            if cid:
                hours, fuel = canal_edge_estimate(data, model)
                fee = canal_costs[cid] * data['canalFraction']
            blocked = any(active_notice(n, line_geometry(data['coordinates']), departure, departure + timedelta(hours=hours),
                                        data.get('passageIds', [])) for n in exclusions)
            costs[a, b] = {'blocked': blocked, 'time': hours, 'fuel': fuel,
                           'cost': sum(fuel_and_time_cost(fuel, hours, model)) + fee}
        base = costs[a, b]
        if base['blocked']:
            return None
        roughness = 0
        if weather_weight:
            weather_key = tuple(sorted((a, b)))
            if weather_key not in weather_costs:
                midpoint = interpolate(graph.nodes[a]['coordinates'], graph.nodes[b]['coordinates'], .5)
                entry = departure + timedelta(hours=distance_nm(graph.nodes[origin]['coordinates'], midpoint) / search_speed)
                sample = getattr(forecast, 'sample_weather', forecast.sample)(*midpoint, entry)
                weather_costs[weather_key] = ((sample['wave'] / 3)**2 + (sample['wind'] / 20)**2
                                      if sample['wave'] is not None and sample['wind'] is not None else 2)
            roughness = weather_costs[weather_key]
        return base[objective] * (1 + weather_weight * roughness + reuse * used.get((a, b), 0))

    # Explicit canal-free alternatives must compete even when the geometric
    # shortest path uses a canal. Tariff/time penalties participate in search,
    # followed by full time-dependent voyage simulation for final ranking.
    choices = [('time', set(), 0, 0), ('cost', set(), 0, 0), ('fuel', set(), 0, 0),
               ('time', {'suez'}, 0, 0), ('time', {'panama'}, 0, 0),
               ('time', {'suez', 'panama'}, 0, 0),
               ('time', set(), .35, .15), ('time', set(), 1.2, .2)]
    for attempt in range(count):
        check_deadline(deadline)
        objective, avoid, weather_weight, reuse = choices[attempt % len(choices)]
        if avoid and result and not any(graph[a][b].get('canalId') in avoid
                                        for a, b in zip(result[0], result[0][1:])):
            continue  # Removing unused canals cannot improve the same minimum-time path.
        try:
            path = nx.shortest_path(graph, origin, destination, weight=cost)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        if path not in result:
            result.append(path)
            for a, b in zip(path, path[1:]):
                used[a, b] = used.get((a, b), 0) + 1
    return result


def calculate(request: RouteRequest, repository):
    started = time.monotonic()
    with repository.planning_context():
        return _calculate(request, repository, started)


def _calculate(request, repository, started):
    phases, phase_start = {}, started
    def phase(name):
        nonlocal phase_start
        now = time.monotonic()
        phases[name], phase_start = round(now - phase_start, 6), now
    deadline = started + repository.settings.route_timeout_seconds
    departure = request.departure_time or datetime.now(UTC)
    model = resolve_vessel(request.vessel_parameters)
    speeds = model['speedKnots']
    origin, destination = repository.resolve_port(request.origin), repository.resolve_port(request.destination)
    graph = repository.load_graph()
    phase('referenceData')
    try:
        baseline = nx.shortest_path(graph, origin.routing_node_id, destination.routing_node_id, weight='distanceNm')
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        raise RouteError('no_route', 'The imported network does not connect these ports.') from None
    # Include offshore detour room, while keeping downloads bounded by provider policy.
    coords = [graph.nodes[n]['coordinates'] for n in baseline]
    bounds = (max(-180, min(p[0] for p in coords) - 8), max(-80, min(p[1] for p in coords) - 8),
              min(180, max(p[0] for p in coords) + 8), min(80, max(p[1] for p in coords) + 8))
    forecast = repository.forecast(departure, bounds)
    restrictions = repository.restrictions()
    phase('forecastAndRestrictions')
    paths = candidates(graph, origin.routing_node_id, destination.routing_node_id, forecast, departure,
                       restrictions, repository.settings.max_candidates, deadline, model)
    restrictions = repository.route_restrictions(graph, paths, restrictions)
    phase('candidateSearch')
    evaluated, geometry_cache = [], {}
    for path in paths:
        prepared = prepare_path(graph, path, geometry_cache)
        for speed in speeds:
            route = simulate(graph, path, speed, departure, forecast, restrictions, deadline, model, prepared)
            if route:
                evaluated.append(route)
    phase('voyageSimulation')
    if not evaluated:
        raise RouteError('no_feasible_route', 'No evaluated path is usable under the available network and restrictions.')
    fastest = min(evaluated, key=lambda r: (r.duration_hours, r.id))
    economical = min(evaluated, key=lambda r: (r.cost.total_usd, r.id))
    lowest_emissions = min(evaluated, key=lambda r: (r.emissions.co2_tonnes, r.cost.total_usd, r.id))
    selected, unavailable = [], []
    for strategy, winner in [('fastest', fastest), ('economical', economical), ('lowest_emissions', lowest_emissions)]:
        route = winner.model_copy(deep=True)
        route.strategy = strategy
        route.id = strategy + '-' + route.id
        if strategy == 'fastest':
            route.explanations = [f'Shortest estimated journey among {len(evaluated)} evaluated path and speed combinations.',
                                  f'Uses a {route.speed_knots:g}-knot cruising setting, adjusted for available currents, modelled wave slowdown and canal delays.']
        elif strategy == 'economical':
            saving = 100 * (1 - route.cost.total_usd / fastest.cost.total_usd) if fastest.cost.total_usd else 0
            route.explanations = [f'{saving:.1f}% lower estimated voyage cost than the fastest option, including fuel, vessel time and canal charges.',
                                  f'Arrives {route.duration_hours - fastest.duration_hours:.1f} hours after the fastest option.']
        else:
            saving = 100 * (1 - route.emissions.co2_tonnes / fastest.emissions.co2_tonnes) if fastest.emissions.co2_tonnes else 0
            route.explanations = [f'Lowest estimated fuel-related CO₂ among {len(evaluated)} evaluated path and speed combinations.',
                                  f'{route.emissions.co2_tonnes:,.0f} t CO₂; {saving:.1f}% lower than the fastest option.',
                                  'Ranks tank-to-wake CO₂ only; upstream fuel production, other pollutants and ecological impacts are not assessed.']
        if strategy != 'fastest' and route.geometry == fastest.geometry:
            route.explanations.append('Shares the fastest option’s geographic path; speed or objective differs.')
        if strategy == 'lowest_emissions' and route.id.split('-', 1)[-1] == economical.id:
            route.explanations.append('The cheapest and lowest-emissions objectives select the same path and speed under these assumptions.')
        route.explanations.append(f'Estimated USD {route.cost.total_usd:,.0f}: fuel {route.cost.fuel_usd:,.0f}, vessel time {route.cost.time_usd:,.0f}, canal tolls and allowances {route.cost.canal_tolls_usd + route.cost.canal_service_allowance_usd:,.0f}.')
        for transit in route.canal_transits:
            route.explanations.append(f'{transit.name}: {transit.transit_hours:g} h transit + {transit.waiting_hours:g} h assumed wait; USD {transit.toll_usd:,.0f} base toll estimate.')
        selected.append(route)
    phase('selection')
    wave_grid = None
    if repository.settings.tideline_mode == 'demo':
        overlays = forecast.overlays()
    else:
        overlays = {'type': 'FeatureCollection', 'features': []}
        # Display all available cached forecasts, including oceans away from the
        # chosen route. This does not fetch more data or change routing samples.
        # Unknown polar/coastal cells and times remain null.
        wave_grid = forecast.global_wave_grid(departure)
    for notice in restrictions:
        if notice.get('geometry'):
            overlays['features'].append({'type': 'Feature', 'geometry': notice['geometry'],
                                         'properties': {key: notice[key] for key in ['id', 'name', 'validFrom', 'validTo', 'action', 'verified', 'cancelled', 'sourceUrl'] if key in notice} | {'kind': 'restriction'}})
    phase('waveDisplay')
    check_deadline(deadline)
    notices = repository.activity_notices([origin, destination])
    notices.append(f'Routes end at approximate offshore approach points. Land screening uses {default_land_mask().name}; depth and pilotage clearance are not assessed.')
    if repository.settings.tideline_mode == 'mongo':
        notices.append('Reviewed Suez and Panama geometry is allowed through the land mask. Arctic, Kiel and Corinth passages are excluded for the generic vessel. Canal availability is a planning assumption, not operational approval.')
    if repository.settings.tideline_mode == 'demo':
        notices.insert(0, 'Demonstration: the network and moving weather scenario are illustrative, not operational forecasts.')
    if any(source.get('stale') for source in forecast.sources):
        notices.append('Expired forecast snapshots were excluded. Refresh provider data to restore coverage.')
    for route in selected:
        enrich_route(route, forecast, restrictions)
    metadata = report_metadata(request, repository, origin, destination, departure, forecast, restrictions,
                               time.monotonic() - started, speeds, len(evaluated), model)
    metadata.calculation_seconds = round(time.monotonic() - started, 3)
    metadata.routing_method['candidateComparisons'] = [
        {'id': r.id, 'distanceNm': r.distance_nm, 'durationHours': r.duration_hours,
         'speedKnots': r.speed_knots, 'canalIds': [t.canal_id for t in r.canal_transits],
         'estimatedCostUsd': r.cost.total_usd, 'fuelTonnes': r.cost.fuel_tonnes,
         'estimatedCo2Tonnes': r.emissions.co2_tonnes,
         'windWaveCoveragePercent': r.forecast_coverage_percent} for r in evaluated]
    check_deadline(deadline)
    phase('evidenceAndMetadata')
    metadata.phase_seconds = phases
    return RouteResponse(origin=origin.id, destination=destination.id, departure_time=departure, metadata=metadata,
                         mode=repository.settings.tideline_mode,
                         assumptions={'model': model['id'], 'speedsKnots': speeds,
                                      'graphVersion': repository.version, 'navigationVersion': 'gshhg-reviewed-canals-v4',
                                      'excludedPassages': sorted(EXCLUDED_PASSAGES),
                                      'landScreen': default_land_mask().name, 'vessel': model, 'canalCatalogVersion': catalog()['version'],
                                      'fuelBasis': 'estimated-tonnes-and-usd', 'physicalClearance': 'not_assessed',
                                      'etaDestination': 'mapped approach point', 'evaluatedCombinations': len(evaluated)},
                         routes=selected, unavailable_strategies=unavailable, overlays=overlays,
                         wave_grid=wave_grid,
                         sources=forecast.sources, notices=notices)
