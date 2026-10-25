import asyncio
import time
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from service.checklist import (ChecklistRequest, ChecklistExportRequest, DocumentResearch, compile_checklist,
    resolve_documents, generate, export_snapshot)
from service.checklist_pdf import render_pdf
from service.compliance import ComplianceService
from service.main import app
from service.models import RouteError

EVIDENCE = {'id': 'e1', 'title': 'Official source', 'url': 'https://www.imo.org/',
            'authority': 'official', 'retrievedAt': '2026-10-25T00:00:00Z', 'supportingPassage': 'Supporting source text.'}


def saved_context():
    findings = [{'id': f'f{i}', 'category': category, 'title': f'Issue {i}', 'recommendedAction': f'Original action {i}: confirm <data> & supporting evidence.',
        'explanation': 'A voyage-specific explanation.', 'status': 'confirmed', 'scope': {'routeIds': ['r1'], 'portIds': ['NLRTM']},
        'missingInputs': ['Cargo identity'], 'evidence': [EVIDENCE]} for i, category in enumerate(('security', 'environment', 'trade'))]
    context = {'contextSha256': 'sha', 'checkedAt': '2026-10-25T00:00:00Z', 'routeReport': {
        'origin': 'NLRTM', 'destination': 'SGSIN', 'departureTime': '2026-10-26T00:00:00Z',
        'routes': [{'id': 'r1', 'strategy': 'fastest', 'eta': '2026-11-01T00:00:00Z'}, {'id': 'r2', 'strategy': 'economical'}]}}
    return {'context': context, 'data': {'evidence': []}, 'findings': {f['id']: f for f in findings}, 'checks': {
        f['category']: {'category': f['category'], 'status': 'completed', 'summary': 'Research returned.', 'findings': [f]} for f in findings},
        'token': 'capability', 'expires': time.monotonic() + 1800}


def body(**kw):
    return ChecklistRequest(analysisId='analysis', contextToken='capability', routeId='r1', **kw)


class Runner:
    calls = 0
    fail = False
    async def invoke(self, prompt, shared, extra, schema, report=None, max_output_tokens=4096):
        self.calls += 1
        await asyncio.sleep(.01)
        if self.fail: raise ValueError('provider unavailable')
        return DocumentResearch(documents=[{'title': 'Supporting declaration', 'purpose': 'Document the verified facts.',
            'applicability': 'required', 'actionIds': [extra['actions'][0]['id']], 'evidenceIds': ['e1'],
            'provider': 'Cargo owner', 'timing': 'Confirm with authority'}]), set()
    async def web_evidence(self, *args): return []


def service():
    return SimpleNamespace(contexts={'analysis': saved_context()}, runner=Runner())


def test_actions_preserved_and_selected_route_scope_with_coverage():
    saved = saved_context()
    snapshot = compile_checklist(saved, 'r1')
    assert len(snapshot['actions']) == 3
    assert snapshot['actions'][0]['action'] == saved['findings']['f0']['recommendedAction']
    assert snapshot['actions'][0]['missingInputs'] == ['Cargo identity']
    assert snapshot['partial'] and len(snapshot['coverage']) == 6
    assert not compile_checklist(saved, 'r2')['actions']
    saved['checks']['congestion'] = {'status': 'completed', 'assessments': [{'portId': 'NLRTM', 'portName': 'Rotterdam',
        'level': 'high', 'summary': 'Busy terminal.', 'sources': []}]}
    followup = compile_checklist(saved, 'r1')['actions'][-1]
    assert followup['origin'] == 'operational_follow_up' and followup['portIds'] == ['NLRTM']


def test_documents_reject_unknown_ids_and_downgrade_unverified_requirements():
    actions = compile_checklist(saved_context(), 'r1')['actions']
    output = DocumentResearch(documents=[
        {'title': 'Forged', 'purpose': 'Bad scope', 'applicability': 'required', 'actionIds': ['invented']},
        {'title': 'Unsourced', 'purpose': 'Check', 'applicability': 'required', 'actionIds': [actions[0]['id']], 'evidenceIds': ['invented']},
        {'title': 'Sourced', 'purpose': 'Check', 'applicability': 'required', 'actionIds': [actions[1]['id']], 'evidenceIds': ['e1']}])
    actions[1]['status'] = 'needs_input'
    result = resolve_documents(output, {'e1': EVIDENCE}, actions)
    assert len(result) == 2
    assert [d['applicability'] for d in result] == ['to_verify', 'conditional']
    assert result[0]['portIds'] == ['NLRTM']


def test_concurrent_requests_deduplicate_and_new_findings_invalidate_cache():
    async def run():
        svc = service()
        first, second = await asyncio.gather(generate(svc, body()), generate(svc, body()))
        assert first == second and svc.runner.calls == 1
        assert first['documents'][0]['applicability'] == 'required'
        assert await generate(svc, body()) == first and svc.runner.calls == 1
        svc.contexts['analysis']['checks']['security']['findings'][0]['recommendedAction'] = 'New action'
        third = await generate(svc, body())
        assert third['id'] != first['id'] and svc.runner.calls == 2
    asyncio.run(run())


