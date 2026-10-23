"""A01/A02/A07/A10运行验收，证据保存在忽略入库的runtime目录。

默认不请求模型。--live明确执行三个合成输入，最多六次供应商请求
（每个输入最多修正一次）。重启检查使用独立临时数据库和子进程。
只输出检查结论、合成记录ID与用时，绝不输出配置或密钥。
"""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

from anxin.config import APP_ROOT
from anxin.domain import DEMO_INPUT
from check_staged import TOKEN_PATTERN

ROOT = APP_ROOT.parent


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def check_restart():
    """真正退出并重建两个API进程；不停止用户正在使用的8000服务。"""
    with tempfile.TemporaryDirectory(prefix='anxin-acceptance-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update(ANXIN_DATABASE_PATH=str(Path(directory) / 'restart.db'),
                   MODEL_BASE_URL='', MODEL_NAME='', MODEL_API_KEY='')
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        command = [sys.executable, '-E', '-X', 'utf8', '-m', 'uvicorn',
                   'anxin.main:app', '--host', '127.0.0.1', '--port', str(port)]
        pids = []
        log_path = APP_ROOT / 'runtime' / 'acceptance-restart.log'
        with log_path.open('w', encoding='utf-8') as log:
            for round_number in range(2):
                process = subprocess.Popen(command, cwd=APP_ROOT, env=env,
                                           stdout=log, stderr=log,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                pids.append(process.pid)
                try:
                    with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=3) as client:
                        deadline = time.monotonic() + 15
                        while True:
                            if process.poll() is not None:
                                raise RuntimeError('Acceptance subprocess exited before ready')
                            try:
                                client.get('/api/health').raise_for_status()
                                break
                            except httpx.HTTPError:
                                if time.monotonic() >= deadline:
                                    raise RuntimeError('Acceptance subprocess startup timeout') from None
                                time.sleep(0.15)
                        if round_number == 0:
                            need = client.post('/api/needs', json={'raw_text': DEMO_INPUT, 'mode': 'demo'}).raise_for_status().json()
                            need = client.patch('/api/needs/' + need['id'], json={
                                'expected_version': need['version'],
                                'fields': {**need['fields'], 'budget_limit': 100},
                            }).raise_for_status().json()
                            plan = client.post(f"/api/needs/{need['id']}/plan-drafts",
                                               json={'expected_version': need['version']}).raise_for_status().json()
                        snapshot = {
                            'need': client.get('/api/needs/' + need['id']).raise_for_status().json(),
                            'plan': client.get('/api/plans/' + plan['id']).raise_for_status().json(),
                            'events': client.get(f"/api/needs/{need['id']}/events").raise_for_status().json(),
                        }
                        if round_number == 0:
                            before = snapshot
                        else:
                            equal = snapshot == before
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
        return {'passed': equal and pids[0] != pids[1], 'different_processes': pids[0] != pids[1],
                'before_sha256': fingerprint(before), 'after_sha256': fingerprint(snapshot),
                'task_count': len(snapshot['plan']['tasks']), 'evidence_count': len(snapshot['need']['evidence']),
                'event_count': len(snapshot['events']), 'database': 'isolated_temporary_sqlite'}


def check_secrets():
    """扫描源码、构建产物与可读取的本机日志；仅记录文件名和计数。"""
    values = {**dotenv_values(APP_ROOT / '.env'), **os.environ}
    secrets = [value.encode() for key, value in values.items()
               if key.startswith(('MODEL_', 'ANXIN_')) and re.search(r'KEY|TOKEN|SECRET|PASSWORD', key)
               and value and len(value) >= 8]
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    sources = [ROOT / name for name in names if name and (ROOT / name).is_file()]
    assets = [p for p in (APP_ROOT / 'apps/web/dist').rglob('*') if p.is_file()]
    logs = list((APP_ROOT / 'runtime').rglob('*.log'))
    failures = []
    for path in sources + assets + logs:
        data = path.read_bytes()
        if any(secret in data for secret in secrets) or TOKEN_PATTERN.search(data):
            failures.append(path.relative_to(ROOT).as_posix())
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    private_tracked = [name for name in tracked if Path(name).name.startswith('.env') and Path(name).name != '.env.example']
    ignored = subprocess.run(['git', 'check-ignore', '-q', 'app/.env'], cwd=ROOT).returncode == 0
    return {'passed': not failures and not private_tracked and ignored and bool(secrets),
            'credential_compared': bool(secrets), 'source_files': len(sources), 'built_files': len(assets),
            'log_files': len(logs), 'env_ignored': ignored, 'private_config_tracked': private_tracked,
            'flagged_files': failures, 'scope': 'current_files_and_readable_logs_only'}


