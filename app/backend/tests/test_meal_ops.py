"""运营扩展：真实/演示隔离、人员竞争、补问待办与来源交叉核对。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from test_meal_workflow import act, client, create, edit, ready, verify
from anxin.meal_ops import next_steps


def register(c, **extra):
    body = {'code': 'V001', 'data_type': 'demo', 'service_date': '2026-10-25', 'town': '市桥街道',
            'start': '12:00', 'end': '13:00', **extra}
    return c.post('/api/meal/volunteers', json=body)


def bind(c, case, volunteer):
    response = c.post(f"/api/meal/cases/{case['id']}/assign", json={
        'expected_version': case['version'], 'volunteer_id': volunteer['id']})
    assert response.status_code == 200, response.text
    return c.get('/api/meal/cases/' + case['id']).json()


def test_sources_have_cross_checks_and_no_claimed_operator_contact(client):
    data = client.get('/api/meal/source-evidence').json()
    assert data['official_records'] == 154 and data['leading_panyu_records'] == 13
    assert data['cross_matched'] == 12 and len(data['unmatched_leading']) == 1
    assert data['basis'] == 'public_pages_only_no_operator_contact'
    assert all(s['http_status'] == 200 and len(s['sha256']) == 64 for s in data['sources'])
    items = client.get('/api/meal/resources', params={'limit': 50}).json()['items']
    # 跨来源补充不改变价格、营业或预约含义。
    assert all(r['price'] is None and r['availability'] is None for r in items)


def test_resource_pagination_has_no_duplicates_or_missing_records(client):
    pages = [client.get('/api/meal/resources', params={'offset': n, 'limit': 50}).json()['items'] for n in (0, 50, 100, 150)]
    assert len({r['id'] for page in pages for r in page}) == 154
    assert sum(len(page) for page in pages) == 154
    assert client.get('/api/meal/resources', params={'offset': -1}).status_code == 422


def test_volunteer_requires_consent_and_rejects_duplicate(client):
    assert register(client, data_type='pilot').status_code == 422
    assert register(client, code='手机号13800000000').status_code == 422
    assert register(client).status_code == 201
    assert register(client).status_code == 409


def test_candidates_isolate_day_town_and_demo_from_pilot(client):
    case = create(client)
    valid = register(client).json()
    register(client, code='V002', town='大石街道')
    register(client, code='V003', service_date='2026-10-26')
    register(client, code='V004', data_type='pilot', consent_confirmed=True)
    items = client.get(f"/api/meal/cases/{case['id']}/candidates").json()['items']
    assert [i['id'] for i in items] == [valid['id']]
    assert not items[0]['eligible']  # 只有登记，未核实的候选不能说可以直接接受。


def test_binding_invalidates_old_commitments_and_keeps_audit(client):
    case = act(client, ready(client), 'accept')
    v = register(client).json()
    changed = bind(client, case, v)
    assert changed['fields']['pickup_person'] == 'V001'
    assert changed['status'] == 'draft' and changed['supply_check'] is None and changed['acceptance'] is None
    events = client.get(f"/api/meal/cases/{case['id']}/events").json()
    assert events[-1]['action'] == 'meal_candidate_selected'
    # 手工改人会解除排班绑定，避免拿A的排班给B占位。
    changed = edit(client, changed, pickup_person='V999')
    assert not changed.get('volunteer_id')


def test_atomic_accept_prevents_double_booking_registered_volunteer(client):
    v = register(client).json()
    cases = [verify(client, bind(client, ready(client), v)) for _ in range(2)]

    def accept(case):
        return client.post(f"/api/meal/cases/{case['id']}/actions", json={
            'expected_version': case['version'], 'action': 'accept', 'actor': '模拟操作者', 'note': '仅合成并发接受测试'})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, cases))
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = cases[next(i for i, r in enumerate(results) if r.status_code == 409)]
    item = client.get(f"/api/meal/cases/{loser['id']}/candidates").json()['items'][0]
    assert item['conflicting_cases'] and not item['eligible']
    winner = results[next(i for i, r in enumerate(results) if r.status_code == 200)].json()
    act(client, winner, 'block')  # 受阻取消接受占用，允许明确重排。
    assert accept(loser).status_code == 200


def test_candidate_wrong_town_cannot_be_bound_and_stale_version_rejected(client):
    case = create(client)
    v = register(client, town='大石街道').json()
    url = f"/api/meal/cases/{case['id']}/assign"
    assert client.post(url, json={'expected_version': case['version'], 'volunteer_id': v['id']}).status_code == 409
    v = register(client, code='V002').json()
    assert client.post(url, json={'expected_version': 1, 'volunteer_id': v['id']}).status_code == 409


def test_comparison_shows_current_quote_only_for_selected_resource(client):
    case = ready(client)
    response = client.get(f"/api/meal/cases/{case['id']}/resource-comparison").json()
    assert response['items'][0]['id'] == case['supply_check']['resource_id']
    assert response['items'][0]['current_quote'] == 20
    assert all(r['current_quote'] is None for r in response['items'][1:])


def test_playbook_does_not_leak_family_address_or_diet(client):
    case = edit(client, create(client), handover_place='不得导出的详细家庭地址', diet_notes='不得导出的敏感饮食备注')
    playbook = client.get(f"/api/meal/cases/{case['id']}/playbook").json()
    assert playbook['case_version'] == case['version'] and playbook['data_type'] == 'demo'
    assert '不得导出' not in str(playbook)
    assert any('取餐时刻' in q for q in playbook['next_action']['questions'])
    assert playbook['replication_tasks']


def test_board_keeps_demo_separate_and_does_not_send_notifications(client):
    case = create(client)
    response = client.get('/api/meal/board').json()
    assert response['counts']['demo'] == 1 and response['counts']['pilot'] == 0
    assert response['notifications_sent'] is False
    act(client, case, 'cancel')
    assert client.get('/api/meal/board').json()['items'] == []


def test_due_logic_uses_given_beijing_clock_and_keeps_closed_items_closed():
    from anxin.meal_domain import demo_meal_fields
    p = {'status': 'accepted', 'fields': {**demo_meal_fields().model_dump(mode='json'), 'planned_pickup': '12:05'}, 'supply_check': None}
    after = datetime.fromisoformat('2026-10-25T12:06:00+08:00')
    assert next_steps(p, after)['overdue']
    assert not next_steps(p, after.replace(hour=11))['overdue']
    assert next_steps({**p, 'status': 'completed'}, after)['priority'] == 'closed'
