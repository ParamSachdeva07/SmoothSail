"""Small, public-data-only contract for port congestion screening."""
from typing import Annotated, Literal
from datetime import UTC, datetime

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from service.models import Model

PortId = Annotated[str, Field(pattern=r'^[A-Z]{2}[A-Z0-9]{3}$')]
Level = Literal['low', 'mild', 'high', 'unknown']


def dated_fields(data, fields):
    """Public reports often give a calendar date, without a timezone or exact observation hour.

    Preserve that precision explicitly and use start-of-day UTC only for conservative expiry.
    Never treat a date-only report as a precise live observation.
    """
    if not isinstance(data, dict): return data
    data = dict(data)
    for field in fields:
        value = data.get(field)
        if not isinstance(value, str): continue
        try: parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError: continue
        if parsed.tzinfo is None:
            data[field] = datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)
            data['datePrecision'] = 'day'
    return data


class Source(Model):
    title: str = Field(max_length=160)
    url: HttpUrl
    observed_at: AwareDatetime | None = None
    published_at: AwareDatetime | None = None
    supporting_passage: str = Field(default='', max_length=700)
    scope: Literal['port', 'terminal'] = 'port'
    date_precision: Literal['day', 'timestamp'] = 'timestamp'

    @model_validator(mode='before')
    @classmethod
    def normalize_report_dates(cls, data):
        return dated_fields(data, ('observedAt', 'publishedAt', 'observed_at', 'published_at'))


class KnownFact(Model):
    """Caller-provided public evidence, never trusted as an instruction."""
    statement: str = Field(min_length=1, max_length=500)
    source: Source


class CongestionRequest(Model):
    port_ids: list[PortId] = Field(min_length=1, max_length=2)
    known_data: dict[PortId, list[KnownFact]] = Field(default_factory=dict, max_length=2)

    @model_validator(mode='after')
    def bounded_input(self):
        if len(set(self.port_ids)) != len(self.port_ids):
            raise ValueError('Port identifiers must be distinct.')
        if set(self.known_data) - set(self.port_ids) or any(len(v) > 4 for v in self.known_data.values()):
            raise ValueError('Supply at most four facts for each requested port.')
        return self


class Alternative(Model):
    port_id: PortId
    name: str = Field(max_length=100)
    reason: str = Field(max_length=400)
    congestion_level: Level = 'unknown'
    source: Source | None = None
    distance_nm: float | None = Field(default=None, ge=0)
    selection_basis: Literal['nearest_supported_port'] = 'nearest_supported_port'
    status: Literal['candidate'] = 'candidate'
    onward_transport: dict | None = None


class ResearchFinding(Model):
    port_id: PortId
    level: Level
    basis: Literal['reported', 'measured', 'unknown']
    confidence: Literal['low', 'medium', 'high']
    summary: str = Field(max_length=600)
    evidence_as_of: AwareDatetime | None
    date_precision: Literal['day', 'timestamp'] = 'timestamp'

    @model_validator(mode='before')
    @classmethod
    def normalize_evidence_date(cls, data):
        return dated_fields(data, ('evidenceAsOf', 'evidence_as_of'))

    sources: list[Source] = Field(max_length=3)


class Finding(ResearchFinding):
    alternative_port: Alternative | None = None


class ResearchOutput(Model):
    assessments: list[ResearchFinding] = Field(max_length=2)


class Display(Model):
    show_badge: bool = False
    color: Literal['yellow', 'red'] | None = None
    label: str = 'issue'


class Assessment(Finding):
    port_name: str = ''
    checked_at: AwareDatetime
    refresh_after: AwareDatetime
    method_version: str = 'port-agent-v5'
    evidence_window_hours: int = 72
    research_status: Literal['completed', 'not_configured', 'timeout', 'unavailable', 'busy', 'budget_limited']
    quality_notes: list[str] = Field(default_factory=list)
    display: Display = Field(default_factory=Display)
    cached: bool = False
    # Provider search metadata; the frontend displays source citations, not suggestion widgets.
    search_suggestions: list[str] = Field(default_factory=list)


class CongestionResponse(Model):
    assessments: list[Assessment]
    model: str
