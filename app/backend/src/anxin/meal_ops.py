"""志愿者排班、解释型候选匹配、待办和标准操作卡。

仅计算并建议，不自动派单；接受时在写事务内复查冲突。
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from .domain import StrictModel
from .config import APP_ROOT
from .meal_domain import PANYU_TOWNS, MealFields, Versioned, meal_checks, minute
from .resources import region_scope
from .storage import MealCase, Resource, Volunteer, add_event, immediate_session, new_id, utc_now

GUIDE_VERSION = 'meal-volunteer-v1'


class VolunteerCreate(StrictModel):
    code: str = Field(min_length=2, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    data_type: Literal['demo', 'pilot'] = 'demo'
    service_date: date
    town: str
    start: time
    end: time
    consent_confirmed: bool = False

    @model_validator(mode='after')
    def valid(self):
        if self.town not in PANYU_TOWNS or self.start.tzinfo or self.end.tzinfo or self.start >= self.end:
            raise ValueError('镇街或当日可用窗口无效')
        if self.data_type == 'pilot' and not self.consent_confirmed:
            raise ValueError('真实志愿者登记须取得同意，只使用代号')
        return self


class Assignment(Versioned):
    volunteer_id: str


def conflicts(db, payload, exclude_id=None):
    """只以已接受/取餐中任务占用时间，demo与pilot永不相互占用。"""
    volunteer_id = payload.get('volunteer_id')
    f = payload['fields']
    if not volunteer_id or not f.get('planned_pickup') or not f.get('travel_minutes'):
        return []
    start = minute(time.fromisoformat(f['planned_pickup']))
    end = start + f['travel_minutes']
    busy = []
    for record in db.scalars(select(MealCase)):
        p, other = record.payload, record.payload['fields']
        if (record.id == exclude_id or p.get('volunteer_id') != volunteer_id
                or p['data_type'] != payload['data_type'] or p['status'] not in ('accepted', 'picked_up')
                or other.get('service_date') != f.get('service_date')):
            continue
        if not other.get('planned_pickup') or not other.get('travel_minutes'):
            busy.append(record.id)
            continue
        other_start = minute(time.fromisoformat(other['planned_pickup']))
        if start < other_start + other['travel_minutes'] and other_start < end:
            busy.append(record.id)
    return busy


def next_steps(payload, now=None):
    """页面待办是本机即时计算，不声称已发送提醒或电话。"""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    status, fields = payload['status'], payload['fields']
    check = meal_checks(payload)
    if status in ('completed', 'cancelled'):
        return {'priority': 'closed', 'title': '已终结', 'questions': [], 'due_at': None, 'overdue': False}
    if status == 'blocked':
        title = '处理异常并重新核实'
    elif status == 'handed_over':
        title = '联系家庭收集反馈'
    elif status == 'picked_up':
        title = '核对交接结果'
    elif status == 'accepted':
        title = '确认是否已取餐'
    elif check['missing_fields']:
        title = '补问家庭关键信息'
    elif not payload.get('supply_check'):
        title = '联系供餐点核实'
    else:
        title = '解决约束并确认接受'
    questions = [f"请确认{m['label']}？" for m in check['missing_fields']]
    if not payload.get('supply_check'):
        questions += ['当天是否供餐，起止时段是什么？', '是否接受这位服务对象，能否打包由他人代取？',
                      '家属饮食要求能否满足，本次含打包等费用的总价是多少？']
    due_at = None
    due_time = fields.get('planned_pickup') if status == 'accepted' else fields.get('handover_deadline')
    if fields.get('service_date') and due_time:
        due_at = datetime.combine(date.fromisoformat(fields['service_date']), time.fromisoformat(due_time), tzinfo=now.tzinfo)
    overdue = bool(due_at and due_at < now)
    return {'priority': 'urgent' if overdue or status == 'blocked' else 'normal', 'title': title,
            'questions': questions, 'due_at': due_at.isoformat() if due_at else None, 'overdue': overdue,
            'basis': '页面待办，不自动发送外部通知；超时仅提示核对实际情况'}


def meal_ops_router(sessions):
    router = APIRouter(prefix='/api/meal', tags=['助餐运营与复用'])

    def require(db, case_id):
        record = db.get(MealCase, case_id)
        if not record:
            raise HTTPException(404, '未找到助餐记录')
        return record

    @router.get('/source-evidence')
    def source_evidence():
        path = APP_ROOT / 'data/research/panyu-public-evidence.json'
        return json.loads(path.read_text(encoding='utf-8'))

    @router.get('/volunteers')
    def volunteers():
        with sessions() as db:
            return [{'id': v.id, **v.payload} for v in db.scalars(select(Volunteer).order_by(Volunteer.created_at.desc())).all()]

    @router.post('/volunteers', status_code=201)
    def add_volunteer(body: VolunteerCreate):
        with immediate_session(sessions) as db:
            payload = body.model_dump(mode='json')
            for v in db.scalars(select(Volunteer)):
                if all(v.payload[k] == payload[k] for k in ('code', 'data_type', 'service_date')):
                    raise HTTPException(409, '同一代号、用途和日期已登记；请使用原登记，勿重复报名')
            record = Volunteer(id=new_id('vol'), payload=payload)
            db.add(record)
            db.flush()
            add_event(db, record.id, 'volunteer_registered', data_type=body.data_type, service_date=str(body.service_date))
            return {'id': record.id, **record.payload}

    @router.get('/cases/{case_id}/candidates')
    def candidates(case_id: str):
        with sessions() as db:
            case = require(db, case_id)
            f = case.payload['fields']
            result = []
            for v in db.scalars(select(Volunteer).order_by(Volunteer.id)):
                p = v.payload
                if p['data_type'] != case.payload['data_type'] or p['service_date'] != f['service_date'] or p['town'] != f['town']:
                    continue
                proposed = {**case.payload, 'volunteer_id': v.id,
                            'fields': {**f, 'availability_start': p['start'], 'availability_end': p['end'], 'pickup_person': p['code']}}
                checks = meal_checks(proposed)
                overlap = conflicts(db, proposed, case_id)
                reasons = []
                if overlap:
                    reasons.append('与已接受任务取餐—交接区间重叠')
                if any(r['status'] == 'conflict' for r in checks['rules']):
                    reasons.append('人员窗口或当前供餐/预算约束存在冲突')
                ready = checks['ready_to_accept'] and not overlap
                result.append({'id': v.id, **p, 'eligible': ready, 'reasons': reasons or ['同日期同镇街；仍须本次核实及本人明确接受'],
                               'pickup_window': checks['pickup_window'], 'conflicting_cases': overlap})
            return {'items': result, 'basis': '按同日期/镇街、登记窗口和已接受任务解释匹配；不是自动派单'}

    @router.post('/cases/{case_id}/assign')
    def assign(case_id: str, body: Assignment):
        with immediate_session(sessions) as db:
            case = require(db, case_id)
            if case.version != body.expected_version:
                raise HTTPException(409, '版本已变化，请刷新后选择候选人')
            if case.payload['status'] in ('completed', 'cancelled', 'picked_up', 'handed_over'):
                raise HTTPException(409, '当前状态不能直接更换候选人，请先记录异常')
            v = db.get(Volunteer, body.volunteer_id)
            f = case.payload['fields']
            if not v or any(v.payload[k] != x for k, x in (('data_type', case.payload['data_type']), ('service_date', f['service_date']), ('town', f['town']))):
                raise HTTPException(409, '候选人必须与需求用途、日期和镇街一致')
            fields = {**f, 'pickup_person': v.payload['code'], 'availability_start': v.payload['start'], 'availability_end': v.payload['end']}
            evidence = {**case.payload['evidence']}
            for key in ('pickup_person', 'availability_start', 'availability_end'):
                evidence[key] = {'source': 'user_edit', 'quote': '操作者从登记排班选择，尚未确认接受', 'confirmed': True}
            case.payload = {**case.payload, 'fields': fields, 'evidence': evidence, 'volunteer_id': v.id,
                            'volunteer_snapshot': v.payload, 'status': 'draft', 'supply_check': None, 'acceptance': None,
                            'feedback': None}
            case.payload.pop('picked_up', None)
            case.payload.pop('handed_over', None)
            case.version += 1
            case.updated_at = utc_now()
            add_event(db, case.id, 'meal_candidate_selected', volunteer_id=v.id, version=case.version,
                      note='选择仅为候选，原核实与接受已失效')
            return {'id': case.id, 'version': case.version}

    @router.get('/cases/{case_id}/resource-comparison')
    def compare(case_id: str):
        with sessions() as db:
            case = require(db, case_id)
            f = case.payload['fields']
            items = []
            for r in db.scalars(select(Resource).order_by(Resource.id)):
                p = r.payload
                if (region_scope(f['region']) != ('广州市', '番禺区') or p.get('district') != '番禺区' or p.get('town') != f['town']):
                    continue
                current = case.payload.get('supply_check')
                checked = bool(current and current['resource_id'] == r.id)
                items.append({'id': r.id, 'name': p['name'], 'address': p.get('address'), 'source_url': p['source_url'],
                              'historical_external': p.get('source_external_residents'), 'historical_open_days': p.get('source_open_days'),
                              'snapshot_date': p.get('snapshot_date'), 'current_case_checked': checked,
                              'current_quote': current['quoted_total'] if checked else None,
                              'reason': '本次已记录人工核实' if checked else '同镇街历史候选；当天价格、代取和资格仍未知'})
            items.sort(key=lambda x: (not x['current_case_checked'], x['id']))
            return {'items': items, 'total': len(items), 'ranking_basis': '本次已核实优先，其余按固定ID；不声称最近、最便宜或实时可用'}

    @router.get('/board')
    def board():
        with sessions() as db:
            items = []
            for r in db.scalars(select(MealCase).order_by(MealCase.created_at)):
                if r.payload['status'] in ('completed', 'cancelled'):
                    continue
                items.append({'id': r.id, 'version': r.version, 'data_type': r.payload['data_type'], 'status': r.payload['status'],
                              'town': r.payload['fields']['town'], 'service_date': r.payload['fields']['service_date'],
                              **next_steps(r.payload)})
            items.sort(key=lambda x: (x['priority'] != 'urgent', x['due_at'] or '9999'))
            return {'generated_at': utc_now(), 'items': items, 'counts': {kind: sum(i['data_type'] == kind for i in items) for kind in ('pilot', 'demo')},
                    'notifications_sent': False}

    @router.get('/cases/{case_id}/playbook')
    def playbook(case_id: str):
        with sessions() as db:
            r = require(db, case_id)
            p, f = r.payload, r.payload['fields']
            return {'guide_version': GUIDE_VERSION, 'case_id': r.id, 'case_version': r.version,
                    'data_type': p['data_type'], 'next_action': next_steps(p),
                    'contact_script': [f"咨询{f.get('service_date') or '待确认日期'}的{f.get('meal_people') or '待确认'}份午餐。",
                                       '先核实服务资格、供餐起止、打包及他人代取是否允许。',
                                       '转达家庭提供的饮食要求，逐项询问能否满足；不要自行作食疗判断。',
                                       '核实本次含打包等费用总价，说明取餐和交接安排。',
                                       '未明确回答的项目保持未知；本卡不会自动拨号或发送消息。'],
                    'handover_checklist': ['核对取餐份数和包装', '核对约定交接对象与地点（在线下完成）', '实际交接后据实记录，受阻先记录原因', '收集家庭反馈，评价可不提供'],
                    'replication_tasks': ['仅看操作卡完成建档和补问', '独立找出一个时间或预算冲突', '记录受阻并重排，确认旧承诺失效', '完成合成闭环，检查真实试点数未增加'],
                    'evidence_basis': '操作辅助卡，不证明已经联系或完成服务；复制复用需要另一名真实操作者验证'}

    return router
