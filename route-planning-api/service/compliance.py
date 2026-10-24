"""Request-scoped orchestration. No saved voyages, job queue, or polling."""
import asyncio
import hashlib
import json
import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from pymongo.errors import PyMongoError

from service.compliance_agents import PROMPTS, AgentRunner
from service.compliance_calculations import calculate_compliance
from service.compliance_data import ComplianceStore
from service.compliance_models import CATEGORIES
from service.compliance_providers import fetch_voyage_apis
from service.congestion_models import CongestionRequest
from service.models import RouteError
from service.report_context import direct_context
from service.routing import calculate


def shared_context(report, cargo_text='', references=()):
    # Retain the original for calculations and read-only tools; models get a brief.
    value = report.model_dump(mode='json', by_alias=True) if hasattr(report, 'model_dump') else report
    declared = value.get('metadata', {}).get('complianceHandoff', {}).get('declaredContext') or {}
    context = {'routeReport': value, 'cargoText': cargo_text,
        'documentReferences': [r.model_dump(mode='json', by_alias=True) if hasattr(r, 'model_dump') else r for r in references],
        'suppliedVesselInformation': declared.get('vessel'), 'resolvedVesselInformation': [],
        'suppliedParties': declared.get('parties', []), 'checkedAt': datetime.now(UTC).isoformat()}
    context['contextSha256'] = hashlib.sha256(json.dumps(direct_context(context), sort_keys=True).encode()).hexdigest()
    return context


