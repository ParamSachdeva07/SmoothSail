from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PrivateAttr, model_validator


def camel(value: str) -> str:
    first, *rest = value.split('_')
    return first + ''.join(word.title() for word in rest)


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra='forbid')


CountryCode = Annotated[str, Field(pattern=r'^[A-Z]{2}$')]


class DeclaredVessel(Model):
    name: str | None = Field(default=None, max_length=200)
    imo_number: str | None = Field(default=None, pattern=r'^\d{7}$')
    mmsi: str | None = Field(default=None, pattern=r'^\d{9}$')
    flag_country_code: CountryCode | None = None
    length_m: float | None = Field(default=None, gt=0)
    beam_m: float | None = Field(default=None, gt=0)
    draft_m: float | None = Field(default=None, gt=0)
    air_draft_m: float | None = Field(default=None, gt=0)
    ice_class: str | None = Field(default=None, max_length=80)
    gross_tonnage: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    build_country_code: CountryCode | None = None


class DeclaredParty(Model):
    role: Literal['owner', 'beneficial_owner', 'operator', 'charterer', 'shipper', 'consignee', 'other']
    name: str = Field(min_length=1, max_length=200)
    country_code: CountryCode | None = None
    registration_id: str | None = Field(default=None, max_length=100)


class DeclaredCargo(Model):
    description: str | None = Field(default=None, max_length=2000)
    hs_codes: list[Annotated[str, Field(pattern=r'^\d{6,10}$')]] = Field(default_factory=list, max_length=100)
    un_numbers: list[Annotated[str, Field(pattern=r'^UN\d{4}$')]] = Field(default_factory=list, max_length=100)
    origin_country_code: CountryCode | None = None
    destination_country_code: CountryCode | None = None
    customs_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    quantity_unit: Literal['containers', 'tonnes', 'items'] | None = None


class ComplianceInput(Model):
    """Optional user declarations for downstream review; not verified or used to change routing."""
    vessel: DeclaredVessel | None = None
    cargo: DeclaredCargo | None = None
    parties: list[DeclaredParty] = Field(default_factory=list, max_length=100)
    applicable_jurisdictions: list[CountryCode] = Field(default_factory=list, max_length=100)


class FuelCurvePoint(Model):
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra='forbid', allow_inf_nan=False)
    speed_knots: float = Field(ge=5, le=30)
    main_fuel_tonnes_per_day: float = Field(gt=0, le=500)


class VesselParameters(Model):
    """Optional per-request performance assumptions; never persisted as a profile."""
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra='forbid', allow_inf_nan=False)
    service_speed_knots: float | None = Field(default=None, ge=5, le=30)
    main_fuel_tonnes_per_day: float | None = Field(default=None, gt=0, le=500)
    auxiliary_fuel_tonnes_per_day: float | None = Field(default=None, ge=0, le=50)
    daily_vessel_cost_usd: float | None = Field(default=None, ge=0, le=500000)
    fuel_usd_per_tonne: float | None = Field(default=None, gt=0, le=5000)
    fuel_category: Literal['residual_hfo', 'light_fuel_oil', 'marine_diesel'] | None = None
    fuel_curve: list[FuelCurvePoint] | None = Field(default=None, min_length=2, max_length=12)

    @model_validator(mode='after')
    def validate_curve(self):
        if self.fuel_curve:
            if self.main_fuel_tonnes_per_day is not None:
                raise ValueError('Supply either a fuel curve or a single main-fuel reference rate, not both.')
            points = self.fuel_curve
            if any(a.speed_knots >= b.speed_knots or a.main_fuel_tonnes_per_day > b.main_fuel_tonnes_per_day
                   for a, b in zip(points, points[1:])):
                raise ValueError('Fuel curve speeds must increase and consumption must not decrease.')
            if self.service_speed_knots is not None and not points[0].speed_knots < self.service_speed_knots <= points[-1].speed_knots:
                raise ValueError('Service speed must be above the minimum and within the supplied fuel curve.')
        return self


class RouteRequest(Model):
    origin: str = Field(min_length=5, max_length=5, pattern=r'^[A-Z]{2}[A-Z0-9]{3}$')
    destination: str = Field(min_length=5, max_length=5, pattern=r'^[A-Z]{2}[A-Z0-9]{3}$')
    departure_time: AwareDatetime | None = None
    compliance_context: ComplianceInput | None = None
    vessel_parameters: VesselParameters | None = None

    @model_validator(mode='after')
    def different_ports(self):
        if self.origin == self.destination:
            raise ValueError('Choose two different ports.')
        return self


class Port(Model):
    id: str
    name: str
    country: str
    coordinates: tuple[float, float]
    routing_node_id: str


class NetworkReference(Model):
    from_node_id: str
    to_node_id: str
    source_edge_id: str | None = None
    passage_ids: list[str] = Field(default_factory=list)


class ConditionEvidence(Model):
    value: float | None
    unit: str
    status: Literal['forecast', 'simulated', 'unknown']
    snapshot_id: str | None = None
    missing_reason: str | None = None


class SegmentMetadata(Model):
    reference_id: str
    index: int
    start: list[float]
    end: list[float]
    midpoint: list[float]
    course_degrees_true: float
    duration_hours: float
    elapsed_start_hours: float
    elapsed_end_hours: float
    cumulative_start_nm: float
    cumulative_end_nm: float
    speed_over_ground_knots: float
    conditions: dict[str, ConditionEvidence]
    jurisdiction_status: Literal['not_assessed'] = 'not_assessed'
    jurisdiction_ids: list[str] | None = None


