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
from service.demo_research import assessments as demo_assessments, enabled as demo_enabled
from service.compliance_models import CATEGORIES
from service.compliance_providers import fetch_voyage_apis
from service.congestion_models import CongestionRequest
from service.models import RouteError
from service.report_context import direct_context
from service.routing import calculate


def shared_context(report, cargo_text='', references=(), declared_context=None):
    # Retain the original for calculations and read-only tools; models get a brief.
    value = report.model_dump(mode='json', by_alias=True) if hasattr(report, 'model_dump') else report
    if declared_context is not None:
        declared_input = declared_context.model_dump(mode='json', by_alias=True) if hasattr(declared_context, 'model_dump') else declared_context
        value = {**value, 'metadata': {**value.get('metadata', {})}}
        value['metadata']['complianceHandoff'] = {**value['metadata'].get('complianceHandoff', {}),
            'declaredContext': declared_input}
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
            if self.congestion is not None: self.congestion.runner = self.runner
        self.active = 0
        # Two short-lived browser contexts, solely for read tools and chat. Never written to Mongo.
        self.contexts = OrderedDict()
        self.preview_reports = OrderedDict()

    def cache_preview(self, report):
        now = time.monotonic()
        self.preview_reports[report.report_id] = (now + 1800, report)
        self.preview_reports.move_to_end(report.report_id)
        while len(self.preview_reports) > 5:
            self.preview_reports.popitem(last=False)

    def get_preview(self, report_id, request):
        cached = self.preview_reports.get(report_id)
        if not cached or cached[0] < time.monotonic():
            self.preview_reports.pop(report_id, None)
            return None
        report = cached[1]
        if report.origin != request.origin or report.destination != request.destination:
            return None
        self.preview_reports.move_to_end(report_id)
        return report

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
        demo = demo_enabled(body)
        route_context = None
        try:
            # Start public-data acquisition/research at submission, alongside route calculation.
            route_context = asyncio.get_running_loop().create_future()
            congestion = None if demo else asyncio.create_task(self.congestion.assess(CongestionRequest(
                port_ids=[body.route_request.origin, body.route_request.destination]), route_context=route_context))
            preliminary = {'routeReport': {'origin': body.route_request.origin, 'destination': body.route_request.destination,
                'departureTime': (body.route_request.departure_time or datetime.now(UTC)).isoformat(),
                'routes': [], 'metadata': {'complianceHandoff': {'declaredContext':
                    body.route_request.compliance_context.model_dump(mode='json', by_alias=True)
                    if body.route_request.compliance_context else None}}}, 'cargoText': body.cargo_text,
                'suppliedVesselInformation': body.route_request.compliance_context.vessel.model_dump(mode='json', by_alias=True)
                    if body.route_request.compliance_context and body.route_request.compliance_context.vessel else None}
            sources = None if demo else asyncio.create_task(asyncio.to_thread(self.store.retrieve, preliminary))
            preview = self.get_preview(body.preview_report_id, body.route_request) if body.preview_report_id else None
            supplied_report = body.route_report or preview
            if supplied_report is None and body.preview_report_id and calculate_routes is calculate:
                # A preview may have been served by another container. Rebuild only
                # the analysis data, never the global wave-display texture.
                calculate_routes = lambda request, repository: calculate(request, repository, include_display=False)
            routes = asyncio.create_task(asyncio.sleep(0, result=supplied_report) if supplied_report is not None
                else asyncio.to_thread(calculate_routes, body.route_request, self.repository))
            apis = None if demo else asyncio.create_task(fetch_voyage_apis(body, self.store))
            tasks.extend(task for task in (congestion, sources, routes, apis) if task is not None)
            yield {'type': 'started', 'analysisId': analysis_id, 'categories': list(CATEGORIES)}
            while not routes.done():
                done, _ = await asyncio.wait([routes], timeout=10)
                if not done:
                    yield {'type': 'heartbeat', 'phase': 'routing', 'seconds': round(time.monotonic() - started, 1)}
            report = routes.result()
            context = shared_context(report, body.cargo_text, body.document_references,
                body.route_request.compliance_context)
            if demo:
                self.contexts[analysis_id] = {'context': context, 'data': {'evidence': []},
                    'token': context_token, 'findings': {}, 'checks': {}, 'demo_research': True,
                    'expires': time.monotonic() + 1800}
                while len(self.contexts) > 2:
                    self.contexts.popitem(last=False)
                if supplied_report is None:
                    yield {'type': 'route_report', 'analysisId': analysis_id, 'report': context['routeReport']}
                yield {'type': 'context_ready', 'analysisId': analysis_id, 'contextToken': context_token,
                       'contextSha256': context['contextSha256'], 'demo': True,
                       'coverage': {'demoResearch': 'synthetic_not_verified'}}
                for result in demo_assessments(context['routeReport'], context['contextSha256']):
                    self.record_assessment(self.contexts[analysis_id], result)
                    yield {'type': 'assessment', **result}
                yield {'type': 'complete', 'analysisId': analysis_id,
                       'seconds': round(time.monotonic() - started, 3)}
                return
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
                route_context.set_result({'brief': direct_context(context), 'report': context['routeReport']})
            self.contexts[analysis_id] = {'context': context, 'data': data, 'token': context_token,
                'findings': {}, 'checks': {}, 'expires': time.monotonic() + 1800}
            while len(self.contexts) > 2:
                self.contexts.popitem(last=False)

            async def specialist(category):
                return await self.runner.assess(category, context, shared_json, data, calculations)

            async def congestion_result():
                response = await congestion
                # Full common context is supplied to this final scoping stage too.
                known = any(a.level != 'unknown' for a in response.assessments)
                no_evidence = all(a.research_status == 'completed' for a in response.assessments) and not known
                return {'category': 'congestion', 'status': 'completed' if known else 'unavailable',
                    'reason': 'insufficient_recent_evidence' if no_evidence else None,
                    'summary': 'The current lookup completed but found no sufficiently recent cited congestion evidence.'
                        if no_evidence else 'Current port reporting; not a forecast for voyage arrival.',
                    'coverageNotes': [f"{a.port_name or a.port_id}: " + (' '.join(a.quality_notes) or
                        f"Research status: {a.research_status}.") for a in response.assessments],
                    'assessments': [a.model_dump(mode='json', by_alias=True) for a in response.assessments],
                    'findings': [], 'contextSha256': context['contextSha256']}


            pending = {asyncio.create_task(specialist(category)) for category in PROMPTS}
            pending.add(asyncio.create_task(congestion_result()))
            tasks.extend(pending)
            # Dispatch before transferring the large display report to the browser.
            await asyncio.sleep(0)
            if supplied_report is None:
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
                        self.record_assessment(self.contexts[analysis_id], result)
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
            # Release admission before cancellable cleanup: disconnect cancellation
            # must never leak a slot and permanently reject subsequent voyages.
            self.active -= 1
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_details(self, body):
        """Research optional declarations against the retained report; never reroute or retransmit its wave grid."""
        saved = self.contexts.get(body.analysis_id)
        if not saved or saved['expires'] <= time.monotonic() or not secrets.compare_digest(saved['token'], body.context_token):
            yield {'type': 'error', 'message': 'This voyage context expired. Calculate routes again.'}
            return
        if saved.get('demo_research'):
            vessel = body.vessel.model_dump(mode='json', by_alias=True) if body.vessel else None
            context = shared_context(saved['context']['routeReport'], body.cargo_text,
                                     body.document_references, {'vessel': vessel})
            saved.update(context=context, expires=time.monotonic() + 1800)
            yield {'type': 'context_ready', 'analysisId': body.analysis_id,
                   'contextToken': body.context_token, 'demo': True,
                   'contextSha256': context['contextSha256']}
            for result in demo_assessments(context['routeReport'], context['contextSha256'],
                                           body.cargo_text, body.document_references,
                                           body.vessel.imo_number if body.vessel else None):
                self.record_assessment(saved, result)
                yield {'type': 'assessment', **result}
            yield {'type': 'complete', 'analysisId': body.analysis_id}
            return
        if self.active >= self.settings.compliance_max_analyses or saved.get('updating'):
            yield {'type': 'error', 'message': 'Another analysis is running. Please try again shortly.'}
            return
        saved['updating'] = True
        self.active += 1
        tasks = []
        try:
            # Copy declaration containers only. Geometry/forecast arrays remain shared read-only.
            original = saved['context']['routeReport']
            metadata = dict(original.get('metadata', {}))
            handoff = dict(metadata.get('complianceHandoff', {}))
            declared = dict(handoff.get('declaredContext') or {})
            declared['vessel'] = body.vessel.model_dump(mode='json', by_alias=True) if body.vessel else None
            handoff['declaredContext'] = declared
            handoff['declarationStatus'] = 'user_provided_unverified' if body.vessel or body.cargo_text or body.document_references or declared.get('parties') else 'not_provided'
            handoff['declarationsUsedForRouting'] = False
            metadata['complianceHandoff'] = handoff
            context = shared_context(original | {'metadata': metadata}, body.cargo_text, body.document_references)
            try:
                data = await asyncio.to_thread(self.store.retrieve, context)
            except PyMongoError:
                data = {'evidence': [], 'coverage': {'mongo': {'fresh': False}}}
            # Reuse the geography work; only declared cargo/vessel retrieval changes.
            data['zones'] = saved['data'].get('zones', [])
            context['resolvedVesselInformation'] = data.get('vesselFacts', [])
            context.pop('contextSha256', None)
            shared = json.dumps(direct_context(context), separators=(',', ':'), ensure_ascii=False)
            context['contextSha256'] = hashlib.sha256(shared.encode()).hexdigest()
            shared = json.dumps(direct_context(context), separators=(',', ':'), ensure_ascii=False)
            saved.update(context=context, data=data, expires=time.monotonic() + 1800)
            saved['checks'] = {k: v for k, v in saved.get('checks', {}).items() if k == 'congestion'}
            saved['findings'] = {}
            calculations = calculate_compliance(context, data)
            tasks = [asyncio.create_task(self.runner.assess(category, context, shared, data, calculations)) for category in PROMPTS]
            yield {'type': 'context_ready', 'analysisId': body.analysis_id, 'contextToken': body.context_token,
                   'contextSha256': context['contextSha256'], 'contextBytes': len(shared.encode())}
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(pending, timeout=10, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    yield {'type': 'heartbeat', 'phase': 'compliance'}
                for task in done:
                    result = task.result()
                    self.record_assessment(saved, result)
                    yield {'type': 'assessment', **result}
            yield {'type': 'complete', 'analysisId': body.analysis_id}
        except (PyMongoError, ValueError, KeyError, TypeError, httpx.HTTPError):
            yield {'type': 'error', 'message': 'Optional-detail research could not complete. Please try again.'}
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            saved['updating'] = False
            self.active -= 1
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def record_assessment(saved, result):
        category = result['category']
        if category != 'congestion' and result.get('contextSha256') != saved['context']['contextSha256']:
            return  # A previous cargo declaration finished after a newer research run.
        saved.setdefault('checks', {})[category] = result
        saved['findings'] = {key: value for key, value in saved['findings'].items() if value['category'] != category}
        saved['findings'].update({f['id']: f for f in result.get('findings', [])})

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
