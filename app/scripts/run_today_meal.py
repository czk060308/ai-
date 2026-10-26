"""当天在线演练：公开名单+可选真实抽取+正常/拒绝/改派三支流程。

所有记录强制demo。无家庭、商家联系，无真实交接，不代表非开发者复用测试。
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from anxin.config import APP_ROOT
from anxin.meal_domain import MEAL_SAMPLE, demo_meal_fields
from anxin.resources import region_scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='仅正常分支调用真实模型，可能产生费用')
    args = parser.parse_args()
    now = datetime.now(timezone(timedelta(hours=8)))
    today, prefix = now.date().isoformat(), 'SIM-' + uuid4().hex[:8]
    report = {'checked_at': now.isoformat(), 'data_type': 'demo', 'external_contact': False,
              'human_replication_test': False, 'live_requested': args.live, 'scenarios': []}
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=65) as c:
        before = c.get('/api/meal/stats').raise_for_status().json()
        sources = c.get('/api/meal/source-evidence').raise_for_status().json()
        report['public_data'] = {k: sources[k] for k in ('official_records', 'leading_panyu_records', 'cross_matched', 'primary_snapshot_drift')}
        resources = c.get('/api/meal/resources', params={'town': '市桥街道'}).raise_for_status().json()['items']
        assert len(resources) >= 2
        volunteers = []
        for suffix in ('A', 'B'):
            v = c.post('/api/meal/volunteers', json={'code': prefix + suffix, 'data_type': 'demo', 'service_date': today,
                'town': '市桥街道', 'start': '12:00', 'end': '13:00'}).raise_for_status().json()
            volunteers.append(v)

        def create(model=False, **overrides):
            raw = MEAL_SAMPLE.replace('2026年10月25日', f'{now.year}年{now.month}月{now.day}日')
            case = c.post('/api/meal/cases', json={'raw_text': raw, 'mode': 'model' if model else 'manual', 'data_type': 'demo'}).raise_for_status().json()
            if model:
                report['model_result'] = {'case_id': case['id'], 'status': case['extraction_status'], 'review': case['extraction_review']}
                f = case['fields']
                assert case['extraction_status'] == 'succeeded', 'Model failed; failure record retained'
                assert (f['service_date'] == today and region_scope(f['region']) == ('广州市', '番禺区') and f['town'] == '市桥街道'
                        and f['budget_limit'] == 25 and f['meal_people'] == 1 and f['planned_pickup'] is None)
                assert all(e['quote'] in raw for e in case['evidence'].values())
                values = {**f, 'planned_pickup': '12:05', **overrides}
            else:
                values = {**demo_meal_fields().model_dump(mode='json'), 'service_date': today, 'planned_pickup': '12:05', **overrides}
            return c.patch('/api/meal/cases/' + case['id'], json={'expected_version': case['version'], 'fields': values}).raise_for_status().json()

        def bind(case, v):
            path = '/api/meal/cases/' + case['id']
            c.post(path + '/assign', json={'expected_version': case['version'], 'volunteer_id': v['id']}).raise_for_status()
            return c.get(path).raise_for_status().json()

        def verify(case, resource):
            return c.post('/api/meal/cases/' + case['id'] + '/verify', json={'expected_version': case['version'],
                'resource_id': resource['id'], 'service_date': today, 'supply_start': '11:00', 'supply_end': '13:00',
                'quoted_total': 20, 'takeaway_confirmed': True, 'eligibility_confirmed': True, 'diet_confirmed': True,
                'verified_by': prefix, 'method': 'phone', 'note': '在线合成演练，未打电话、未核实商家，模拟总价20元'}).raise_for_status().json()

        def action(case, verb):
            return c.post('/api/meal/cases/' + case['id'] + '/actions', json={'expected_version': case['version'],
                'action': verb, 'actor': prefix, 'note': '在线合成演练，没有实际联系、接受、取餐或交接'}).raise_for_status().json()

        def complete(case):
            for verb in ('accept', 'picked_up', 'handed_over'):
                case = action(case, verb)
            return c.post('/api/meal/cases/' + case['id'] + '/feedback', json={'expected_version': case['version'],
                'reporter': '合成反馈', 'channel': 'oral', 'comment': '仅在线合成反馈，无真实家庭评价'}).raise_for_status().json()

        try:
            case = create(args.live)
            case = verify(bind(case, volunteers[0]), resources[0])
            case = complete(case)
            report['scenarios'].append({'name': 'normal', 'case_id': case['id'], 'status': case['status'], 'passed': case['status'] == 'completed'})
            case = verify(create(budget_limit=10), resources[0])
            rejection = c.post('/api/meal/cases/' + case['id'] + '/actions', json={'expected_version': case['version'],
                'action': 'accept', 'actor': prefix, 'note': '合成测试超预算应当被阻止'})
            assert rejection.status_code == 409
            case = action(case, 'cancel')
            report['scenarios'].append({'name': 'over_budget_rejected', 'case_id': case['id'], 'status': case['status'], 'passed': rejection.status_code == 409})
            case = verify(bind(create(), volunteers[0]), resources[0])
            case = action(action(case, 'accept'), 'block')
            case = bind(case, volunteers[1])
            assert case['acceptance'] is None and case['supply_check'] is None
            case = verify(case, resources[1])
            case = complete(case)
            playbook = c.get('/api/meal/cases/' + case['id'] + '/playbook').raise_for_status().json()
            events = c.get('/api/meal/cases/' + case['id'] + '/events').raise_for_status().json()
            report['scenarios'].append({'name': 'blocked_reassigned_reverified', 'case_id': case['id'], 'status': case['status'],
                'passed': case['status'] == 'completed' and sum(e['action'] == 'meal_candidate_selected' for e in events) == 2,
                'playbook_version': playbook['guide_version'], 'event_count': len(events)})
        except (AssertionError, httpx.HTTPError) as exc:
            report['error_type'] = type(exc).__name__
        after = c.get('/api/meal/stats').raise_for_status().json()
        report['pilot_stats_unchanged'] = all(before[k] == after[k] for k in ('pilot_cases', 'families', 'completed', 'feedback_count'))
        report['pilot_cases'] = after['pilot_cases']
        report['passed'] = len(report['scenarios']) == 3 and all(r['passed'] for r in report['scenarios']) and report['pilot_stats_unchanged']
    target = APP_ROOT / 'runtime' / ('today-meal-' + now.strftime('%Y%m%dT%H%M%S') + '.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
