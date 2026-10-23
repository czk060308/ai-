"""SQLite持久化：需求、资源、草案和事件是业务权威状态。

时间戳保存为带UTC偏移的ISO文本；页面另按北京时间显示。
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from sqlalchemy import JSON, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid4().hex}'


class Base(DeclarativeBase):
    pass


class Need(Base):
    """保存原文、当前结构化字段、证据及编辑版本。"""
    __tablename__ = 'needs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    raw_text: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    extraction_status: Mapped[str] = mapped_column(String)
    extraction_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
    updated_at: Mapped[str] = mapped_column(String, default=utc_now)


class PlanDraft(Base):
    """保存不可被新版本静默覆盖的草案快照，不代表正式预约。"""
    __tablename__ = 'plan_drafts'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    need_id: Mapped[str] = mapped_column(String, index=True)
    need_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)


class Resource(Base):
    """资源目录记录；合成数据与真实资料通过data_type区分。"""
    __tablename__ = 'resources'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    data_type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    """记录实际业务动作，不记录模型内部推理或密钥。"""
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    object_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)


def make_storage(path: str):
    """为指定数据库创建引擎和会话工厂，测试可独立使用临时路径。"""
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    connect_args = {'check_same_thread': False, 'timeout': 15, 'isolation_level': 'DEFERRED'}
    # Python 3.12+显式固定驱动模式，避免未来默认autocommit变化造成重复BEGIN。
    if hasattr(sqlite3, 'LEGACY_TRANSACTION_CONTROL'):
        connect_args['autocommit'] = sqlite3.LEGACY_TRANSACTION_CONTROL
    engine = create_engine('sqlite:///' + Path(path).resolve().as_posix(), connect_args=connect_args)

    @event.listens_for(engine, 'connect')
    def configure(dbapi_connection, _):
        # WAL允许读写更好地共存；busy_timeout给并发写入有限等待时间。
        dbapi_connection.execute('PRAGMA journal_mode=WAL')
        dbapi_connection.execute('PRAGMA foreign_keys=ON')
        dbapi_connection.execute('PRAGMA busy_timeout=15000')

    return engine, sessionmaker(engine, expire_on_commit=False)


def add_event(db, object_id: str, action: str, **payload):
    """沿用调用者事务，保证业务变更与对应事件一起提交或回滚。"""
    db.add(Event(id=new_id('evt'), object_id=object_id, action=action, payload=payload))


@contextmanager
def immediate_session(sessions):
    """SQLite专用写事务：新会话先取写锁，再读版本、生成并提交草案。

    集中管理BEGIN/commit/rollback，不与Session.begin()嵌套；异常时连同
    草案事件一起回滚。其他数据库不能复用此SQLite事务策略。
    """
    with sessions() as db:
        try:
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
