"""Explicit live smoke check: one synthetic request, no credential output.

Run only when live API verification is intended. A single needs request can
perform an initial provider call and at most one schema/evidence repair call.
"""
import json
import sys
import time
from pathlib import Path

import httpx

from anxin.config import APP_ROOT
from anxin.domain import DEMO_INPUT


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.perf_counter()
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=65) as client:
        health = client.get('/api/health').raise_for_status().json()
        if not health['model_configured']:
            raise SystemExit('Model not configured. No provider request was sent.')
        result = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'model'}).raise_for_status().json()
        elapsed = round(time.perf_counter() - started, 2)
        record = {
            'need_id': result['id'], 'extraction_status': result['extraction_status'],
            'extraction_message': result['extraction_message'], 'elapsed_seconds': elapsed,
            'fields': result['fields'], 'evidence_count': len(result['evidence']),
            'missing_fields': [item['field'] for item in result['missing_fields']],
            'checked_at': result['updated_at'],
        }
        if result['extraction_status'] == 'succeeded':
            fields = result['fields']
            expected = {
                'date': fields['service_date'] == '2026-10-24',
                'arrival': (fields['arrival_deadline'] or '').startswith('09:00'),
                'budget': fields['budget_limit'] == 150,
                'candidate': fields['participant_name'] == '妹妹',
                'care_recipient': '老人' in (fields['care_recipient'] or ''),
                'accompaniment': fields['accompaniment_required'] is True,
                'requester_unavailable': '上午' in (fields['requester_unavailable'] or ''),
                'availability_start': (fields['availability_start'] or '').startswith('08:00'),
                'availability_end': (fields['availability_end'] or '').startswith('12:00'),
                'meal': fields['meal_required'] is True,
                'acceptance_unknown': fields['acceptance_status'] == 'unknown',
                'travel_unknown': fields['travel_minutes'] is None,
                'region_unknown': fields['region'] is None,
                'budget_scope_unknown': fields['budget_scope'] is None,
                'quotes_locatable': bool(result['evidence']) and all(e['quote'] in DEMO_INPUT for e in result['evidence'].values()),
            }
            record['checks'] = expected
            if all(expected.values()):
                # This saves a draft only; it does not book services or confirm a member.
                plan = client.post(f"/api/needs/{result['id']}/plan-drafts", json={'expected_version': result['version']}).raise_for_status().json()
                reread = client.get('/api/plans/' + plan['id']).raise_for_status().json()
                record.update(plan_id=plan['id'], plan_status=plan['status'],
                              draft_persisted=reread['tasks'] == plan['tasks'],
                              unknown_total=reread['budget']['total'] is None,
                              task_count=len(plan['tasks']))
        target = APP_ROOT / 'runtime' / 'live-verification.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(record, ensure_ascii=False, indent=2))
        succeeded = record.get('extraction_status') == 'succeeded' and all(record.get('checks', {}).values()) and record.get('draft_persisted')
        raise SystemExit(0 if succeeded else 1)


if __name__ == '__main__':
    main()
