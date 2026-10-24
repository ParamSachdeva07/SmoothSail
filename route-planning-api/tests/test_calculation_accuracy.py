"""Independent engineering checks and regressions; not measured voyage validation."""
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from service.costs import fuel_tonnes, main_fuel_per_day, resolve_vessel
from service.interpolation import GridField
from service.metadata import enrich_route
from service.models import VesselParameters
from service.routing import candidates, simulate


def test_scalar_and_batch_interpolation_match_independent_scipy_oracle():
    rng = np.random.default_rng(73)
    axes = (np.array([0., 10800., 21600.]), np.array([40., 41., 43.]), np.array([-20., -18., -16.]))
    values = rng.uniform(0, 8, (3, 3, 3))
    points = rng.uniform([0, 40, -20], [21600, 43, -16], (100, 3))
    field = GridField(axes, values, 10800, 'fixture')
    expected = RegularGridInterpolator(axes, values)(points)
    assert field.sample_many(points) == pytest.approx(expected, abs=1e-12)
    assert [field.sample(*point) for point in points] == pytest.approx(expected, abs=1e-12)


def test_exact_nodes_survive_unused_missing_neighbours_but_unknown_interior_does_not():
    values = np.full((2, 2, 2), np.nan)
    values[0, 0, 0] = 3.5
    field = GridField((np.array([0., 1.]),) * 3, values, 1, 'fixture')
    assert field.sample(0, 0, 0) == 3.5
    assert field.sample(.5, .5, .5) is None
    batch = field.sample_many(np.array([[0, 0, 0], [.5, .5, .5], [2, 0, 0]]))
    assert batch[0] == 3.5 and np.isnan(batch[1:]).all()


def test_imo_speed_rule_checks_daily_and_fixed_distance_fuel_separately():
    # IMO GreenVoyage2050: 10% slower -> 27.1% less propulsion per day,
    # but 19% less propulsion over the same distance because the voyage is longer.
    model = resolve_vessel(VesselParameters(auxiliary_fuel_tonnes_per_day=0))
    reference = fuel_tonnes(24, 16, model=model)
    assert fuel_tonnes(24, 14.4, model=model) / reference == pytest.approx(.729)
    assert fuel_tonnes(24 / .9, 14.4, model=model) / reference == pytest.approx(.81)


def test_published_curve_points_drive_real_voyage_fuel_without_a_cubic_override():
    evidence = json.loads((Path(__file__).parents[1] / 'data/validation/fuel-benchmarks.json').read_text())
    points = evidence['consumption']['points']
    parameters = VesselParameters(fuel_curve=[{'speedKnots': speed, 'mainFuelTonnesPerDay': fuel}
                                               for speed, fuel in points], auxiliary_fuel_tonnes_per_day=3)
    model = resolve_vessel(parameters)
    assert main_fuel_per_day(14, model) == 32
    assert main_fuel_per_day(15.5, model) == pytest.approx((35.1 + 37.8) / 2)
    graph = nx.DiGraph()
    graph.add_edge('a', 'b', coordinates=[[0, 0], [1, 0]], passageIds=[])
    class Calm:
        sources = []
        def sample(self, *args):
            return {'wave': 0, 'wind': 0, 'u': 0, 'v': 0}
    route = simulate(graph, ['a', 'b'], 14, datetime(2026, 10, 24, tzinfo=UTC), Calm(), [], time.monotonic() + 10, model)
    # WGS84 equatorial degree = 111319.49079327357 metres, independent of route rounding.
    hours = 111319.49079327357 / 1852 / 14
    expected_fuel = hours / 24 * (32 + 3)
    assert route.cost.fuel_tonnes == pytest.approx(expected_fuel, abs=1e-6)
    assert route.cost.fuel_usd == pytest.approx(round(expected_fuel * 763, 2))
    assert route.cost.time_usd == pytest.approx(round(hours / 24 * 18000, 2))


@pytest.mark.parametrize('curve', [
    [{'speedKnots': 14, 'mainFuelTonnesPerDay': 30}],
    [{'speedKnots': 14, 'mainFuelTonnesPerDay': 30}, {'speedKnots': 14, 'mainFuelTonnesPerDay': 35}],
    [{'speedKnots': 14, 'mainFuelTonnesPerDay': 35}, {'speedKnots': 16, 'mainFuelTonnesPerDay': 30}],
])
def test_invalid_curves_cannot_silently_fall_back_to_generic(curve):
    with pytest.raises(ValueError):
        VesselParameters(fuelCurve=curve)


def test_metadata_uses_the_same_environment_that_determined_fuel_and_eta():
    graph = nx.DiGraph()
    graph.add_edge('a', 'b', coordinates=[[0, 0], [1, 0]], passageIds=[])
    class Environment:
        sources = []
        def sample(self, *args):
            return {'wave': 2.5, 'wind': 12, 'u': .5, 'v': 0}
    forecast = Environment()
    route = simulate(graph, ['a', 'b'], 16, datetime(2026, 10, 24, tzinfo=UTC), forecast, [], time.monotonic() + 10)
    def unavailable(*args):
        raise AssertionError('Metadata must not resample a potentially changed forecast')
    forecast.sample = unavailable
    enrich_route(route, forecast, [])
    assert all(s.metadata.conditions['waveHeight'].value == s.wave_height_m for s in route.segments)
    assert all(s.metadata.conditions['currentEast'].value == .5 for s in route.segments)


def test_temporary_closure_is_checked_at_passage_not_straight_line_arrival_guess():
    graph = nx.DiGraph()
    graph.add_node('a', coordinates=[0, 0])
    graph.add_node('b', coordinates=[10, 0])
    graph.add_edge('a', 'b', coordinates=[[0, 0], [10, 0]], distanceNm=601.077164, passageIds=[])
    departure = datetime(2026, 10, 24, tzinfo=UTC)
    notice = {'id': 'temporary', 'action': 'exclude', 'verified': True,
              'validFrom': departure + timedelta(hours=20), 'validTo': departure + timedelta(hours=22),
              'geometry': {'type': 'Polygon', 'coordinates': [[[9.5, -1], [10.1, -1], [10.1, 1], [9.5, 1], [9.5, -1]]]}}
    class Calm:
        def sample(self, *args):
            return {'wave': 0, 'wind': 0, 'u': 0, 'v': 0}
    paths = candidates(graph, 'a', 'b', Calm(), departure, [notice], 3, time.monotonic() + 10)
    assert paths == [['a', 'b']]
    route = simulate(graph, paths[0], 14, departure, Calm(), [notice], time.monotonic() + 10)
    assert route is not None and route.duration_hours > 40
