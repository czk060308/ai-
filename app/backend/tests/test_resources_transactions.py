"""真实公开目录的地区边界及SQLite并发、回滚检查。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from anxin.config import Settings
from anxin.domain import DEMO_INPUT
from anxin.main import create_app
from anxin.resources import load_catalog
from anxin.storage import Base, Event, PlanDraft, Resource, immediate_session, make_storage


@pytest.fixture
def client(tmp_path):
    config = Settings(database_path=str(tmp_path / 'resources.db'), model_base_url='', model_name='', model_api_key='')
    with TestClient(create_app(config)) as instance:
        yield instance


def test_public_catalog_has_sources_and_no_claimed_live_prices():
    public = [r for r in load_catalog() if r['data_type'] == 'public']
    assert len(public) == 7
    assert len([r for r in public if r['category'] == 'meal']) == 5
    assert all(r['source_url'].startswith('https://') and r['checked_at'] and r['unknown_fields'] for r in public)
    assert all(r['price'] is None and r['availability'] is None and r['phone'] is None for r in public)


@pytest.mark.parametrize('region', ['厦门市', '厦门', '湖里区', '厦门市湖里区', '思明', '翔安区'])
def test_public_resources_do_not_require_demo_switch(client, region):
    resources = client.get('/api/resources', params={'region': region}).json()
    assert resources and all(r['data_type'] == 'public' for r in resources)
    assert all(r['source_stale'] and r['match_reason'] for r in resources)


def test_district_matching_does_not_claim_other_district_service(client):
    resources = client.get('/api/resources', params={'region': '湖里区'}).json()
    assert len(resources) == 4
    assert {r['name'] for r in resources if r['scope'] == 'local_site'} == {'后浦近邻长者食堂', '南厝社区食堂'}
    assert all(r['district'] in (None, '湖里区') for r in resources)
    assert client.get('/api/resources', params={'region': '北京市'}).json() == []
    assert client.get('/api/resources', params={'region': '思明区附近'}).json() == []


def test_public_draft_links_sources_but_still_requires_verification(client):
    need = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'demo'}).json()
    need = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'], 'fields': {**need['fields'], 'region': '厦门市'},
    }).json()
    plan = client.post(f"/api/needs/{need['id']}/plan-drafts", json={'expected_version': need['version']}).json()
    assert len(plan['resources']) == 7
    assert plan['budget']['total'] is None
    assert next(r for r in plan['rules'] if r['code'] == 'resource_verification')['status'] == 'unknown'
    assert client.get('/api/plans/' + plan['id']).json()['resources'] == plan['resources']
    need = client.patch('/api/needs/' + need['id'], json={
        'expected_version': need['version'], 'fields': {**need['fields'], 'meal_required': False},
    }).json()
    plan = client.post(f"/api/needs/{need['id']}/plan-drafts", json={'expected_version': need['version']}).json()
    assert all(r['category'] != 'meal' for r in plan['resources'])


def test_parallel_generation_returns_one_draft_and_one_event(client):
    need = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'demo'}).json()
    barrier = Barrier(6)

    def generate(_):
        barrier.wait(timeout=10)
        response = client.post(f"/api/needs/{need['id']}/plan-drafts", json={'expected_version': need['version']})
        assert response.status_code == 201
        return response.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(generate, range(6)))
    assert len({r['id'] for r in results}) == 1
    assert all(r['version'] == 1 for r in results)
    events = client.get(f"/api/needs/{need['id']}/events").json()
    assert sum(e['action'] == 'draft_saved' for e in events) == 1


def test_immediate_session_rolls_back_both_plan_and_event(tmp_path):
    engine, sessions = make_storage(str(tmp_path / 'rollback.db'))
    Base.metadata.create_all(engine)
    with pytest.raises(RuntimeError, match='injected failure'):
        with immediate_session(sessions) as db:
            db.add(PlanDraft(id='rollback-plan', need_id='rollback-need', need_version=1, version=1, payload={}))
            db.add(Event(id='rollback-event', object_id='rollback-need', action='draft_saved', payload={}))
            db.flush()
            raise RuntimeError('injected failure')
    with sessions() as db:
        assert db.get(PlanDraft, 'rollback-plan') is None
        assert db.get(Event, 'rollback-event') is None
    # 回滚释放写锁，后续会话可以正常提交。
    with immediate_session(sessions) as db:
        db.add(Event(id='after-rollback', object_id='probe', action='probe', payload={}))
    with sessions() as db:
        assert db.get(Event, 'after-rollback') is not None
    engine.dispose()


@pytest.mark.parametrize('managed', [True, False])
def test_catalog_refresh_only_upgrades_owned_records(monkeypatch, tmp_path, managed):
    config = Settings(database_path=str(tmp_path / 'upgrade.db'), model_base_url='', model_name='', model_api_key='')
    with TestClient(create_app(config)) as first:
        with first.app.state.sessions.begin() as db:
            record = db.get(Resource, 'public-xm-wujia-meal')
            record.payload = {**record.payload, 'catalog_managed_by': 'anxin_public_seed' if managed else 'manual_catalog', 'name': '人工核对名称'}
    rows = load_catalog()
    for row in rows:
        if row['id'] == 'public-xm-wujia-meal':
            row.update(catalog_version=2, name='目录升级名称')
    monkeypatch.setattr('anxin.main.load_catalog', lambda: rows)
    with TestClient(create_app(config)) as second:
        resources = second.get('/api/resources', params={'region': '厦门市'}).json()
        actual = next(r for r in resources if r['id'] == 'public-xm-wujia-meal')
        assert actual['name'] == ('目录升级名称' if managed else '人工核对名称')
