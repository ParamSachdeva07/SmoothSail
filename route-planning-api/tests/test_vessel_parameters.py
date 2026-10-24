import time
from datetime import UTC, datetime

import networkx as nx
import pytest
from pydantic import ValidationError

from service.config import Settings
from service.costs import resolve_vessel, vessel_model
from service.data import Repository
from service.forecast import GridForecast
from service.models import RouteRequest, VesselParameters
from service.routing import calculate, simulate


def test_optional_overrides_are_isolated_and_zero_values_are_preserved():
    defaults = resolve_vessel()
    supplied = resolve_vessel(VesselParameters(service_speed_knots=20, main_fuel_tonnes_per_day=60,
                                               auxiliary_fuel_tonnes_per_day=0, daily_vessel_cost_usd=0))
    assert supplied['speedKnots'] == [15, 17.5, 20]
    assert supplied['referenceSpeedKnots'] == 20
    assert supplied['mainFuelTonnesPerDayAtReferenceSpeed'] == 60
    assert supplied['auxiliaryFuelTonnesPerDay'] == supplied['dailyVesselCostUsd'] == 0
    assert supplied['inputProvenance']['userSupplied']['mainFuelTonnesPerDay'] == 60
    assert resolve_vessel() == defaults
    assert vessel_model()['speedKnots'] == [12, 14, 16]
    assert resolve_vessel(VesselParameters()) == defaults


@pytest.mark.parametrize('payload', [{'serviceSpeedKnots': 0}, {'mainFuelTonnesPerDay': -1},
                                    {'fuelUsdPerTonne': float('inf')}, {'mainFuelTonnesPerDay': float('nan')},
                                    {'fuelCategory': 'unknown'}])
def test_invalid_parameters_are_rejected(payload):
    with pytest.raises(ValidationError):
        VesselParameters.model_validate(payload)


def test_consumption_price_and_fuel_category_change_actual_outputs():
    graph = nx.DiGraph()
    graph.add_edge('a', 'b', coordinates=[[-20, 40], [-18, 40]], passageIds=[])
    now = datetime(2026, 10, 24, tzinfo=UTC)
    base = simulate(graph, ['a', 'b'], 16, now, GridForecast([]), [], time.monotonic() + 10)
    model = resolve_vessel(VesselParameters(main_fuel_tonnes_per_day=76, auxiliary_fuel_tonnes_per_day=6,
                                           fuel_usd_per_tonne=vessel_model()['fuelUsdPerTonne'] * 2, fuel_category='marine_diesel'))
    custom = simulate(graph, ['a', 'b'], 16, now, GridForecast([]), [], time.monotonic() + 10, model)
    assert custom.eta == base.eta
    assert custom.cost.fuel_tonnes == pytest.approx(base.cost.fuel_tonnes * 2, abs=.00001)
    assert custom.cost.fuel_usd == pytest.approx(base.cost.fuel_usd * 4, abs=.03)
    assert custom.cost.time_usd == base.cost.time_usd
    assert custom.emissions.co2_tonnes == pytest.approx(custom.cost.fuel_tonnes * 3.206, abs=.00001)


def test_custom_speed_reaches_route_selection_and_report_without_changing_next_request():
    repo = Repository(Settings(tideline_mode='demo'))
    base = {'origin': 'NLRTM', 'destination': 'PTLIS', 'departureTime': '2026-10-24T00:00:00Z'}
    custom = calculate(RouteRequest.model_validate(base | {'vesselParameters': {'serviceSpeedKnots': 20}}), repo)
    assert custom.metadata.vessel_model['inputProvenance']['userSupplied'] == {'serviceSpeedKnots': 20}
    assert custom.assumptions['speedsKnots'] == [15, 17.5, 20]
    assert all(route.speed_knots in [15, 17.5, 20] for route in custom.routes)
    following = calculate(RouteRequest.model_validate(base), repo)
    assert following.assumptions['speedsKnots'] == [12, 14, 16]
    assert not following.metadata.vessel_model['inputProvenance']['userSupplied']
