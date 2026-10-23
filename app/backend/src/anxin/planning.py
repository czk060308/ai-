"""确定性规划与规则，不依赖模型自由判断约束是否满足。

这里只生成带未知条件的草案；不会创建预约、认领或派单副作用。
"""

from .domain import NeedFields, missing_fields


def hm(value) -> str:
    return value.strftime('%H:%M') if value else '待确认'


def minutes(value) -> int:
    return value.hour * 60 + value.minute


def evaluate_rules(f: NeedFields) -> list[dict]:
    """返回通过／冲突／未知／不适用；未知不能被合并为通过。"""
    rules = []

    def add(code, status, title, detail):
        rules.append({'code': code, 'status': status, 'title': title, 'detail': detail})

    missing = missing_fields(f)
    add('information', 'unknown' if missing else 'pass', '关键信息', f'仍有{len(missing)}项待补充或核对' if missing else '当前字段已填写，仍需核实服务供给')
    arrival = f.arrival_deadline
    start = f.availability_start
    end = f.availability_end
    if f.accompaniment_required is False:
        add('availability', 'not_applicable', '陪同时段', '用户明确不需要陪同')
        add('acceptance', 'not_applicable', '陪同接受情况', '无需安排陪同人')
    else:
        if arrival and start and minutes(start) > minutes(arrival):
            add('availability', 'conflict', '陪同时段冲突', f'候选人{hm(start)}才有空，但要求{hm(arrival)}前到院')
        elif arrival and start and f.travel_minutes and minutes(start) + f.travel_minutes > minutes(arrival):
            add('availability', 'conflict', '出发时间冲突', f'可用起点{hm(start)}加单程{f.travel_minutes}分钟，晚于{hm(arrival)}到院要求')
        elif end and arrival and minutes(end) <= minutes(arrival):
            add('availability', 'conflict', '陪同时段不足', '候选人可用窗口在到院时或之前结束，无法覆盖到院后的陪同')
        elif end and f.return_time and minutes(end) < minutes(f.return_time):
            add('availability', 'conflict', '返家陪同缺口', f'候选人{hm(end)}结束可用，早于预计{hm(f.return_time)}返家')
        elif all([arrival, start, end, f.travel_minutes, f.return_time]):
            add('availability', 'pass', '陪同时段', '已填时段覆盖预计行程；实际耗时仍需核实')
        else:
            add('availability', 'unknown', '陪同时段待确认', '缺少完整时长或窗口，尚不能确认能覆盖行程')
        add('acceptance', 'pass' if f.acceptance_status == 'confirmed' else ('conflict' if f.acceptance_status == 'declined' else 'unknown'),
            '陪同接受情况', {'confirmed': '用户填报已确认接受；本系统尚未提供成员认领核验', 'declined': '候选人已拒绝，需重新选择', 'unknown': '有空不等于已接受，候选人尚未确认'}[f.acceptance_status])
    if f.return_time and arrival and minutes(f.return_time) <= minutes(arrival):
        add('return_order', 'conflict', '返家时间冲突', '返家时间必须晚于到院时间；V0.1按当日场景检查')
    if f.meal_required and f.meal_time and f.return_time:
        add('meal_order', 'conflict' if minutes(f.meal_time) < minutes(f.return_time) else 'pass', '返家与午餐衔接', '午餐时间早于返家，需调整' if minutes(f.meal_time) < minutes(f.return_time) else '午餐不早于预计返家时间')
    elif f.meal_required:
        add('meal_order', 'unknown', '返家与午餐衔接', '返家或用餐时刻未知，暂不能核实时序')
    # 已知小计和预计总价分开：缺少报价时，不能把未报费用按0元计算。
    known = round(sum(c.amount for c in f.costs if c.amount is not None), 2)
    unknown = not f.costs or any(c.amount is None for c in f.costs)
    if f.budget_limit is not None and known > f.budget_limit:
        add('budget', 'conflict', '已知费用超预算', f'已知费用小计{known:g}元，高于预算{f.budget_limit:g}元')
    elif f.budget_limit is None or not f.budget_scope or unknown:
        add('budget', 'unknown', '费用尚未核实', '价格、费用清单或预算范围不完整；未知费用不按0元计算')
    else:
        add('budget', 'pass', '已填写费用清单', f'用户填写的费用小计{known:g}元未超预算；未列费用与实际价格仍待核实')
    add('resource_verification', 'unknown', '资源与本次可用性', '当前没有完成本次服务核实的供给，演示资料不代表真实商家或预约')
    return rules