def test_agent_failure_preserves_actions_export_and_allows_retry():
    async def run():
        svc = service(); svc.runner.fail = True
        result = await generate(svc, body())
        assert len(result['actions']) == 3 and result['researchStatus'] == 'unavailable'
        export = ChecklistExportRequest(**body().model_dump(), checklistId=result['id'])
        assert export_snapshot(svc, export) == result
        svc.runner.fail = False
        assert (await generate(svc, body()))['researchStatus'] == 'completed'
    asyncio.run(run())


def test_capability_route_and_export_item_validation():
    async def run():
        svc = service()
        for values in ({'context_token': 'wrong'}, {'route_id': 'foreign'}):
            with pytest.raises(RouteError): await generate(svc, body().model_copy(update=values))
        result = await generate(svc, body())
        with pytest.raises(RouteError):
            export_snapshot(svc, ChecklistExportRequest(**body().model_dump(), checklistId=result['id'], checkedItemIds=['forged']))
        svc.contexts['analysis']['expires'] = 0
        with pytest.raises(RouteError): await generate(svc, body())
    asyncio.run(run())


def test_new_declarations_ignore_stale_assessments():
    saved = saved_context()
    old = deepcopy(saved['checks']['trade']); old['contextSha256'] = 'old'
    ComplianceService.record_assessment(saved, old)
    assert saved['checks']['trade'] is not old
    fresh = old | {'contextSha256': 'sha', 'findings': []}
    ComplianceService.record_assessment(saved, fresh)
    assert not saved['checks']['trade']['findings'] and 'f2' not in saved['findings']


def test_pdf_multipage_preserves_actions_notes_status_and_links():
    snapshot = asyncio.run(generate(service(), body()))
    snapshot['actions'] *= 5
    item = snapshot['actions'][0]
    pdf = render_pdf(snapshot, [item['id']], {item['id']: 'Assigned to Jane <not markup> & owner.'})
    reader = PdfReader(BytesIO(pdf)); text = '\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages) >= 3
    assert text.count('Original action 0:') == 5
    assert 'Assigned to Jane <not markup> & owner.' in text
    assert '[X]' in text and 'PARTIAL SNAPSHOT' in text and 'Supporting declaration' in text
    assert any(a.get_object().get('/A', {}).get('/URI') == 'https://www.imo.org/' for p in reader.pages for a in p.get('/Annots', []))


def test_endpoints_return_pdf_and_reject_bad_capabilities(monkeypatch):
    svc = service(); monkeypatch.setattr(app.state, 'compliance', svc, raising=False)
    client = TestClient(app)
    request = body().model_dump(by_alias=True)
    created = client.post('/voyages/checklist', json=request)
    assert created.status_code == 200 and created.headers['cache-control'] == 'no-store'
    pdf = client.post('/voyages/checklist/pdf', json=request | {'checklistId': created.json()['id']})
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    assert 'attachment' in pdf.headers['content-disposition']
    assert client.post('/voyages/checklist', json=request | {'contextToken': 'forged'}).status_code == 410


def test_preview_returns_actions_without_model_call_and_is_not_exportable():
    async def run():
        svc = service()
        preview = await generate(svc, body(research=False))
        assert len(preview['actions']) == 3 and preview['researchStatus'] == 'researching'
        assert svc.runner.calls == 0
        with pytest.raises(RouteError):
            export_snapshot(svc, ChecklistExportRequest(**body().model_dump(), checklistId=preview['id']))
        ready = await generate(svc, body())
        assert ready['id'] == preview['id'] and svc.runner.calls == 1
    asyncio.run(run())


def test_pdf_consolidates_publication_sections_without_dumping_raw_page_text():
    snapshot = asyncio.run(generate(service(), body()))
    snapshot['actions'][1]['evidence'] = [EVIDENCE | {'id': 'e2', 'pageOrSection': 'Page 8',
        'supportingPassage': 'NAVIGATION_NOISE\n' * 100}]
    snapshot['actions'][0]['evidence'] = [EVIDENCE | {'pageOrSection': 'Page 2'}]
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(render_pdf(snapshot))).pages)
    assert 'Page 2, Page 8' in text
    assert 'NAVIGATION_NOISE' not in text
    assert text.count('[1] Official source') == 1


def test_unofficial_document_evidence_cannot_imply_verified_requirement():
    actions = compile_checklist(saved_context(), 'r1')['actions']
    output = DocumentResearch(documents=[{'title': 'Suggested form', 'purpose': 'Check applicability',
        'applicability': 'conditional', 'actionIds': [actions[0]['id']], 'evidenceIds': ['e1']}])
    assert resolve_documents(output, {'e1': EVIDENCE | {'authority': 'unverified'}}, actions)[0]['applicability'] == 'to_verify'


