"""业务回归：临时数据库与HTTP模拟，不依赖真实模型额度。"""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from anxin.config import Settings
from anxin.domain import DEMO_INPUT, NeedFields, demo_fields
from anxin.main import create_app
from anxin.model_gateway import ModelFailure, extract_need


@pytest.fixture
def config(tmp_path):
    return Settings(database_path=str(tmp_path / 'test.db'), model_base_url='', model_name='', model_api_key='')


@pytest.fixture
def client(config):
    with TestClient(create_app(config)) as client:
        yield client


def create_demo(client):
    response = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'demo'})
    assert response.status_code == 201
    return response.json()


def patch(client, need, **changes):
    response = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'], 'fields': {**need['fields'], **changes},
    })
    assert response.status_code == 200, response.text
    return response.json()


def draft(client, need, include_demo=False):
    response = client.post(f"/api/needs/{need['id']}/plan-drafts", json={'expected_version': need['version'], 'include_demo': include_demo})
    assert response.status_code == 201, response.text
    return response.json()


def rule(plan, code):
    return next(r for r in plan['rules'] if r['code'] == code)


def test_health_has_no_secrets(client):
    result = client.get('/api/health').json()
    assert result['status'] == 'ok' and result['storage'] == 'ok'
    assert result['model_configured'] is False
    assert not any('key' in k or 'path' in k for k in result)


def test_demo_unknown_costs_and_candidate_acceptance(client):
    need = create_demo(client)
    assert need['extraction_status'] == 'demo'
    assert need['fields']['service_date'] == '2026-10-24'
    assert need['fields']['arrival_deadline'].startswith('09:00')
    assert need['fields']['travel_minutes'] is None
    assert need['fields']['acceptance_status'] == 'unknown'
    plan = draft(client, need)
    assert plan['status'] == 'needs_information'
    assert plan['budget']['known_subtotal'] is None
    assert plan['budget']['total'] is None
    assert rule(plan, 'budget')['status'] == 'unknown'
    assert rule(plan, 'availability')['status'] == 'unknown'
    assert rule(plan, 'dependencies')['status'] == 'pass'
    assert len(plan['tasks']) == 5
    assert all(t['status'] == 'draft' for t in plan['tasks'])


def test_missing_model_does_not_fabricate_extraction(client):
    result = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'model'}).json()
    assert result['extraction_status'] == 'not_configured'
    assert result['fields']['budget_limit'] is None
    assert client.get('/api/needs/' + result['id']).status_code == 200


def test_manual_flow_and_invalid_demo_reuse(client):
    manual = client.post('/api/needs', json={'raw_text': '明天希望安排午餐', 'mode': 'manual'}).json()
    assert manual['extraction_status'] == 'manual'
    assert manual['fields']['service_date'] is None
    assert client.post('/api/needs', json={'raw_text': '另一条需求', 'mode': 'demo'}).status_code == 400


def test_time_conflict_and_travel_conflict(client):
    need = patch(client, create_demo(client), availability_start='10:00')
    assert rule(draft(client, need), 'availability')['status'] == 'conflict'
    need = patch(client, need, availability_start='08:00', travel_minutes=90)
    assert rule(draft(client, need), 'availability')['status'] == 'conflict'


def test_budget_overrun_and_unknown_amount(client):
    need = patch(client, create_demo(client), costs=[{'label': '已知交通费用', 'amount': 160}], budget_scope='交通与助餐')
    assert rule(draft(client, need), 'budget')['status'] == 'conflict'
    need = patch(client, need, costs=[{'label': '午餐', 'amount': None}])
    assert rule(draft(client, need), 'budget')['status'] == 'unknown'
    assert draft(client, need)['budget']['known_subtotal'] is None


def test_edit_versions_stale_drafts_and_idempotent_generation(client):
    need = create_demo(client)
    first = draft(client, need)
    assert draft(client, need)['id'] == first['id']
    edited = patch(client, need, budget_limit=100)
    assert edited['version'] == 2
    assert edited['evidence']['budget_limit']['source'] == 'user_edit'
    assert client.get('/api/plans/' + first['id']).json()['is_stale'] is True
    assert client.patch('/api/needs/' + need['id'], json={'expected_version': 1, 'fields': need['fields']}).status_code == 409
    assert client.post(f"/api/needs/{need['id']}/plan-drafts", json={'expected_version': 1}).status_code == 409
    second = draft(client, edited)
    assert second['version'] == 2 and second['fields_snapshot']['budget_limit'] == 100
    assert second['is_stale'] is False