def make_plan(f: NeedFields, evidence: dict, resources: list[dict]) -> dict:
    """展开场景模板并验证依赖，返回可持久化的JSON兼容快照。"""
    tasks = []

    def add(task_id, title, timing, deps, fields, reason, owner=None):
        sources = [{'field': key, **evidence[key]} for key in fields if key in evidence]
        tasks.append({'id': task_id, 'title': title, 'timing': timing, 'dependencies': deps,
                      'owner_candidate': owner, 'acceptance_status': f.acceptance_status if owner else 'unknown',
                      'status': 'draft', 'reason': reason, 'evidence': sources,
                      'template_source': 'care_visit_day / V0.1 场景模板建议'})

    add('prepare', '核对出行与陪同信息', '出发前，具体时间待确认', [],
        ['region', 'origin', 'destination', 'accompaniment_required'], '核对地点、路线及家属安排；不包含医疗处置建议')
    departure = None
    if f.arrival_deadline and f.travel_minutes:
        total = minutes(f.arrival_deadline) - f.travel_minutes
        if total >= 0:
            departure = f'{total // 60:02d}:{total % 60:02d}'
    add('outbound', '集合并前往医院', (f'{departure}前出发（仅按填写时长倒推，未含缓冲）' if departure else '出发时间待确认'),
        ['prepare'], ['origin', 'destination', 'travel_minutes', 'arrival_deadline'], '路线与集合信息仍需核对')
    previous = 'outbound'
    if f.accompaniment_required is not False:
        add('accompany', '到院与复诊陪同', (f'{hm(f.arrival_deadline)}前到达；结束时间未知' if f.arrival_deadline else '到院与结束时间待确认'),
            ['outbound'], ['arrival_deadline', 'participant_name', 'availability_start', 'availability_end', 'acceptance_status'],
            '候选人仅作安排建议；草案不代表已经接受或预约', f.participant_name)
        previous = 'accompany'
    else:
        add('arrival', '到院事项', f'{hm(f.arrival_deadline)}前到达' if f.arrival_deadline else '到院时间待确认',
            ['outbound'], ['arrival_deadline'], '用户明确无需陪同；到院后的事项由用户核对')
        previous = 'arrival'
    add('return', '返家', f'预计{hm(f.return_time)}返家' if f.return_time else '就诊结束后；返家时间待确认',
        [previous], ['return_time', 'transport'], '依赖当日事项结束，具体返程仍需核实')
    if f.meal_required:
        add('meal', '衔接午餐', f'{hm(f.meal_time)}用餐' if f.meal_time else '返家后；用餐时间待确认',
            ['return'], ['meal_required', 'meal_time', 'meal_people', 'diet_notes'], '助餐资源、费用和本次可用性均待核实')
    rules = evaluate_rules(f)
    # 按生成顺序验证所有依赖都已出现，阻止不存在的引用与有环任务图。
    seen = set()
    for task in tasks:
        if task['id'] in seen or not set(task['dependencies']).issubset(seen):
            raise ValueError('Invalid task dependency graph')
        seen.add(task['id'])
    rules.append({'code': 'dependencies', 'status': 'pass', 'title': '事项依赖', 'detail': '事项引用有效，依赖顺序无环'})
    rules.append({'code': 'booking', 'status': 'pass', 'title': '草案边界', 'detail': '未创建预约、认领或正式派单'})
    known = [c for c in f.costs if c.amount is not None]
    return {
        'status': 'conflict' if any(r['status'] == 'conflict' for r in rules) else 'needs_information',
        'scene_id': f.scene_id, 'fields_snapshot': f.model_dump(mode='json'),
        'tasks': tasks, 'rules': rules, 'missing_fields': missing_fields(f), 'resources': resources,
        'budget': {'limit': f.budget_limit, 'known_subtotal': round(sum(c.amount for c in known), 2) if known else None,
                   'has_unknown_costs': not f.costs or any(c.amount is None for c in f.costs), 'total': None},
    }