def check_live(client):
    cases = [
        ('baseline', DEMO_INPUT),
        ('missing', '家里老人需要有人陪同去医院，日期和地区都还没定。哥哥可以帮忙但还没有确认接受。预算和交通时长暂不清楚，不需要午餐。'),
        ('conflict', '2026年10月25日上午9点前要到医院，家里老人需要陪同。弟弟当天10点到12点有空，还没确认接受。生活服务预算200元，地区和单程交通时间未定，不需要午餐。'),
    ]
    results = []
    for label, raw in cases:
        started = time.monotonic()
        need = client.post('/api/needs', json={'raw_text': raw, 'mode': 'model'}).raise_for_status().json()
        fields = need['fields']
        checks = {'actual_model_success': need['extraction_status'] == 'succeeded',
                  'quotes_locatable': bool(need['evidence']) and all(e['source'] == 'model_quote' and e['quote'] in raw for e in need['evidence'].values()),
                  'acceptance_unknown': fields['acceptance_status'] == 'unknown',
                  'region_unknown': fields['region'] is None, 'travel_unknown': fields['travel_minutes'] is None}
        if label == 'baseline':
            checks.update(service_date=fields['service_date'] == '2026-10-24',
                          arrival=(fields['arrival_deadline'] or '').startswith('09:00'), budget=fields['budget_limit'] == 150,
                          candidate=fields['participant_name'] == '妹妹',
                          candidate_start=(fields['availability_start'] or '').startswith('08:00'),
                          candidate_end=(fields['availability_end'] or '').startswith('12:00'),
                          care_recipient='老人' in (fields['care_recipient'] or ''),
                          requester_unavailable='上午' in (fields['requester_unavailable'] or ''),
                          accompaniment=fields['accompaniment_required'] is True, meal=fields['meal_required'] is True,
                          scope_unknown=fields['budget_scope'] is None)
        elif label == 'missing':
            checks.update(date_unknown=fields['service_date'] is None, budget_unknown=fields['budget_limit'] is None,
                          no_meal=fields['meal_required'] is False, candidate=fields['participant_name'] == '哥哥')
        else:
            checks.update(service_date=fields['service_date'] == '2026-10-25',
                          arrival=(fields['arrival_deadline'] or '').startswith('09:00'), budget=fields['budget_limit'] == 200,
                          candidate=fields['participant_name'] == '弟弟', no_meal=fields['meal_required'] is False,
                          candidate_start=(fields['availability_start'] or '').startswith('10:00'),
                          candidate_end=(fields['availability_end'] or '').startswith('12:00'))
        result = {'case': label, 'need_id': need['id'], 'extraction_status': need['extraction_status'],
                  'elapsed_seconds': round(time.monotonic() - started, 2), 'evidence_count': len(need['evidence']), 'checks': checks}
        if checks['actual_model_success']:
            plan = client.post(f"/api/needs/{need['id']}/plan-drafts", json={'expected_version': need['version']}).raise_for_status().json()
            reread = client.get('/api/plans/' + plan['id']).raise_for_status().json()
            checks.update(draft_persisted=reread == plan, total_unknown=plan['budget']['total'] is None,
                          draft_only=all(t['status'] == 'draft' for t in plan['tasks']))
            if label == 'conflict':
                checks['conflict_detected'] = next(r for r in plan['rules'] if r['code'] == 'availability')['status'] == 'conflict'
            if label == 'missing':
                checks['missing_date_and_region'] = {'service_date', 'region'} <= {m['field'] for m in plan['missing_fields']}
            result.update(plan_id=plan['id'], task_count=len(plan['tasks']), plan_status=plan['status'])
        result['passed'] = all(checks.values())
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='运行三个合成输入的真实供应商验收')
    args = parser.parse_args()
    (APP_ROOT / 'runtime').mkdir(exist_ok=True)
    now = datetime.now(timezone(timedelta(hours=8)))
    report = {'checked_at': now.isoformat(),
              'scope': 'runtime_A01_A07_A10_plus_A02_when_live', 'live_requested': args.live,
              'not_checked_by_this_script': ['A03', 'A04', 'A05', 'A06', 'A08', 'A09'] + ([] if args.live else ['A02'])}
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=65) as client:
        health = client.get('/api/health').raise_for_status().json()
        report['A01'] = {'passed': health['status'] == 'ok' and health['storage'] == 'ok' and client.get('/').status_code == 200,
                         'model_configured': health['model_configured']}
        if args.live:
            report['A02'] = check_live(client) if health['model_configured'] else [{'passed': False, 'reason': 'not_configured'}]
    report['A07'] = check_restart()
    report['A10'] = check_secrets()
    passed = all(report[key]['passed'] for key in ['A01', 'A07', 'A10'])
    if args.live:
        passed = passed and all(r['passed'] for r in report['A02'])
    report['passed'] = passed
    target = APP_ROOT / 'runtime' / 'acceptance-verification.json'
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    # 保留每次证据，避免后续非live复测覆盖此前的真实模型失败记录。
    archive = target.with_name('acceptance-verification-' + now.strftime('%Y%m%dT%H%M%S%f') + '.json')
    archive.write_text(rendered, encoding='utf-8')
    target.write_text(rendered, encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