class CoverageMetric(Model):
    known_hours: float
    unknown_hours: float
    percent: float


class UnknownInterval(Model):
    variable: str
    first_segment_index: int
    last_segment_index: int
    entry_time: datetime
    exit_time: datetime


class RouteEvent(Model):
    reference_id: str
    first_segment_index: int
    last_segment_index: int
    entry_time: datetime
    exit_time: datetime


class RouteMetadata(Model):
    content_sha256: str
    geometry_sha256: str
    bounding_boxes: list[list[float]]
    crosses_antimeridian: bool
    forecast_snapshot_ids_used: list[str]
    coverage: dict[str, CoverageMetric]
    unknown_intervals: list[UnknownInterval]
    passage_events: list[RouteEvent]
    restriction_events: list[RouteEvent]
    restriction_screening: dict
    quality_flags: list[str]
    compliance_status: Literal['not_assessed'] = 'not_assessed'


class PortContext(Model):
    locode: str
    name: str
    country_code: str
    catalogue_coordinates: list[float] | None = None
    approach_coordinates: list[float]
    routing_node_id: str
    catalogue_import_version: str | None = None
    approach_basis: str = 'approximate offshore network access point'
    portwatch_location_id: str | None = None
    latest_activity_date: str | None = None
    activity_interpretation: str = 'Activity observation only; does not establish closure, delay or permission.'


class RestrictionRecord(Model):
    id: str
    name: str | None = None
    action: str | None = None
    verified: bool = False
    passage_id: str | None = None
    geometry: dict | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    source_url: str | None = None
    source_reference: str | None = None


class ComplianceCheck(Model):
    id: str
    status: Literal['not_assessed', 'limited_screening']
    evidence: list[str]
    missing_data: list[str]


class ComplianceHandoff(Model):
    status: Literal['not_assessed'] = 'not_assessed'
    decision: None = None
    declared_context: ComplianceInput | None = None
    declaration_status: Literal['user_provided_unverified', 'not_provided']
    declarations_used_for_routing: bool = False
    checks: list[ComplianceCheck]
    interpretation_rules: list[str]


class ReportMetadata(Model):
    coordinate_system: dict
    units: dict[str, str]
    request: dict
    ports: dict[str, PortContext]
    routing_method: dict
    vessel_model: dict
    data_provenance: dict
    restriction_catalog: list[RestrictionRecord]
    compliance_handoff: ComplianceHandoff
    calculation_seconds: float
    phase_seconds: dict[str, float] = Field(default_factory=dict)


class Segment(Model):
    _environment: dict | None = PrivateAttr(default=None)
    _environment_sources: dict = PrivateAttr(default_factory=dict)
    geometry: dict
    entry_time: datetime
    exit_time: datetime
    distance_nm: float
    speed_through_water_knots: float
    wave_height_m: float | None
    wind_knots: float | None
    along_track_current_knots: float | None
    notice_ids: list[str] = Field(default_factory=list)
    sample_time: datetime
    network_reference: NetworkReference
    metadata: SegmentMetadata | None = None
    kind: Literal['sailing', 'canal_transit', 'canal_wait'] = 'sailing'
    fuel_tonnes: float = 0


class CanalTransit(Model):
    canal_id: str
    name: str
    entry_time: datetime
    transit_start_time: datetime
    exit_time: datetime
    waiting_hours: float
    transit_hours: float
    toll_usd: float
    service_allowance_usd: float
    tariff: dict
    timing_basis: str
    operational_status: str


class CostBreakdown(Model):
    currency: Literal['USD'] = 'USD'
    period: Literal['entire_voyage'] = 'entire_voyage'
    fuel_tonnes: float
    fuel_usd: float
    fuel_usd_per_tonne: float
    average_fuel_tonnes_per_day: float
    average_fuel_usd_per_day: float
    time_usd: float
    canal_tolls_usd: float
    canal_service_allowance_usd: float
    total_usd: float
    basis: str
    model_id: str
    excluded_costs: list[str]


class EmissionsEstimate(Model):
    co2_tonnes: float
    factor_tonnes_co2_per_tonne_fuel: float
    fuel_category: str
    boundary: Literal['tank_to_wake_CO2'] = 'tank_to_wake_CO2'
    basis: str
    source_url: str
    excluded_impacts: list[str]


class Route(Model):
    id: str
    strategy: Literal['fastest', 'economical', 'lowest_emissions']
    geometry: dict
    distance_nm: float
    duration_hours: float
    eta: datetime
    speed_knots: float
    exposure_score: float | None
    forecast_coverage_percent: float
    unknown_weather_hours: float
    max_wave_height_m: float | None
    max_wind_knots: float | None
    rough_sea_hours: float
    segments: list[Segment]
    passage_ids: list[str]
    explanations: list[str]
    warnings: list[str]
    compliance_status: str = 'not_assessed'
    metadata: RouteMetadata | None = None
    cost: CostBreakdown
    emissions: EmissionsEstimate
    canal_transits: list[CanalTransit] = Field(default_factory=list)
    sailing_hours: float
    canal_hours: float = 0
    waiting_hours: float = 0


class RouteResponse(Model):
    schema_version: Literal['1.4.0'] = '1.4.0'
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    origin: str
    destination: str
    departure_time: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: Literal['demo', 'mongo']
    assumptions: dict
    routes: list[Route]
    unavailable_strategies: list[dict]
    overlays: dict
    wave_grid: dict | None = None
    sources: list[dict]
    notices: list[str] = Field(default_factory=list)
    metadata: ReportMetadata


class RouteError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
