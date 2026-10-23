"""领域数据约定：需求字段、版本输入、未知项与合成演示。

未知信息保留为None；候选成员有空与接受任务是两个独立事实。
本模块不调用模型、数据库或外部服务。
"""

from datetime import date, time
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCENE_ID = 'care_visit_day'
DEMO_INPUT = '2026年10月24日上午9点要到医院，家里老人需要有人陪同。我上午没空，妹妹8点到12点有空，回来后还需要安排午餐。生活服务预算150元，具体交通时间还没有确认。'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CostItem(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    amount: float | None = Field(default=None, ge=0, le=1000000, allow_inf_nan=False)


class NeedFields(StrictModel):
    """模型抽取与用户核对共用的Schema，所有时刻按北京时间解释。"""
    scene_id: Literal['care_visit_day'] = SCENE_ID
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'
    service_date: date | None = None
    arrival_deadline: time | None = None
    region: str | None = Field(default=None, max_length=120)
    origin: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, max_length=200)
    meeting_point: str | None = Field(default=None, max_length=200)
    care_recipient: str | None = Field(default=None, max_length=80)
    accompaniment_required: bool | None = None
    participant_name: str | None = Field(default=None, max_length=80)
    availability_start: time | None = None
    availability_end: time | None = None
    acceptance_status: Literal['unknown', 'confirmed', 'declined'] = 'unknown'
    requester_unavailable: str | None = Field(default=None, max_length=200)
    transport: str | None = Field(default=None, max_length=100)
    travel_minutes: int | None = Field(default=None, gt=0, le=1440)
    return_time: time | None = None
    meal_required: bool | None = None
    meal_time: time | None = None
    meal_people: int | None = Field(default=None, ge=1, le=30)
    diet_notes: str | None = Field(default=None, max_length=300)
    budget_limit: float | None = Field(default=None, ge=0, le=1000000, allow_inf_nan=False)
    currency: Literal['CNY'] = 'CNY'
    budget_scope: str | None = Field(default=None, max_length=200)
    costs: list[CostItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def ordered_times(self):
        """首版只支持当日窗口，拒绝倒序或混入其他时区的时刻。"""
        if self.availability_start and self.availability_end:
            if self.availability_start >= self.availability_end:
                raise ValueError('可用结束时间须晚于开始时间；V0.1暂不支持跨日窗口')
        for value in [self.arrival_deadline, self.availability_start, self.availability_end, self.return_time, self.meal_time]:
            if value and value.tzinfo:
                raise ValueError('时刻请使用北京时间HH:MM，不附加其他时区')
        return self


class NeedCreate(StrictModel):
    raw_text: str = Field(min_length=2, max_length=6000)
    mode: Literal['model', 'manual', 'demo'] = 'model'


class NeedPatch(StrictModel):
    """客户端必须带上读取时的版本，避免较旧表单覆盖新编辑。"""
    expected_version: int = Field(ge=1)
    fields: NeedFields


class DraftCreate(StrictModel):
    expected_version: int = Field(ge=1)
    include_demo: bool = False


class RuleStatus(StrEnum):
    PASS = 'pass'
    CONFLICT = 'conflict'
    UNKNOWN = 'unknown'
    NOT_APPLICABLE = 'not_applicable'


def demo_fields() -> NeedFields:
    """内置样例的人工标注字段；只能用于显式demo模式。"""
    return NeedFields(
        service_date='2026-10-24', arrival_deadline='09:00',
        care_recipient='家里老人', accompaniment_required=True,
        participant_name='妹妹', availability_start='08:00', availability_end='12:00',
        requester_unavailable='当日上午不可用', meal_required=True, budget_limit=150,
    )


DEMO_EVIDENCE = {
    'service_date': '2026年10月24日', 'arrival_deadline': '上午9点要到医院',
    'care_recipient': '家里老人', 'accompaniment_required': '需要有人陪同',
    'participant_name': '妹妹', 'availability_start': '妹妹8点到12点有空',
    'availability_end': '妹妹8点到12点有空', 'requester_unavailable': '我上午没空',
    'meal_required': '回来后还需要安排午餐', 'budget_limit': '生活服务预算150元',
}


def missing_fields(f: NeedFields) -> list[dict]:
    """根据当前需求生成缺项，而非把模板默认值补成用户事实。"""
    items = []
    labels = {
        'service_date': '服务日期', 'arrival_deadline': '到院截止时间',
        'region': '服务地区', 'origin': '出发地点', 'destination': '医院目的地',
        'meeting_point': '集合地点', 'transport': '交通方式', 'travel_minutes': '单程交通时长',
        'return_time': '预计返家时间', 'budget_limit': '生活服务预算', 'budget_scope': '预算包含的费用',
    }
    if f.accompaniment_required is not False:
        labels.update({'participant_name': '候选陪同人', 'availability_start': '陪同人可用起点', 'availability_end': '陪同人可用终点'})
    for field, label in labels.items():
        if getattr(f, field) is None:
            items.append({'field': field, 'label': label, 'reason': f'{label}尚未提供，保留待确认'})
    if f.accompaniment_required is None:
        items.append({'field': 'accompaniment_required', 'label': '是否需要陪同', 'reason': '需用户核对陪同需求'})
    if f.accompaniment_required is not False and f.acceptance_status == 'unknown':
        items.append({'field': 'acceptance_status', 'label': '陪同接受情况', 'reason': '有空不等于已经接受陪同任务'})
    if f.meal_required is None:
        items.append({'field': 'meal_required', 'label': '是否需要午餐', 'reason': '需用户核对用餐需求'})
    if f.meal_required:
        for field, label in [('meal_time', '午餐时间'), ('meal_people', '用餐人数'), ('diet_notes', '饮食限制说明')]:
            if getattr(f, field) is None:
                items.append({'field': field, 'label': label, 'reason': '尚未提供；请核对后补充，未填写不表示无特殊要求'})
    return items
