import asyncio
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
import pytest

from scripts.ingest_compliance import parse_records
from service.compliance import ComplianceService, shared_context
from service.compliance_agents import PROMPTS, AgentRunner
from service.compliance_calculations import calculate_compliance
from service.compliance_data import applicable, official_url
from service.compliance_models import ChatRequest, VoyageAnalysisRequest
from service.config import Settings
from service.documents import extract_document
from service.report_context import direct_context, read_report

NOW = datetime.now(UTC)


def config(**values):
    return Settings(_env_file=None, tideline_mode='demo', gemini_api_key='test-only', **values)


def report():
    return {'origin': 'NLRTM', 'destination': 'SGSIN', 'departureTime': NOW.isoformat(),
        'routes': [{'id': 'r1', 'eta': (NOW + timedelta(days=10)).isoformat(),
            'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [2, 0]]},
            'segments': [{'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [2, 0]]},
                'entryTime': NOW.isoformat(), 'exitTime': (NOW + timedelta(hours=2)).isoformat(), 'fuelTonnes': 10}],
            'emissions': {'co2Tonnes': 100}}], 'waveGrid': {'values': [[[1.2, 3.4], [None, 5.6]]]},
        'metadata': {'complianceHandoff': {'declaredContext': {'vessel': {'imoNumber': '1234567'}}}},
        'overlays': {'custom': 'retained'}, 'sources': [{'snapshotId': 'source-original'}]}


def output(category='security', **changes):
    finding = {'category': category, 'severity': 'red', 'status': 'confirmed', 'title': 'Example finding',
        'explanation': 'A test official passage supports this finding.', 'scope': {'routeIds': ['r1'],
        'portRoles': ['arrival'], 'portIds': ['FAKE1']}, 'evidenceIds': ['official-1']}
    finding.update(changes)
    return {'status': 'completed', 'summary': 'Test result', 'findings': [finding], 'webEvidence': []}


def interaction(value):
    return {'status': 'completed', 'steps': [{'type': 'model_output', 'content': [
        {'type': 'text', 'text': json.dumps(value), 'annotations': []}]}]}


def evidence():
    return {'id': 'official-1', 'title': 'Official test source', 'url': 'https://www.imo.org/test',
        'retrievedAt': NOW.isoformat(), 'supportingPassage': 'A test official passage.',
        'authority': 'official', 'category': 'security'}


def test_compact_brief_keeps_alternatives_and_full_report_remains_readable():
    original = report(); context = shared_context(original, 'Full cargo text')
    direct = direct_context(context)
    assert context['routeReport'] is original
    assert [r['id'] for r in direct['routeReport']['routes']] == ['r1']
    assert 'waveGrid' not in direct['routeReport']
    assert 'segments' not in direct['routeReport']['routes'][0]
    assert direct['routeReport']['routes'][0]['emissions'] == original['routes'][0]['emissions']
    assert direct['routeReport']['routes'][0]['details']['segmentsPath'] == '/routes/0/segments'
    assert direct['routeReport']['detailAccess']['availableThrough'] == 'read_route_report'
    assert read_report(original, '/routes/0/geometry')['values']['coordinates'] == [[0, 0], [2, 0]]
    assert read_report(original, '/routes/0/segments')['values'] == original['routes'][0]['segments']
    assert read_report(original, '/waveGrid/values/0/0')['values'] == [1.2, 3.4]
    assert read_report(original, '/waveGrid/values/0/1/0')['value'] is None
    assert 'error' in read_report(original, '/does-not-exist')
    assert 'error' in read_report(original, '/routes', limit=1000)


def test_brief_supplies_full_cargo_once_and_preserves_separate_document_text():
    references = [{'id': 'page1', 'title': 'Cargo', 'page': 1, 'text': 'UN1993'},
                  {'id': 'page2', 'title': 'Other', 'page': 2, 'text': 'Separate specifications'}]
    brief = direct_context(shared_context(report(), 'Declared UN1993 cargo', references))
    assert brief['cargoText'] == 'Declared UN1993 cargo'
    assert brief['documentReferences'][0]['cargoTextStart'] == 9
    assert 'text' not in brief['documentReferences'][0]
    assert brief['documentReferences'][1]['text'] == 'Separate specifications'