def test_disk_persistence_after_application_restart(config):
    with TestClient(create_app(config)) as first:
        need = create_demo(first)
        plan = draft(first, need)
    with TestClient(create_app(config)) as restarted:
        result = restarted.get('/api/plans/' + plan['id']).json()
        assert result['tasks'] == plan['tasks']
        assert result['id'] == plan['id']
        assert len(restarted.get(f"/api/needs/{need['id']}/events").json()) >= 3


def test_resources_require_explicit_demo_opt_in_and_matching_region(client):
    assert client.get('/api/resources').json() == []
    assert client.get('/api/resources', params={'region': '演示片区'}).json() == []
    resources = client.get('/api/resources', params={'region': '演示片区', 'include_demo': True}).json()
    assert len(resources) == 5
    assert all(r['data_type'] == 'demo' and r['price'] is None for r in resources)
    need = patch(client, create_demo(client), region='演示片区')
    assert draft(client, need)['resources'] == []
    assert len(draft(client, need, include_demo=True)['resources']) == 5


def test_optional_meal_and_accompaniment_are_not_forced(client):
    need = patch(client, create_demo(client), accompaniment_required=False, meal_required=False)
    plan = draft(client, need)
    assert 'meal' not in [t['id'] for t in plan['tasks']]
    assert 'accompany' not in [t['id'] for t in plan['tasks']]
    assert rule(plan, 'availability')['status'] == 'not_applicable'


def test_invalid_dates_times_and_negative_costs(client):
    need = create_demo(client)
    for fields in [
        {**need['fields'], 'service_date': '2026-02-30'},
        {**need['fields'], 'availability_start': '13:00', 'availability_end': '12:00'},
        {**need['fields'], 'budget_limit': -1},
        {**need['fields'], 'travel_minutes': 0},
    ]:
        result = client.patch('/api/needs/' + need['id'], json={'expected_version': 1, 'fields': fields})
        assert result.status_code == 422
        assert 'trace_id' in result.json()


def test_external_origin_writes_rejected(client):
    response = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'demo'}, headers={'Origin': 'https://unrelated.example'})
    assert response.status_code == 403


def test_model_timeout_preserves_need_and_allows_manual_edit(client, monkeypatch):
    async def timeout(*args):
        raise ModelFailure('timeout', '模型请求超时，可手工填写。')
    monkeypatch.setattr('anxin.main.extract_need', timeout)
    need = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'model'}).json()
    assert need['extraction_status'] == 'timeout'
    edited = patch(client, need, budget_limit=100)
    assert edited['fields']['budget_limit'] == 100


def test_model_gateway_validates_quotes_and_handles_provider_errors(config, monkeypatch):
    # Contract tests use an in-memory transport. They do not verify a real provider.
    actual_client = httpx.AsyncClient
    mode = {'case': 'valid'}
    def respond(request):
        if mode['case'] == 'auth':
            return httpx.Response(401)
        quote = '150元' if mode['case'] == 'valid' else '不存在的依据'
        content = {'fields': {'budget_limit': 150}, 'evidence': {'budget_limit': quote}}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}}]})
    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient', lambda **kw: actual_client(transport=httpx.MockTransport(respond), **kw))
    cfg = replace(config, model_base_url='https://api.example/v1', model_name='contract-test', model_api_key='test-placeholder')
    fields, evidence = asyncio.run(extract_need(DEMO_INPUT, cfg))
    assert fields.budget_limit == 150 and evidence['budget_limit']['quote'] == '150元'
    mode['case'] = 'invalid'
    with pytest.raises(ModelFailure, match='invalid_evidence'):
        asyncio.run(extract_need(DEMO_INPUT, cfg))
    mode['case'] = 'auth'
    with pytest.raises(ModelFailure, match='unauthorized'):
        asyncio.run(extract_need(DEMO_INPUT, cfg))
