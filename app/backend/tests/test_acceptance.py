"""A01—A10补充验收：重点验证原测试没有明确覆盖的缺项与故障边界。

使用临时数据库和内存HTTP故障，不读取真实账号、不消耗模型额度。
"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from anxin.config import Settings
from anxin.domain import DEMO_INPUT, NeedFields
from anxin.main import create_app
from anxin.model_gateway import ModelFailure, extract_need


@pytest.fixture
def client(tmp_path):
    config = Settings(database_path=str(tmp_path / 'acceptance.db'),
                      model_base_url='', model_name='', model_api_key='')
    with TestClient(create_app(config)) as instance:
        yield instance


def create_demo(client):
    response = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'demo'})
    assert response.status_code == 201
    return response.json()


def make_draft(client, need):
    response = client.post(f"/api/needs/{need['id']}/plan-drafts",
                           json={'expected_version': need['version']})
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize('missing', ['service_date', 'region', 'arrival_deadline'])
def test_a03_deleted_required_field_stays_unknown(client, missing):
    need = create_demo(client)
    fields = {**need['fields'], missing: None}
    # region在合成输入中本来就未知，明确验证不会自动补一个地区。
    response = client.patch('/api/needs/' + need['id'],
                            json={'expected_version': need['version'], 'fields': fields})
    assert response.status_code == 200
    need = response.json()
    plan = make_draft(client, need)
    assert need['fields'][missing] is None
    assert missing in {item['field'] for item in need['missing_fields']}
    assert missing in {item['field'] for item in plan['missing_fields']}
    assert plan['fields_snapshot'][missing] is None
    assert plan['status'] == 'needs_information'
    assert all(task['status'] == 'draft' for task in plan['tasks'])


def test_a05_mixed_known_and_unknown_costs_are_separate(client):
    need = create_demo(client)
    response = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'],
        'fields': {**need['fields'], 'budget_scope': '交通与午餐',
                   'costs': [{'label': '交通', 'amount': 20}, {'label': '午餐', 'amount': None}]},
    })
    assert response.status_code == 200
    plan = make_draft(client, response.json())
    assert plan['budget']['known_subtotal'] == 20
    assert plan['budget']['has_unknown_costs'] is True
    assert plan['budget']['total'] is None
    assert next(r for r in plan['rules'] if r['code'] == 'budget')['status'] == 'unknown'
    assert next(r for r in plan['rules'] if r['code'] == 'acceptance')['status'] == 'unknown'


def test_a06_time_edit_changes_rule_and_keeps_previous_snapshot(client):
    need = create_demo(client)
    original = make_draft(client, need)
    response = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'],
        'fields': {**need['fields'], 'availability_start': '10:00'},
    })
    assert response.status_code == 200
    edited = response.json()
    updated = make_draft(client, edited)
    assert updated['fields_snapshot']['availability_start'].startswith('10:00')
    assert next(r for r in updated['rules'] if r['code'] == 'availability')['status'] == 'conflict'
    old = client.get('/api/plans/' + original['id']).json()
    assert old['fields_snapshot']['availability_start'].startswith('08:00')
    assert old['is_stale'] is True
    assert edited['evidence']['availability_start']['source'] == 'user_edit'


@pytest.mark.parametrize('status', [401, 403, 404, 429, 503])
def test_a08_provider_failure_does_not_claim_success(client, monkeypatch, status):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient',
                        lambda **kw: original(transport=transport, **kw))
    config = Settings(model_base_url='https://acceptance.invalid/v1',
                      model_name='contract-test', model_api_key='synthetic-placeholder')

    async def configured_extract(raw_text, _):
        return await extract_need(raw_text, config)

    monkeypatch.setattr('anxin.main.extract_need', configured_extract)
    response = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'model'})
    assert response.status_code == 201
    need = response.json()
    expected = {401: 'unauthorized', 403: 'unauthorized', 404: 'model_not_found',
                429: 'rate_limited', 503: 'provider_error'}[status]
    assert need['extraction_status'] == expected
    assert need['raw_text'] == DEMO_INPUT and need['fields'] == NeedFields().model_dump(mode='json')
    assert need['evidence'] == {}
    assert client.get('/api/needs/' + need['id']).json()['extraction_status'] == expected
    saved = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'], 'fields': {**need['fields'], 'budget_limit': 100},
    })
    assert saved.status_code == 200 and saved.json()['fields']['budget_limit'] == 100


@pytest.mark.parametrize('body', [
    {'choices': [None]}, {'choices': [[]]}, {'choices': [{'message': None}]},
    {'choices': []}, {'choices': [{'message': {'content': 'not-json'}}]},
])
def test_a08_malformed_provider_envelope_is_controlled(monkeypatch, body):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient',
                        lambda **kw: original(transport=transport, **kw))
    config = Settings(model_base_url='https://acceptance.invalid/v1',
                      model_name='contract-test', model_api_key='synthetic-placeholder')
    with pytest.raises(ModelFailure) as failure:
        asyncio.run(extract_need(DEMO_INPUT, config))
    assert failure.value.code == 'invalid_output'


def test_a08_total_timeout_stops_slow_transport(monkeypatch):
    original = httpx.AsyncClient

    async def slow(_):
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={})

    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient',
                        lambda **kw: original(transport=httpx.MockTransport(slow), **kw))
    config = Settings(model_base_url='https://acceptance.invalid/v1',
                      model_name='contract-test', model_api_key='synthetic-placeholder', model_timeout=0.02)
    with pytest.raises(ModelFailure) as failure:
        asyncio.run(extract_need(DEMO_INPUT, config))
    assert failure.value.code == 'timeout'


def test_a08_malformed_envelope_persists_failure_for_manual_recovery(client, monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'choices': [None]}))
    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient',
                        lambda **kw: original(transport=transport, **kw))
    config = Settings(model_base_url='https://acceptance.invalid/v1',
                      model_name='contract-test', model_api_key='synthetic-placeholder')

    async def configured_extract(raw_text, _):
        return await extract_need(raw_text, config)

    monkeypatch.setattr('anxin.main.extract_need', configured_extract)
    response = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'model'})
    assert response.status_code == 201
    need = response.json()
    assert need['extraction_status'] == 'invalid_output'
    assert need['raw_text'] == DEMO_INPUT and need['evidence'] == {}
    assert client.get('/api/needs/' + need['id']).json()['extraction_status'] == 'invalid_output'
    response = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'], 'fields': {**need['fields'], 'budget_limit': 100},
    })
    assert response.status_code == 200
    assert make_draft(client, response.json())['fields_snapshot']['budget_limit'] == 100


def test_a10_response_headers_and_error_trace(client):
    response = client.get('/api/health')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert response.headers['x-trace-id']
    error = client.get('/api/plans/absent')
    assert error.status_code == 404
    assert error.json()['trace_id'] == error.headers['x-trace-id']
    assert 'traceback' not in json.dumps(error.json()).lower()