def test_all_specialists_launch_concurrently_and_share_the_same_context():
    async def run():
        starts, observed = [], []
        ready = asyncio.Event()
        async def handler(request):
            body = json.loads(request.content)
            starts.append(body)
            if len(starts) == len(PROMPTS): ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            assert body['store'] is False
            assert body['generation_config']['thinking_level'] == 'low'
            assert body['generation_config']['max_output_tokens'] == 3072
            assert any(t.get('type') == 'google_search' for t in body['tools'])
            assert any(t.get('name') == 'read_route_report' for t in body['tools'])
            return httpx.Response(200, json=interaction({'status': 'needs_input', 'summary': 'Needs data',
                                                        'findings': [], 'webEvidence': []}))
        runner = AgentRunner(config(), httpx.MockTransport(handler))
        context = shared_context(report(), 'UN1993 declared cargo; do not omit this text')
        text = json.dumps(direct_context(context))
        result = await asyncio.gather(*(runner.assess(category, context, text, {}, {'costs': {}}) for category in PROMPTS))
        for body in starts:
            supplied = body['input'].split('COMPLETE_SHARED_CONTEXT\n')[1].split('\nSPECIALIST_EVIDENCE')[0]
            observed.append(json.loads(supplied))
        assert len(observed) == 5 and all(v == observed[0] for v in observed)
        assert all(r['contextSha256'] == context['contextSha256'] for r in result)
    asyncio.run(run())


def test_function_tool_can_read_original_wave_values_and_return_to_model():
    calls = []
    def handler(request):
        body = json.loads(request.content); calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={'status': 'requires_action', 'steps': [{'type': 'function_call',
                'name': 'read_route_report', 'id': 'call-1', 'arguments': {'path': '/waveGrid/values/0/0'}}]})
        assert 'tools' not in body
        tool_result = next(step for step in body['input'] if step['type'] == 'function_result')
        assert tool_result['call_id'] == 'call-1'
        assert json.loads(tool_result['result'][0]['text'])['values'] == [1.2, 3.4]
        return httpx.Response(200, json=interaction({'status': 'needs_input', 'summary': 'Checked original grid',
            'findings': [], 'webEvidence': []}))
    runner = AgentRunner(config(), httpx.MockTransport(handler))
    context = shared_context(report())
    result = asyncio.run(runner.assess('security', context, json.dumps(direct_context(context)), {}, {'costs': {}}))
    assert result['status'] == 'needs_input' and len(calls) == 2


def test_research_budget_reserves_the_last_round_for_a_concise_answer():
    requests = []
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        if len(requests) < 2:
            return httpx.Response(200, json={'status': 'requires_action', 'steps': [{'type': 'function_call',
                'name': 'read_route_report', 'id': f'call-{len(requests)}', 'arguments': {'path': '/origin'}}]})
        assert 'tools' not in body
        assert body['input'][-1]['type'] == 'user_input'
        return httpx.Response(200, json=interaction({'status': 'needs_input', 'summary': 'Need verified boundaries',
            'findings': [], 'webEvidence': []}))
    runner = AgentRunner(config(), httpx.MockTransport(handler))
    context = shared_context(report())
    result = asyncio.run(runner.assess('security', context, '{}', {}, {'costs': {}}))
    assert result['status'] == 'needs_input' and len(requests) == 2
    assert 'reason' not in result


def test_backend_maps_port_roles_and_discards_invented_costs():
    result_value = output(cost={'amount': 99999, 'currency': 'USD', 'basis': 'vessel_voyage', 'calculationId': 'invented'})
    runner = AgentRunner(config(), httpx.MockTransport(lambda _: httpx.Response(200, json=interaction(result_value))))
    context = shared_context(report())
    result = asyncio.run(runner.assess('security', context, json.dumps(direct_context(context)),
                                      {'evidence': [evidence()]}, {'costs': {}}))
    finding = result['findings'][0]
    assert finding['scope']['portIds'] == ['SGSIN']
    assert finding['cost'] is None and finding['evidence'][0]['id'] == 'official-1'


