"""助餐接力用例：人工核实、版本化状态机、异常重排与脱敏试点统计。

所有状态均为操作者填报，不向商家派单，不自动拨号、付款或发送消息。
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from .meal_domain import (MEAL_SAMPLE, PANYU_TOWNS, MealAction, MealCreate, MealEdit,
                          MealFeedback, MealFields, SupplyCheck, demo_meal_fields,
                          meal_checks, meal_prompt, parse_meal)
from .model_gateway import ModelFailure, extract_need
from .resources import match_resource, present_resource
from .storage import Event, MealCase, Resource, add_event, immediate_session, new_id, utc_now

TERMINAL = {'completed', 'cancelled'}


def meal_router(sessions, config):
    router = APIRouter(prefix='/api/meal', tags=['助餐接力'])

    def require(db, case_id, version=None):
        record = db.get(MealCase, case_id)
        if not record:
            raise HTTPException(404, '未找到这次助餐接力')
        if version is not None and record.version != version:
            raise HTTPException(409, '接力已被其他操作修改，请重新载入后再操作')
        return record

    def serialize(record):
        return {**record.payload, 'id': record.id, 'version': record.version,
                'created_at': record.created_at, 'updated_at': record.updated_at,
                'checks': meal_checks(record.payload)}

    def save(db, record, payload, action, **event):
        record.payload = payload
        record.version += 1
        record.updated_at = utc_now()
        add_event(db, record.id, action, version=record.version, **event)
        db.flush()
        return serialize(record)

    def editable(record):
        if record.payload['status'] in TERMINAL | {'picked_up', 'handed_over'}:
            raise HTTPException(409, '已取餐或终结的接力不能直接改安排；异常请先记录受阻，再核实重排')

    @router.get('/demo')
    def demo():
        return {'raw_text': MEAL_SAMPLE, 'fields': demo_meal_fields().model_dump(mode='json'), 'data_type': 'demo'}

    @router.get('/resources')
    def resources(town: str | None = None, query: str = '', limit: int = 20):
        if town and town not in PANYU_TOWNS:
            raise HTTPException(422, '请选择公开目录支持的番禺镇街')
        if not 1 <= limit <= 50 or len(query) > 80:
            raise HTTPException(422, '资源查询范围无效')
        with sessions() as db:
            records = db.scalars(select(Resource).where(Resource.data_type == 'public').order_by(Resource.id)).all()
            items = [r.payload for r in records if r.payload.get('city') == '广州市' and r.payload.get('district') == '番禺区'
                     and (not town or r.payload.get('town') == town)
                     and (not query or query in r.payload['name'] or query in r.payload.get('address', ''))]
        return {'items': [present_resource(r, '广州市番禺区') for r in items[:limit]], 'total': len(items),
                'towns': PANYU_TOWNS, 'scope': 'public_historical_directory', 'snapshot_date': '2025-02-05'}

    @router.get('/stats')
    def stats():
        with sessions() as db:
            records = db.scalars(select(MealCase)).all()
            pilot = [r for r in records if r.payload['data_type'] == 'pilot']
            counts = Counter(r.payload['status'] for r in pilot)
            ratings = [r.payload['feedback']['rating'] for r in pilot if r.payload.get('feedback') and r.payload['feedback']['rating'] is not None]
            return {'pilot_cases': len(pilot), 'demo_cases': len(records) - len(pilot),
                    'families': len({r.payload['family_code'] for r in pilot}), 'status_counts': dict(counts),
                    'completed': counts['completed'], 'completion_denominator': len(pilot),
                    'completion_rate': counts['completed'] / len(pilot) if pilot else None,
                    'feedback_count': sum(bool(r.payload.get('feedback')) for r in pilot),
                    'rating_count': len(ratings), 'rating_mean': sum(ratings) / len(ratings) if ratings else None,
                    'evidence_basis': 'operator_reported_not_independently_verified',
                    'notes': '仅统计创建时标记真实试点且确认同意的记录；完成率分母为全部试点需求，含待执行、取消与受阻。演示完全排除。'}

    @router.get('/export')
    def export():
        # 默认导出仅含评估必要字段，不导出原文、家庭代号、人员、地址、备注和引文。
        with sessions() as db:
            records = db.scalars(select(MealCase).order_by(MealCase.created_at)).all()
            items = []
            for r in records:
                p, f = r.payload, r.payload['fields']
                items.append({'case_id': r.id, 'data_type': p['data_type'], 'status': p['status'],
                              'service_date': f['service_date'], 'town': f['town'], 'meal_people': f['meal_people'],
                              'version': r.version, 'created_at': r.created_at, 'updated_at': r.updated_at,
                              'supply_checked': bool(p.get('supply_check')), 'resource_id': p.get('supply_check', {}).get('resource_id') if p.get('supply_check') else None,
                              'feedback_received': bool(p.get('feedback')), 'rating': (p.get('feedback') or {}).get('rating'),
                              'actual_cost': (p.get('feedback') or {}).get('actual_cost')})
            return {'schema_version': 1, 'generated_at': utc_now(), 'stats': stats(), 'cases': items,
                    'evidence_basis': '人工填报，非独立核验；demo不能作为真实服务成果'}

    @router.get('/cases')
    def history():
        with sessions() as db:
            return [{'id': r.id, 'version': r.version, 'status': r.payload['status'],
                     'data_type': r.payload['data_type'], 'service_date': r.payload['fields']['service_date'],
                     'town': r.payload['fields']['town'], 'updated_at': r.updated_at}
                    for r in db.scalars(select(MealCase).order_by(MealCase.updated_at.desc()).limit(100)).all()]

    @router.post('/cases', status_code=201)
    async def create(body: MealCreate):
        payload = {'raw_text': body.raw_text, 'fields': MealFields().model_dump(mode='json'),
                   'data_type': body.data_type, 'family_code': body.family_code if body.data_type == 'pilot' else None,
                   'consent_confirmed': body.consent_confirmed, 'status': 'draft', 'evidence': {},
                   'extraction_status': 'processing' if body.mode == 'model' else body.mode,
                   'extraction_message': '原文已保存', 'extraction_review': {},
                   'supply_check': None, 'acceptance': None, 'feedback': None, 'latest_exception': None}
        with sessions.begin() as db:
            record = MealCase(id=new_id('meal'), payload=payload)
            db.add(record)
            db.flush()
            case_id = record.id
            add_event(db, case_id, 'meal_created', mode=body.mode, data_type=body.data_type)
        status, message, evidence, review = body.mode, '手工填写，未调用模型', {}, {}
        fields = MealFields()
        if body.mode == 'demo':
            fields, message = demo_meal_fields(), '合成助餐演示，未调用模型，不计入真实试点'
        elif body.mode == 'model':
            try:
                fields, evidence = await extract_need(body.raw_text, config, parser=parse_meal, prompt=meal_prompt())
                status, message, review = 'succeeded', '真实API识别完成，请逐项核对', evidence.review
            except ModelFailure as exc:
                status, message, review = exc.code, exc.message, getattr(exc, 'review', {})
        with immediate_session(sessions) as db:
            record = require(db, case_id)
            if record.version == 1:
                current = {**record.payload, 'fields': fields.model_dump(mode='json'), 'evidence': dict(evidence),
                           'extraction_status': status, 'extraction_message': message, 'extraction_review': review}
                return save(db, record, current, 'meal_extraction_finished', status=status, review=review)
            add_event(db, case_id, 'meal_extraction_discarded', status=status)
            return serialize(record)

    @router.get('/cases/{case_id}')
    def read(case_id: str):
        with sessions() as db:
            return serialize(require(db, case_id))

    @router.patch('/cases/{case_id}')
    def edit(case_id: str, body: MealEdit):
        with immediate_session(sessions) as db:
            record = require(db, case_id, body.expected_version)
            editable(record)
            values = body.fields.model_dump(mode='json')
            changed = [k for k in values if values[k] != record.payload['fields'].get(k)]
            if not changed:
                return serialize(record)
            evidence = {**record.payload['evidence']}
            for key in changed:
                evidence[key] = {'source': 'user_edit', 'quote': '操作者核对补充', 'confirmed': True}
            # 不迁移旧承诺：任何字段变化都要求重新核实供餐并重新接受。
            payload = {**record.payload, 'fields': values, 'evidence': evidence, 'status': 'draft',
                       'supply_check': None, 'acceptance': None, 'feedback': None}
            payload.pop('picked_up', None)
            payload.pop('handed_over', None)
            return save(db, record, payload, 'meal_replanned', fields=changed, previous_status=record.payload['status'])

    @router.post('/cases/{case_id}/verify')
    def verify(case_id: str, body: SupplyCheck):
        with immediate_session(sessions) as db:
            record = require(db, case_id, body.expected_version)
            editable(record)
            fields = record.payload['fields']
            resource = db.get(Resource, body.resource_id)
            if (not resource or resource.payload.get('district') != '番禺区'
                    or not match_resource(resource.payload, fields['region'], False)
                    or fields['town'] != resource.payload.get('town')):
                raise HTTPException(409, '核实资源须与已填写的番禺服务镇街一致；跨镇安排请先核对服务地区')
            if fields['service_date'] != body.service_date.isoformat():
                raise HTTPException(409, '供餐核实必须针对本次服务日期')
            check = body.model_dump(mode='json', exclude={'expected_version'})
            check.update(checked_at=utc_now(), resource_snapshot=resource.payload,
                         basis='operator_reported_not_provider_booking')
            payload = {**record.payload, 'supply_check': check, 'acceptance': None, 'status': 'verified'}
            payload.pop('picked_up', None)
            payload.pop('handed_over', None)
            return save(db, record, payload, 'meal_supply_verified', resource_id=resource.id, check=check)

    @router.post('/cases/{case_id}/actions')
    def action(case_id: str, body: MealAction):
        with immediate_session(sessions) as db:
            record = require(db, case_id, body.expected_version)
            payload = dict(record.payload)
            state = payload['status']
            if state in TERMINAL:
                raise HTTPException(409, '这次接力已经终结，不能继续修改状态')
            action_note = {'actor': body.actor, 'note': body.note, 'at': utc_now(), 'basis': 'operator_reported'}
            if body.action == 'accept':
                if state != 'verified' or not meal_checks(payload)['ready_to_accept']:
                    raise HTTPException(409, '请先补齐字段、核实供餐并解决时间/预算冲突，再记录接受')
                payload.update(status='accepted', acceptance=action_note)
            elif body.action in ('picked_up', 'handed_over'):
                required = 'accepted' if body.action == 'picked_up' else 'picked_up'
                if state != required:
                    raise HTTPException(409, '必须按确认接受、已取餐、已交接的顺序记录')
                today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                if payload['data_type'] == 'pilot' and payload['fields']['service_date'] != today:
                    raise HTTPException(409, '真实取餐与交接仅可记录当天服务；未来安排不能提前记为完成')
                payload['status'] = body.action
                payload[body.action] = action_note
            elif body.action == 'block':
                payload.update(status='blocked', latest_exception=action_note, acceptance=None)
            else:
                payload.update(status='cancelled', cancellation=action_note)
            return save(db, record, payload, 'meal_' + body.action, **action_note)

    @router.post('/cases/{case_id}/feedback')
    def feedback(case_id: str, body: MealFeedback):
        with immediate_session(sessions) as db:
            record = require(db, case_id, body.expected_version)
            if record.payload['status'] != 'handed_over':
                raise HTTPException(409, '实际交接记录后才能收集反馈并完成闭环')
            note = body.model_dump(mode='json', exclude={'expected_version'})
            note.update(recorded_at=utc_now(), basis='operator_reported')
            payload = {**record.payload, 'status': 'completed', 'feedback': note}
            return save(db, record, payload, 'meal_feedback_received', feedback=note)

    @router.get('/cases/{case_id}/events')
    def events(case_id: str):
        with sessions() as db:
            require(db, case_id)
            return [{'id': r.id, 'action': r.action, 'payload': r.payload, 'created_at': r.created_at}
                    for r in db.scalars(select(Event).where(Event.object_id == case_id).order_by(Event.created_at)).all()]

    return router