def test_document_timing_explanation_and_long_source_title_remain_exportable():
    actions = compile_checklist(saved_context(), 'r1')['actions']
    timing = 'Confirm the applicable voyage reporting and retention periods with the issuer. ' * 8
    output = DocumentResearch(documents=[{'title': 'Voyage supporting records', 'purpose': 'Keep supporting evidence.',
        'applicability': 'conditional', 'actionIds': [actions[0]['id']], 'timing': timing, 'evidenceIds': ['e1']}])
    docs = resolve_documents(output, {'e1': EVIDENCE | {'title': 'Official reference publication ' * 15}}, actions)
    assert docs[0]['timing'] == timing
    snapshot = compile_checklist(saved_context(), 'r1') | {'id': 'checklist-long',
        'generatedAt': '2026-10-25T00:00:00Z', 'documents': docs}
    request = ChecklistExportRequest(**body().model_dump(), checklistId=snapshot['id'], snapshot=displayed_snapshot(snapshot))
    assert export_snapshot(SimpleNamespace(contexts={}), request)['documents'][0]['timing'] == timing


def displayed_snapshot(snapshot):
    """The compact display contract sent by the browser, without raw reference passages/geometry."""
    result = deepcopy(snapshot)
    result.pop('notice')
    result['route'] = {k: v for k, v in result['route'].items() if k in ('strategy', 'eta')}
    result['actions'] = [{k: v for k, v in item.items() if k not in ('findingIds', 'severity')} for item in result['actions']]
    for item in result['actions'] + result['documents']:
        for evidence in item.get('evidence', []): evidence.pop('supportingPassage', None)
    return result


def test_pdf_exports_displayed_snapshot_after_backend_restart_without_research_or_db(monkeypatch):
    snapshot = asyncio.run(generate(service(), body()))
    monkeypatch.setattr(app.state, 'compliance', SimpleNamespace(contexts={}), raising=False)
    request = body().model_dump(by_alias=True) | {'checklistId': snapshot['id'],
        'snapshot': displayed_snapshot(snapshot),
        'checkedItemIds': [a['id'] for a in snapshot['actions']] + [d['id'] for d in snapshot['documents']],
        'itemNotes': {snapshot['actions'][0]['id']: 'All selected after research expiry'}}
    client = TestClient(app)
    response = client.post('/voyages/checklist/pdf', json=request)
    assert response.status_code == 200 and response.content.startswith(b'%PDF')
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(response.content)).pages)
    assert '4 checked / 4 items' in text
    assert 'All selected after research expiry' in text
    assert 'does not revalidate' in text
    assert 'Supporting declaration' in text
    legacy = {k: v for k, v in request.items() if k != 'snapshot'}
    assert client.post('/voyages/checklist/pdf', json=legacy).status_code == 410
    assert client.post('/voyages/checklist/pdf', json=request | {'checkedItemIds': ['foreign']}).status_code == 422
    assert client.post('/voyages/checklist/pdf', json=request | {'routeId': 'foreign'}).status_code == 422


def test_display_export_rejects_unbounded_or_inconsistent_payloads(monkeypatch):
    snapshot = asyncio.run(generate(service(), body()))
    monkeypatch.setattr(app.state, 'compliance', SimpleNamespace(contexts={}), raising=False)
    request = body().model_dump(by_alias=True) | {'checklistId': snapshot['id'], 'snapshot': displayed_snapshot(snapshot)}
    client = TestClient(app)
    bad = deepcopy(request)
    bad['snapshot']['documents'][0]['actionIds'] = ['not-in-checklist']
    assert client.post('/voyages/checklist/pdf', json=bad).status_code == 422
    bad = deepcopy(request)
    bad['snapshot']['actions'][0]['action'] = 'x' * 2001
    assert client.post('/voyages/checklist/pdf', json=bad).status_code == 422
    bad = deepcopy(request)
    bad['snapshot']['actions'][0]['evidence'][0]['url'] = 'javascript:alert(1)'
    assert client.post('/voyages/checklist/pdf', json=bad).status_code == 422


def test_curator_brief_is_selected_route_only_and_retains_actions():
    import json
    instance = service()
    class CapturingRunner(Runner):
        async def invoke(self, prompt, shared, extra, schema, **kwargs):
            brief = json.loads(shared)
            assert [r['id'] for r in brief['routeReport']['routes']] == ['r1']
            assert len(extra['actions']) == 3
            assert kwargs['max_output_tokens'] == 3072
            assert len(kwargs['report']['routes']) == 2
            return await super().invoke(prompt, shared, extra, schema, **kwargs)
    instance.runner = CapturingRunner()
    result = asyncio.run(generate(instance, body()))
    assert result['researchStatus'] == 'completed'
    assert len(instance.contexts['analysis']['context']['routeReport']['routes']) == 2