def test_published_boundary_screening_can_return_without_a_local_geometry_catalogue():
    runner = AgentRunner(config(), httpx.MockTransport(lambda _: httpx.Response(200, json=interaction(output()))))
    context = shared_context(report())
    result = asyncio.run(runner.assess('security', context, '{}', {'evidence': [evidence()]}, {'costs': {}}))
    assert result['status'] == 'completed'
    assert result['findings'][0]['status'] == 'estimated'
    assert result['coverageNotes'] and 'not a verified crossing' in result['coverageNotes'][0]


def test_missing_cargo_does_not_spend_a_dangerous_goods_research_call():
    def forbidden(_): raise AssertionError('Missing cargo cannot be recovered by research')
    runner = AgentRunner(config(), httpx.MockTransport(forbidden))
    context = shared_context(report())
    result = asyncio.run(runner.assess('dangerous_goods', context, '{}', {}, {'costs': {}}))
    assert result['status'] == 'needs_input' and result['seconds'] == 0 and not runner.calls


def test_sanctions_list_match_does_not_automatically_prove_voyage_prohibition():
    value = output(category='sanctions')
    source = evidence() | {'category': 'sanctions'}
    runner = AgentRunner(config(), httpx.MockTransport(lambda _: httpx.Response(200, json=interaction(value))))
    context = shared_context(report())
    result = asyncio.run(runner.assess('sanctions', context, '{}', {'evidence': [source]}, {'costs': {}}))
    assert result['findings'][0]['status'] == 'estimated'
    assert 'jurisdiction' in result['findings'][0]['missingInputs'][-1]


@pytest.mark.parametrize('change', ['no_evidence', 'guessed_evidence', 'other_route', 'other_category'])
def test_unsupported_findings_never_become_red_issues(change):
    value = output()
    if change == 'guessed_evidence': value['findings'][0]['evidenceIds'] = ['invented']
    if change == 'other_route': value['findings'][0]['scope']['routeIds'] = ['other']
    if change == 'other_category': value['findings'][0]['category'] = 'trade'
    runner = AgentRunner(config(), httpx.MockTransport(lambda _: httpx.Response(200, json=interaction(value))))
    context = shared_context(report())
    result = asyncio.run(runner.assess('security', context, '{}', {}, {'costs': {}}))
    assert all(f['severity'] == 'info' and f['status'] == 'unverified' for f in result['findings'])


def test_context_limit_fails_explicitly_without_silent_truncation_or_provider_call():
    def forbidden(_): raise AssertionError('must not call provider')
    runner = AgentRunner(config(compliance_max_context_bytes=10000), httpx.MockTransport(forbidden))
    context = shared_context(report(), 'x' * 30000)
    result = asyncio.run(runner.assess('security', context, json.dumps(direct_context(context)), {}, {'costs': {}}))
    assert result['reason'] == 'context_too_large'


def test_sources_and_effective_dates_are_checked():
    assert official_url('https://ofac.treasury.gov/sanctions-list-service', 'sanctions')
    assert not official_url('https://ofac.treasury.gov.evil.example/notice', 'sanctions')
    assert not official_url('http://www.imo.org/test')
    assert not applicable({'policyStatus': 'proposed'}, NOW)
    assert not applicable({'policyStatus': 'suspended'}, NOW)
    assert not applicable({'effectiveFrom': NOW + timedelta(days=1)}, NOW)
    assert not applicable({'effectiveTo': NOW}, NOW)


def test_zone_calculation_uses_actual_intersection_and_preserves_unknown_costs():
    zone = {'id': 'test', 'name': 'Test area', 'category': 'jwc', 'routeId': 'r1', 'reviewed': True,
        'geometry': {'type': 'Polygon', 'coordinates': [[[0, -1], [1, -1], [1, 1], [0, 1], [0, -1]]]}}
    result = calculate_compliance(shared_context(report()), {'zones': [zone]})
    encounter = result['zoneEncounters'][0]
    assert encounter['hours'] == pytest.approx(1, abs=.01)
    assert encounter['fuelTonnes'] == pytest.approx(5, abs=.01)
    assert result['costs'] == {}
    zone['reviewed'] = False
    assert not calculate_compliance(shared_context(report()), {'zones': [zone]})['zoneEncounters']