class ComplianceService:
    def __init__(self, repository, settings, congestion, runner=None):
        self.repository, self.settings, self.congestion = repository, settings, congestion
        self.store = ComplianceStore(repository)
        self.runner = runner or AgentRunner(settings)
        if isinstance(self.runner, AgentRunner):
            self.runner.reference_lookup = self.store.search_references
        self.active = 0
        # Two short-lived browser contexts, solely for read tools and chat. Never written to Mongo.
        self.contexts = OrderedDict()

    async def stream(self, body, calculate_routes=None):
        if self.active >= self.settings.compliance_max_analyses:
            yield {'type': 'error', 'code': 'busy', 'message': 'Another analysis is running. Please try again shortly.'}
            return
        self.active += 1
        tasks = []
        started = time.monotonic()
        analysis_id = str(uuid4())
        context_token = secrets.token_urlsafe(32)
        calculate_routes = calculate_routes or calculate
        route_context = None
        try:
            # Start public-data acquisition/research at submission, alongside route calculation.
            route_context = asyncio.get_running_loop().create_future()
            congestion = asyncio.create_task(self.congestion.assess(CongestionRequest(
                port_ids=[body.route_request.origin, body.route_request.destination]), route_context=route_context))
            preliminary = {'routeReport': {'origin': body.route_request.origin, 'destination': body.route_request.destination,
                'departureTime': (body.route_request.departure_time or datetime.now(UTC)).isoformat(),
                'routes': [], 'metadata': {'complianceHandoff': {'declaredContext':
                    body.route_request.compliance_context.model_dump(mode='json', by_alias=True)
                    if body.route_request.compliance_context else None}}}, 'cargoText': body.cargo_text,
                'suppliedVesselInformation': body.route_request.compliance_context.vessel.model_dump(mode='json', by_alias=True)
                    if body.route_request.compliance_context and body.route_request.compliance_context.vessel else None}
            sources = asyncio.create_task(asyncio.to_thread(self.store.retrieve, preliminary))
            routes = asyncio.create_task(asyncio.to_thread(calculate_routes, body.route_request, self.repository))
            apis = asyncio.create_task(fetch_voyage_apis(body, self.store))
            tasks.extend([congestion, sources, routes, apis])
            yield {'type': 'started', 'analysisId': analysis_id, 'categories': list(CATEGORIES)}
            while not routes.done():
                done, _ = await asyncio.wait([routes], timeout=10)
                if not done:
                    yield {'type': 'heartbeat', 'phase': 'routing', 'seconds': round(time.monotonic() - started, 1)}
            report = routes.result()
            context = shared_context(report, body.cargo_text, body.document_references)
            try:
                data = await sources
                data['zones'] = await asyncio.to_thread(self.store.route_zones, context['routeReport'], data)
                for item in await apis:
                    data['evidence'].append(item['evidence'] | {'category': 'trade'})
            except PyMongoError:
                data = {'evidence': [], 'zones': [], 'entities': [], 'rules': [], 'tariffs': [], 'fees': [],
                        'vesselFacts': [], 'versions': {}, 'coverage': {'mongo': {'fresh': False}}}
            context['resolvedVesselInformation'] = data.get('vesselFacts', [])
            # Fingerprint the shared brief without serializing the 45 MB display grid.
            context.pop('contextSha256', None)
            context['contextSha256'] = hashlib.sha256(json.dumps(direct_context(context), sort_keys=True).encode()).hexdigest()
            shared_json = json.dumps(direct_context(context), separators=(',', ':'), ensure_ascii=False)
            calculations = calculate_compliance(context, data)
            if not route_context.done():
                route_context.set_result(direct_context(context))
            self.contexts[analysis_id] = {'context': context, 'data': data, 'token': context_token,
                'findings': {}, 'expires': time.monotonic() + 1800}
            while len(self.contexts) > 2:
                self.contexts.popitem(last=False)

            async def specialist(category):
                return await self.runner.assess(category, context, shared_json, data, calculations)

            async def congestion_result():
                response = await congestion
                # Full common context is supplied to this final scoping stage too.
                return {'category': 'congestion', 'status': 'completed' if any(
                    a.level != 'unknown' for a in response.assessments) else 'unavailable',
                    'summary': 'Current port reporting; not a forecast for voyage arrival.',
                    'assessments': [a.model_dump(mode='json', by_alias=True) for a in response.assessments],
                    'findings': [], 'contextSha256': context['contextSha256']}

            pending = {asyncio.create_task(specialist(category)) for category in PROMPTS}
            pending.add(asyncio.create_task(congestion_result()))
            tasks.extend(pending)
            # Dispatch before transferring the large display report to the browser.
            await asyncio.sleep(0)
            yield {'type': 'route_report', 'analysisId': analysis_id, 'report': context['routeReport']}
            yield {'type': 'context_ready', 'contextSha256': context['contextSha256'],
                   'contextBytes': len(shared_json.encode()), 'sourceVersions': data.get('versions', {}),
                   'coverage': data.get('coverage', {}), 'analysisId': analysis_id, 'contextToken': context_token}
            while pending:
                done, pending = await asyncio.wait(pending, timeout=10, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    yield {'type': 'heartbeat', 'phase': 'compliance', 'seconds': round(time.monotonic() - started, 1)}
                for task in done:
                    result = task.result()
                    if analysis_id in self.contexts:
                        self.contexts[analysis_id]['findings'].update({f['id']: f for f in result.get('findings', [])})
                    yield {'type': 'assessment', **result}
            yield {'type': 'complete', 'analysisId': analysis_id, 'seconds': round(time.monotonic() - started, 3)}
        except asyncio.CancelledError:
            raise
        except (RouteError, PyMongoError, ValueError, KeyError, TypeError, httpx.HTTPError) as error:
            yield {'type': 'error', 'code': error.code if isinstance(error, RouteError) else 'analysis_unavailable',
                   'message': error.message if isinstance(error, RouteError) else 'The analysis could not complete.'}
        finally:
            if route_context is not None and not route_context.done():
                route_context.cancel()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.active -= 1

    async def chat(self, body):
        if body.analysis_id:
            from service.compliance_models import ChatResponse, ComplianceFinding
            saved = self.contexts.get(body.analysis_id)
            if not saved or saved['expires'] <= time.monotonic() or not secrets.compare_digest(
                    saved['token'], body.context_token or '') or body.finding_id not in saved['findings']:
                return ChatResponse(answer='This temporary analysis context has expired. Calculate routes again to continue research.',
                                    evidence_ids=[], evidence=[], status='unavailable')
            body = body.model_copy(update={'finding': ComplianceFinding.model_validate(saved['findings'][body.finding_id])})
            return await self.runner.chat(body, saved['context'], saved['data'], trusted_finding=True)
        context = shared_context(body.route_report, body.cargo_text, body.document_references)
        try:
            data = await asyncio.to_thread(self.store.retrieve, context)
        except PyMongoError:
            data = {'evidence': []}
        context['resolvedVesselInformation'] = data.get('vesselFacts', [])
        return await self.runner.chat(body, context, data)
