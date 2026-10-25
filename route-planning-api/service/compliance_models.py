"""Shared contracts: complete route reports in, cited and scoped findings out."""
from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from service.models import DeclaredVessel, Model, RouteRequest, RouteResponse

CATEGORIES = ('security', 'environment', 'trade', 'sanctions', 'dangerous_goods', 'congestion')
Category = Literal['security', 'environment', 'trade', 'sanctions', 'dangerous_goods', 'congestion']


class DocumentReference(Model):
    id: str = Field(max_length=100)
    title: str = Field(max_length=200)
    page: int | None = Field(default=None, ge=1)
    text: str = Field(max_length=100000)


class VoyageAnalysisRequest(Model):
    route_request: RouteRequest
    demo_research: bool = False
    route_report: RouteResponse | None = None
    preview_report_id: str | None = Field(default=None, pattern=r'^[0-9a-f-]{36}$')
    cargo_text: str = Field(default='', max_length=200000)
    document_references: list[DocumentReference] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def report_matches_request(self):
        if self.route_report and (self.route_report.origin != self.route_request.origin or
                                  self.route_report.destination != self.route_request.destination):
            raise ValueError('The supplied route report must match the requested ports.')
        return self


class VoyageDetailsRequest(Model):
    analysis_id: str = Field(min_length=1, max_length=100)
    context_token: str = Field(min_length=1, max_length=100)
    cargo_text: str = Field(default='', max_length=200000)
    document_references: list[DocumentReference] = Field(default_factory=list, max_length=200)
    vessel: DeclaredVessel | None = None


class Evidence(Model):
    id: str
    title: str
    url: HttpUrl | None = None
    document_id: str | None = None
    download_path: str | None = Field(default=None, pattern=r'^/compliance/documents/[0-9a-f]{24}/download$')
    page_or_section: str | None = None
    supporting_passage: str = Field(default='', max_length=16000)
    retrieved_at: datetime
    published_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    source_version: str | None = None
    authority: Literal['official', 'user_document', 'unverified'] = 'unverified'


class Scope(Model):
    route_ids: list[str] = Field(default_factory=list, max_length=3)
    port_roles: list[Literal['departure', 'arrival']] = Field(default_factory=list, max_length=2)
    port_ids: list[str] = Field(default_factory=list, max_length=2)
    cargo_item_ids: list[str] = Field(default_factory=list, max_length=100)
    vessel_imo: str | None = None


class Cost(Model):
    amount: float = Field(ge=0, allow_inf_nan=False)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    basis: Literal['vessel_voyage', 'port_call', 'cargo_shipment', 'container_day']
    calculation_id: str
    assumptions: list[str] = Field(default_factory=list)


class ComplianceFinding(Model):
    id: str = ''
    demo: bool = False
    category: Category
    severity: Literal['info', 'yellow', 'red'] = 'info'
    status: Literal['confirmed', 'estimated', 'needs_input', 'unverified']
    title: str = Field(max_length=120)
    explanation: str = Field(max_length=1600)
    recommended_action: str = Field(default='', max_length=600)
    scope: Scope = Field(default_factory=Scope)
    cost: Cost | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    evidence: list[Evidence] = Field(default_factory=list, max_length=12)
    missing_inputs: list[str] = Field(default_factory=list, max_length=20)


class SpecialistOutput(Model):
    findings: list[ComplianceFinding] = Field(default_factory=list, max_length=8)
    status: Literal['completed', 'needs_input', 'unavailable', 'not_applicable']
    summary: str = Field(max_length=500)


class ChatRequest(Model):
    route_id: str | None = Field(default=None, max_length=100)
    route_report: RouteResponse | None = None
    analysis_id: str | None = Field(default=None, max_length=100)
    context_token: str | None = Field(default=None, max_length=100)
    finding_id: str | None = Field(default=None, max_length=100)
    cargo_text: str = Field(default='', max_length=200000)
    document_references: list[DocumentReference] = Field(default_factory=list, max_length=200)
    finding: ComplianceFinding | None = None
    question: str = Field(min_length=1, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def finding_belongs_to_report(self):
        if self.analysis_id and self.context_token and self.finding_id:
            return self
        if self.route_report is None or self.finding is None:
            raise ValueError('Supply an analysis ID/context token/finding ID, or a route report and finding.')
        ids = {r.id for r in self.route_report.routes}
        if set(self.finding.scope.route_ids) - ids:
            raise ValueError('The finding does not belong to this report.')
        return self


class ChatOutput(Model):
    answer: str = Field(max_length=7000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)


class ChatResponse(ChatOutput):
    evidence: list[Evidence] = Field(default_factory=list)
    status: Literal['completed', 'unavailable', 'needs_input']
