import asyncio
from typing import Literal

from pydantic import Field, model_validator

from service.models import Model, RouteError, RouteRequest
from service.routing import calculate


class RerouteRequest(Model):
    original: RouteRequest
    affected_port_id: str = Field(pattern=r'^[A-Z]{2}[A-Z0-9]{3}$')
    alternative_port_id: str = Field(pattern=r'^[A-Z]{2}[A-Z0-9]{3}$')
    strategy: Literal['fastest', 'economical', 'lowest_emissions'] = 'fastest'

    @model_validator(mode='after')
    def valid_endpoints(self):
        ports = (self.original.origin, self.original.destination)
        if self.affected_port_id not in ports or self.alternative_port_id in ports:
            raise ValueError('Replace one voyage endpoint with a different supported port.')
        return self


async def preview_reroute(body, repository, onward, calculator=calculate, cache_report=None):
    departure = body.affected_port_id == body.original.origin
    request = body.original.model_copy(update={('origin' if departure else 'destination'): body.alternative_port_id})
    # Independent routing call: no compliance swarm or replacement of the original voyage context.
    # Reuse the map's forecast display; calculate fresh sampled conditions for the alternative itself.
    report, transfer = await asyncio.gather(
        asyncio.to_thread(calculator, request, repository, include_display=False),
        onward.estimate(*( (body.affected_port_id, body.alternative_port_id) if departure
            else (body.alternative_port_id, body.affected_port_id))))
    route = next((route for route in report.routes if route.strategy == body.strategy), None)
    if route is None: raise RouteError('alternative_unavailable', 'No alternative was found for this routing objective.', 422)
    if cache_report:
        cache_report(report)
    return {'route': route.model_dump(mode='json', by_alias=True),
        'routes': [candidate.model_dump(mode='json', by_alias=True) for candidate in report.routes],
        'reportId': report.report_id,
        'departureTime': report.departure_time.isoformat(),
        'origin': report.origin, 'destination': report.destination,
        'ports': {role: port.model_dump(mode='json', by_alias=True) for role, port in report.metadata.ports.items()}, 'onwardTransport': transfer,
        'affectedPortId': body.affected_port_id, 'alternativePortId': body.alternative_port_id,
        'transferRole': 'pre_carriage' if departure else 'onward_delivery',
        'complianceStatus': 'not_assessed',
        'notice': 'Alternative sea route plus a separate per-container transfer scenario. Original compliance results do not clear the alternative. Terminal suitability and transfer arrangements need confirmation.'}