def test_tariff_uses_origin_value_currency_and_arrival_date():
    value = report(); value['metadata']['complianceHandoff']['declaredContext']['cargo'] = {
        'hsCodes': ['850760'], 'originCountryCode': 'CN', 'customsValue': 10000, 'currency': 'USD'}
    tariff = {'id': 'test', 'reviewed': True, 'rateType': 'ad_valorem', 'ratePercent': 7.5,
        'hsCode': '850760', 'originCountryCode': 'CN', 'destinationPortId': 'SGSIN', 'currency': 'USD'}
    result = calculate_compliance(shared_context(value), {'tariffs': [tariff]})
    assert next(iter(result['costs'].values()))['amount'] == 750
    tariff['effectiveTo'] = (NOW + timedelta(days=2)).isoformat()
    assert not calculate_compliance(shared_context(value), {'tariffs': [tariff]})['costs']


def test_port_fee_uses_declared_gt_and_effective_arrival_date():
    value = report(); value['metadata']['complianceHandoff']['declaredContext']['vessel']['grossTonnage'] = 30000
    fee = {'id': 'dues', 'reviewed': True, 'portId': 'SGSIN', 'feeBasis': 'per_gt', 'rate': .12,
           'currency': 'SGD', 'effectiveFrom': (NOW + timedelta(days=5)).isoformat()}
    costs = calculate_compliance(shared_context(value), {'fees': [fee]})['costs']
    charge = next(iter(costs.values()))
    assert charge['amount'] == 3600 and charge['basis'] == 'port_call' and charge['portIds'] == ['SGSIN']
    value['metadata']['complianceHandoff']['declaredContext']['vessel'].pop('grossTonnage')
    assert not calculate_compliance(shared_context(value), {'fees': [fee]})['costs']


