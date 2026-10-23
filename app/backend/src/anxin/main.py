"""FastAPI用例入口：协调领域规则、模型网关与事务存储。

构建后的前端也由此提供；当前仅面向本机开发，不提供家庭鉴权。
"""

import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text, update

from .config import APP_ROOT, Settings, settings
from .domain import DEMO_EVIDENCE, DEMO_INPUT, DraftCreate, NeedCreate, NeedFields, NeedPatch, demo_fields, missing_fields
from .model_gateway import ModelFailure, extract_need
from .planning import make_plan
from .storage import Base, Event, Need, PlanDraft, Resource, add_event, make_storage, new_id, utc_now

logger = logging.getLogger('anxin')


def create_app(config: Settings | None = None) -> FastAPI:
    """应用工厂允许测试注入临时数据库与空模型配置，隔离真实服务。"""
    config = config or settings
    engine, sessions = make_storage(config.database_path)

    @asynccontextmanager
    async def lifespan(app):
        # 种子只补缺少的ID，重启不清空数据库或覆盖既有资源。
        Base.metadata.create_all(engine)
        seeds = json.loads((APP_ROOT / 'data/seeds/resources.json').read_text(encoding='utf-8'))
        with sessions.begin() as db:
            for record in seeds:
                if not db.get(Resource, record['id']):
                    db.add(Resource(id=record['id'], category=record['category'], region=record['region'], data_type=record['data_type'], payload=record))
        yield
        engine.dispose()

    app = FastAPI(title='安心接力 API', version='0.1.0', lifespan=lifespan)
    app.state.sessions = sessions

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        # 这是本机开发的跨站写入限制，不能替代后续登录和对象级授权。
        request.state.trace_id = uuid4().hex[:12]
        origin = request.headers.get('origin')
        allowed = {'http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:4173', 'http://localhost:4173', 'http://127.0.0.1:8000', 'http://localhost:8000'}
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in allowed:
            return JSONResponse(status_code=403, content={'message': '本机开发版不接受跨站写入', 'trace_id': request.state.trace_id})
        response = await call_next(request)
        response.headers['X-Trace-ID'] = request.state.trace_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'message': str(exc.detail), 'trace_id': request.state.trace_id})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        errors = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()]
        return JSONResponse(status_code=422, content={'message': '字段格式有误，请检查日期、时段与金额', 'errors': errors, 'trace_id': request.state.trace_id})

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error('request_failed trace=%s error_type=%s', request.state.trace_id, type(exc).__name__)
        return JSONResponse(status_code=500, content={'message': '服务处理失败，请保留当前输入并重试', 'trace_id': request.state.trace_id})

    def require_need(db, need_id):
        record = db.get(Need, need_id)
        if not record:
            raise HTTPException(404, '未找到这份需求')
        return record

    def serialize_need(record):
        return {
            'id': record.id, 'raw_text': record.raw_text, 'fields': record.fields,
            'evidence': record.evidence, 'version': record.version,
            'extraction_status': record.extraction_status, 'extraction_message': record.extraction_message,
            'missing_fields': missing_fields(NeedFields.model_validate(record.fields)),
            'created_at': record.created_at, 'updated_at': record.updated_at,
        }

    def serialize_plan(record, current_version):
        return {**record.payload, 'id': record.id, 'need_id': record.need_id,
                'need_version': record.need_version, 'version': record.version,
                'created_at': record.created_at, 'is_stale': record.need_version != current_version}

    def resources_for(db, region, include_demo, category=None):
        if not region:
            return []
        query = select(Resource).where(Resource.region == region)
        if not include_demo:
            query = query.where(Resource.data_type != 'demo')
        if category:
            query = query.where(Resource.category == category)
        return [r.payload for r in db.scalars(query.order_by(Resource.id)).all()]

    @app.get('/api/health')
    def health():
        # 对前端仅暴露配置是否存在，不返回地址、密钥或数据库路径。
        with sessions() as db:
            db.execute(text('SELECT 1'))
        return {'status': 'ok', 'storage': 'ok', 'version': '0.1.0',
                'model_configured': config.model_configured, 'access_mode': 'local_development',
                'timezone': 'Asia/Shanghai'}

    @app.get('/api/demo')
    def demo():
        return {'raw_text': DEMO_INPUT, 'fields': demo_fields().model_dump(mode='json'), 'data_type': 'demo'}

    @app.post('/api/needs', status_code=201)
    async def create_need(body: NeedCreate):
        if body.mode == 'demo' and body.raw_text != DEMO_INPUT:
            raise HTTPException(400, '演示字段只适用于内置样例，修改后的需求请用自动识别或手工填写')
        record = Need(id=new_id('need'), raw_text=body.raw_text, fields=NeedFields().model_dump(mode='json'),
                      evidence={}, extraction_status='manual', extraction_message='手工填写模式，未调用模型')
        # 外部请求之前先保存原文，供应商故障也不会丢掉用户的输入。
        with sessions.begin() as db:
            db.add(record)
            add_event(db, record.id, 'need_created', mode=body.mode)
        if body.mode == 'demo':
            fields = demo_fields()
            evidence = {key: {'source': 'demo_fixture', 'quote': quote, 'confirmed': False} for key, quote in DEMO_EVIDENCE.items()}
            status, message = 'demo', '已载入合成演示字段，未调用模型，请核对后生成草案'
        elif body.mode == 'model':
            try:
                fields, evidence = await extract_need(body.raw_text, config)
                status, message = 'succeeded', '真实API识别完成，字段仍需用户核对'
            except ModelFailure as exc:
                fields, evidence = NeedFields(), {}
                status, message = exc.code, exc.message
        else:
            fields, evidence, status, message = NeedFields(), {}, 'manual', '手工填写模式，未调用模型'
        with sessions.begin() as db:
            # 识别期间若发生用户编辑，迟到的模型结果不能覆盖新版本。
            changed = db.execute(update(Need).where(Need.id == record.id, Need.version == 1).values(
                fields=fields.model_dump(mode='json'), evidence=evidence,
                extraction_status=status, extraction_message=message, updated_at=utc_now()))
            add_event(db, record.id, 'extraction_finished' if changed.rowcount else 'extraction_discarded', status=status)
        with sessions() as db:
            return serialize_need(require_need(db, record.id))

    @app.get('/api/needs')
    def list_needs():
        with sessions() as db:
            records = db.scalars(select(Need).order_by(Need.created_at.desc()).limit(20)).all()
            return [{'id': r.id, 'raw_text': r.raw_text, 'version': r.version, 'updated_at': r.updated_at,
                     'extraction_status': r.extraction_status} for r in records]

    @app.get('/api/needs/{need_id}')
    def get_need(need_id: str):
        with sessions() as db:
            return serialize_need(require_need(db, need_id))

    @app.patch('/api/needs/{need_id}')
    def patch_need(need_id: str, body: NeedPatch):
        # 通过带版本条件的UPDATE执行乐观并发控制；冲突返回409。
        with sessions.begin() as db:
            current = require_need(db, need_id)
            evidence = dict(current.evidence)
            values = body.fields.model_dump(mode='json')
            changed_fields = []
            for key, value in values.items():
                if value != current.fields.get(key):
                    evidence[key] = {'source': 'user_edit', 'quote': '用户补充或修改', 'confirmed': True}
                    changed_fields.append(key)
                elif key in evidence:
                    evidence[key] = {**evidence[key], 'confirmed': True}
            updated = db.execute(update(Need).where(Need.id == need_id, Need.version == body.expected_version).values(
                fields=values, evidence=evidence, version=body.expected_version + 1, updated_at=utc_now()))
            if updated.rowcount != 1:
                raise HTTPException(409, '需求已被其他操作修改，请重新载入后再保存')
            add_event(db, need_id, 'fields_reviewed', fields=changed_fields, version=body.expected_version + 1)
        with sessions() as db:
            return serialize_need(require_need(db, need_id))

    @app.get('/api/resources')
    def list_resources(region: str | None = None, include_demo: bool = False, category: str | None = None):
        with sessions() as db:
            return resources_for(db, region, include_demo, category)

    @app.post('/api/needs/{need_id}/plan-drafts', status_code=201)
    def create_draft(need_id: str, body: DraftCreate):
        with sessions.begin() as db:
            # 在同一写事务中检查需求版本并保存草案，避免编辑与生成交错。
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            need = require_need(db, need_id)
            if need.version != body.expected_version:
                raise HTTPException(409, '需求版本已变化，请载入最新字段后再生成')
            fields = NeedFields.model_validate(need.fields)
            resources = resources_for(db, fields.region, body.include_demo)
            if fields.meal_required is not True:
                resources = [r for r in resources if r['category'] != 'meal']
            if fields.accompaniment_required is False:
                resources = [r for r in resources if r['category'] != 'accompany']
            payload = make_plan(fields, need.evidence, resources)
            previous = db.scalars(select(PlanDraft).where(PlanDraft.need_id == need_id).order_by(PlanDraft.version.desc())).first()
            if previous and previous.need_version == need.version and previous.payload == payload:
                return serialize_plan(previous, need.version)
            draft = PlanDraft(id=new_id('plan'), need_id=need_id, need_version=need.version,
                              version=previous.version + 1 if previous else 1, payload=payload)
            db.add(draft)
            db.flush()
            add_event(db, need_id, 'draft_saved', plan_id=draft.id, version=draft.version)
            return serialize_plan(draft, need.version)

    @app.get('/api/needs/{need_id}/plans')
    def list_plans(need_id: str):
        with sessions() as db:
            need = require_need(db, need_id)
            return [serialize_plan(r, need.version) for r in db.scalars(select(PlanDraft).where(PlanDraft.need_id == need_id).order_by(PlanDraft.version.desc()).limit(20)).all()]

    @app.get('/api/plans/{plan_id}')
    def get_plan(plan_id: str):
        with sessions() as db:
            record = db.get(PlanDraft, plan_id)
            if not record:
                raise HTTPException(404, '未找到这份草案')
            need = require_need(db, record.need_id)
            return serialize_plan(record, need.version)

    @app.get('/api/needs/{need_id}/events')
    def get_events(need_id: str):
        with sessions() as db:
            require_need(db, need_id)
            return [{'id': r.id, 'action': r.action, 'payload': r.payload, 'created_at': r.created_at}
                    for r in db.scalars(select(Event).where(Event.object_id == need_id).order_by(Event.created_at.desc()).limit(50)).all()]

    @app.get('/api/{unmatched:path}')
    def missing_api(unmatched: str):
        raise HTTPException(404, '接口不存在')

    web_dist = APP_ROOT / 'apps/web/dist'
    if web_dist.is_dir():
        app.mount('/', StaticFiles(directory=web_dist, html=True), name='web')
    return app


app = create_app()
