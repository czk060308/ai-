"""模型合约回归：参数兼容、输出拒绝与有限修正，不请求供应商。"""

import asyncio
from dataclasses import replace

import httpx
import pytest

from anxin.config import Settings
from anxin.domain import DEMO_INPUT
from anxin.model_gateway import ModelFailure, build_request, extract_need


def test_generic_model_keeps_baseline_parameters():
    config = Settings(model_name='contract-test')
    body = build_request(config, 'JSON extraction', DEMO_INPUT)
    assert body['temperature'] == 0 and body['max_tokens'] == 2400
    assert 'thinking' not in body and 'reasoning_effort' not in body


def test_kimi_k26_extraction_uses_non_thinking_json_profile():
    body = build_request(Settings(model_name='kimi-k2.6'), 'JSON extraction', DEMO_INPUT)
    assert 'temperature' not in body and 'reasoning_effort' not in body
    assert body['thinking'] == {'type': 'disabled'}
    assert body['max_tokens'] == 4096
    assert body['response_format'] == {'type': 'json_object'}


def test_one_evidence_repair_keeps_original_quote_validation(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    def respond(request):
        calls.append(request)
        content = '{"fields":{"budget_limit":150},"evidence":{"budget_limit":"150元"}}' if len(calls) == 2 else '{"fields":{"budget_limit":150},"evidence":{}}'
        return httpx.Response(200, json={'choices': [{'message': {'content': content}}]})
    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    config = Settings(model_base_url='https://api.example/v1', model_name='kimi-k2.6', model_api_key='test-placeholder')
    fields, evidence = asyncio.run(extract_need(DEMO_INPUT, config))
    assert len(calls) == 2 and fields.budget_limit == 150
    assert evidence['budget_limit']['quote'] == '150元'


@pytest.mark.parametrize('response,expected_code', [
    ({'choices': [{'finish_reason': 'length', 'message': {'content': '{"fields":'}}]}, 'output_limit'),
    ({'choices': [{'message': {'content': '{"fields":{},"evidence":[]}'}}]}, 'invalid_output'),
])
def test_incomplete_or_invalid_evidence_output_is_not_accepted(monkeypatch, response, expected_code):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    monkeypatch.setattr('anxin.model_gateway.httpx.AsyncClient', lambda **kw: original(transport=transport, **kw))
    config = Settings(model_base_url='https://api.example/v1', model_name='kimi-k3', model_api_key='test-placeholder')
    with pytest.raises(ModelFailure) as raised:
        asyncio.run(extract_need(DEMO_INPUT, config))
    assert raised.value.code == expected_code