def test_plain_and_docx_uploads_extract_text_without_persistence():
    result = extract_document('cargo.txt', b'Paint, machinery and batteries')
    assert result['text'] == 'Paint, machinery and batteries' and not result['stored']
    assert result['references'][0]['id'].startswith('upload:')
    data = BytesIO()
    with ZipFile(data, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="urn:word"><w:p><w:r><w:t>UN1993</w:t></w:r></w:p></w:document>')
    assert extract_document('cargo.docx', data.getvalue())['text'] == 'UN1993'
    with pytest.raises(ValueError): extract_document('cargo.exe', b'not supported')
    invalid = BytesIO()
    with ZipFile(invalid, 'w') as archive:
        archive.writestr('word/document.xml', '<invalid')
    with pytest.raises(ValueError, match='Unreadable'): extract_document('broken.docx', invalid.getvalue())


def test_historical_ofac_and_invalid_geometry_are_rejected_before_publication():
    with pytest.raises(ValueError, match='Historical'):
        parse_records('ofac_sdn', b'<dataset>Historical dataset includes removed designations</dataset>')
    with pytest.raises(ValueError):
        parse_records('zones', json.dumps([{'geometry': {'type': 'Point', 'coordinates': [0, 0]}}]).encode())


def test_uk_feed_deduplicates_aliases_and_preserves_imo():
    raw = b'Report Date: 24-Oct-2026\nUnique ID,Name 1,Name 2,IMO number\nSHIP1,Example,Ship,IMO1234567\nSHIP1,Alias,,1234567\n'
    rows = parse_records('uk_sanctions', raw)['sanctions_entities']
    assert len(rows) == 1 and rows[0]['imo'] == ['1234567'] and rows[0]['names'] == ['Example Ship', 'Alias']


def test_ofac_imo_prefixed_registration_identifier_is_not_lost():
    raw = b'<sdnList><sdnEntry><uid>1</uid><lastName>Example</lastName><sdnType>Vessel</sdnType><idList><id><idType>Vessel Registration Identification</idType><idNumber>IMO 1234567</idNumber></id></idList></sdnEntry></sdnList>'
    assert parse_records('ofac_sdn', raw)['sanctions_entities'][0]['imo'] == ['1234567']


def test_orchestrator_returns_routes_before_slow_agents_and_preserves_parallel_launch():
    async def run():
        gate, all_started = asyncio.Event(), asyncio.Event()
        starts = []
        class Runner:
            async def assess(self, category, context, text, data, calculations):
                starts.append(category)
                assert context['routeReport']['waveGrid'] == report()['waveGrid']
                if len(starts) == 5: all_started.set()
                await gate.wait()
                return {'category': category, 'status': 'needs_input', 'findings': [], 'summary': 'Needs data'}
        class Congestion:
            async def assess(self, body, route_context=None):
                if route_context is not None:
                    context = await route_context
                    assert len(context['report']['routes']) == 1
                    assert 'routeReport' in context['brief']
                return SimpleNamespace(assessments=[])
        service = ComplianceService(SimpleNamespace(settings=config()), config(), Congestion(), Runner())
        body = VoyageAnalysisRequest(route_request={'origin': 'NLRTM', 'destination': 'SGSIN'}, cargo_text='Full text')
        events = service.stream(body, lambda *_: report())
        assert (await anext(events))['type'] == 'started'
        assert (await anext(events))['type'] == 'route_report'
        assert len(starts) == 5  # Already dispatched before the browser receives the report.
        assert (await anext(events))['type'] == 'context_ready'
        collect = asyncio.create_task(anext(events))
        await asyncio.wait_for(all_started.wait(), 2)
        gate.set(); rest = [await collect] + [item async for item in events]
        assert len([e for e in rest if e['type'] == 'assessment']) == 6
        assert rest[-1]['type'] == 'complete'
        assert service.active == 0
    asyncio.run(run())


def test_expired_chat_context_does_not_return_another_voyage():
    service = ComplianceService(SimpleNamespace(settings=config()), config(), None)
    body = ChatRequest(analysis_id='missing', context_token='wrong', finding_id='unknown', question='Why?')
    result = asyncio.run(service.chat(body))
    assert result.status == 'unavailable' and 'expired' in result.answer


def test_input_gates_skip_dependent_research_without_provider_calls():
    requests = []
    runner = AgentRunner(config(), httpx.MockTransport(lambda request: requests.append(request)))
    value = report()
    value['metadata']['complianceHandoff']['declaredContext'] = None
    context = shared_context(value)
    async def run():
        for category in ['trade', 'sanctions', 'dangerous_goods']:
            result = await runner.assess(category, context, '{}', {}, {})
            assert result['status'] == 'needs_input' and result['findings'] == []
            assert result['summary'].startswith('Not run:')
    asyncio.run(run())
    assert requests == []


def test_optional_details_reuses_report_and_shares_manifest_and_imo_with_every_specialist():
    from service.compliance_models import VoyageDetailsRequest
    import time
    observed = []
    class Runner:
        async def assess(self, category, context, shared, data, calculations):
            observed.append((category, context, json.loads(shared)))
            await asyncio.sleep(0)
            return {'category': category, 'status': 'completed', 'findings': []}
    value = report()
    service = ComplianceService(SimpleNamespace(), config(), None, runner=Runner())
    data = {'zones': [], 'evidence': [], 'versions': {}}
    service.store.retrieve = lambda context: data.copy()
    service.contexts['test'] = {'context': shared_context(value), 'data': data, 'token': 'private',
        'expires': time.monotonic() + 100, 'findings': {}}
    body = VoyageDetailsRequest(analysis_id='test', context_token='private', cargo_text='UN1993 cleaning liquids',
        vessel={'imoNumber': '9876543'}, document_references=[{'id': 'd1', 'title': 'Manifest', 'text': 'UN1993'}])
    async def run():
        return [event async for event in service.stream_details(body)]
    events = asyncio.run(run())
    assert len(observed) == len(PROMPTS)
    for category, context, brief in observed:
        assert brief['cargoText'] == body.cargo_text
        assert brief['suppliedVesselInformation']['imoNumber'] == '9876543'
        assert context['routeReport']['waveGrid'] is value['waveGrid']
        assert brief['documentReferences'][0]['id'] == 'd1'
        assert 'waveGrid' not in brief['routeReport']
    assert events[0]['type'] == 'context_ready' and events[-1]['type'] == 'complete'
    assert all(e['type'] != 'route_report' for e in events)
    assert value['metadata']['complianceHandoff']['declaredContext']['vessel']['imoNumber'] == '1234567'
    body.context_token = 'wrong'
    assert asyncio.run(run())[0]['type'] == 'error'
    assert service.active == 0


def test_parallel_reference_batch_finishes_with_evidence_and_gracefully_limits_extra_reads():
    from threading import Barrier
    from service.compliance_agents import ResearchOutput
    barrier = Barrier(2, timeout=2)
    seen, requests = [], []
    def lookup(query):
        if query in ('0', '1'):
            barrier.wait()  # Sequential lookups would fail this rendezvous.
        seen.append(query)
        return [evidence() | {'id': 'source-' + query}]
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        assert body['generation_config']['thinking_level'] == 'low'
        assert body['generation_config']['max_output_tokens'] == 8192  # Checklist override stays intact.
        if len(requests) == 1:
            return httpx.Response(200, json={'status': 'requires_action', 'steps': [
                {'type': 'function_call', 'name': 'lookup_reference', 'id': 'call-' + str(i),
                 'arguments': {'query': str(i)}} for i in range(5)]})
        assert 'tools' not in body
        results = [s for s in body['input'] if s['type'] == 'function_result']
        assert [s['call_id'] for s in results] == ['call-' + str(i) for i in range(5)]
        assert 'budget reached' in json.loads(results[-1]['result'][0]['text'])['error']
        return httpx.Response(200, json=interaction({'status': 'needs_input', 'summary': 'Partial cited evidence',
            'findings': [], 'webEvidence': []}))
    runner = AgentRunner(config(), httpx.MockTransport(handler)); runner.reference_lookup = lookup
    extra = {'evidence': []}
    result, _ = asyncio.run(runner.invoke('Quick check', '{}', extra, ResearchOutput, max_output_tokens=8192))
    assert result.status == 'needs_input' and len(requests) == 2
    assert sorted(seen) == ['0', '1', '2', '3']
    assert [e['id'] for e in extra['evidence']] == ['source-' + str(i) for i in range(4)]


def test_chat_focuses_selected_route_and_rejects_an_unrelated_selection():
    from service.compliance_models import ComplianceFinding
    from service.compliance_agents import ChatResearchOutput
    finding = ComplianceFinding(category='security', status='needs_input', title='Scope test',
        explanation='Test finding', scope={'routeIds': ['r1'], 'portIds': ['NLRTM']})
    body = ChatRequest(analysis_id='test', context_token='test', finding_id='test', question='Explain', route_id='r1', finding=finding)
    runner = AgentRunner(config())
    calls = []
    async def invoke(prompt, brief, extra, schema, report):
        calls.append(extra['selectedRouteId'])
        return ChatResearchOutput(answer='No verified information.', evidence_ids=[], web_evidence=[]), set()
    runner.invoke = invoke
    async def run():
        await runner.chat(body, shared_context(report()), {}, trusted_finding=True)
        assert calls == ['r1']
        invalid = body.model_copy(update={'route_id': 'another-voyage'})
        result = await runner.chat(invalid, shared_context(report()), {}, trusted_finding=True)
        assert result.status == 'unavailable' and len(calls) == 1
    asyncio.run(run())


def test_disconnect_during_cleanup_releases_analysis_slot(monkeypatch):
    async def run():
        class Congestion:
            async def assess(self, *args, **kwargs):
                await asyncio.Event().wait()
        service = ComplianceService(SimpleNamespace(settings=config()), config(), Congestion())
        body = VoyageAnalysisRequest(route_request={'origin': 'NLRTM', 'destination': 'SGSIN'})
        events = service.stream(body, lambda *_: report())
        assert (await anext(events))['type'] == 'started'
        assert service.active == 1
        original_gather = asyncio.gather
        async def interrupted_cleanup(*tasks, **kwargs):
            await original_gather(*tasks, **kwargs)
            raise asyncio.CancelledError()
        monkeypatch.setattr(asyncio, 'gather', interrupted_cleanup)
        try:
            await events.aclose()
        except asyncio.CancelledError:
            pass
        assert service.active == 0
    asyncio.run(run())
