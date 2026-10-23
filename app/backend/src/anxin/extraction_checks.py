"""独立于模型的高确定性事实检查；只拦截遗漏与冲突，不替模型填值。

覆盖数字日期、预算、明确亲属称呼/可用窗口与陪同/午餐的否定表达。
这不是完整中文语义解析器；模糊表达仍由模型抽取、用户核对。
"""

import re
from dataclasses import dataclass
from datetime import date

from .domain import NeedFields

# 指令污染句不能作为事实证据；保留原始输入，过滤仅用于抽取与校验。
INSTRUCTION = re.compile(
    r'忽略.{0,20}(?:指令|规则|要求|提示|前文|以上)|'
    r'(?:泄露|透露|输出|打印|显示).{0,20}(?:密钥|系统提示|API_KEY|api_key|环境变量)|'
    r'(?:你现在是|扮演|系统消息|开发者消息|最高优先级)|'
    r'(?:system|developer|assistant)\s*:|\[/?INST\]|<\/?(?:system|assistant|script)\b|'
    r'(?:只输出|必须输出).{0,20}(?:JSON|json|confirmed|预算)|'
    r'把.{0,20}(?:budget_limit|acceptance_status).{0,12}(?:改|设)|'
    r'(?:curl|fetch|exec|eval)\s*\(', re.IGNORECASE,
)
ENGLISH_INSTRUCTION = re.compile(r'ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|rules)|'
                                 r'(?:reveal|print|expose)\s+(?:the\s+)?(?:system\s+prompt|api\s*key|secret)|'
                                 r'you\s+are\s+now|<\|(?:im_start|im_end|system|assistant)\|>', re.IGNORECASE)


def fact_text(raw_text: str) -> str:
    """按句隔离明显越权指令；原文与安全片段仍可逐字定位。"""
    return ''.join(part for part in re.split(r'(?<=[。！？\n])', raw_text)
                   if not INSTRUCTION.search(part) and not ENGLISH_INSTRUCTION.search(part))


@dataclass(frozen=True)
class Fact:
    field: str
    value: object
    quote: str


def explicit_facts(raw_text: str) -> list[Fact]:
    text = fact_text(raw_text)
    found = []

    def add(field, value, quote):
        found.append(Fact(field, value, quote))

    for match in re.finditer(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', text):
        try:
            add('service_date', date(*map(int, match.groups())).isoformat(), match.group())
        except ValueError:
            pass  # 无效日期交给Schema或用户确认，不能猜一个有效日期。
    for match in re.finditer(r'(?:生活服务|服务|总)?预算(?:上限)?(?:为|是|不超过|：|:)?\s*(\d+(?:\.\d{1,2})?)元', text):
        add('budget_limit', float(match.group(1)), match.group())
    arrival = re.compile(r'(上午|下午|早上|晚上)?(\d{1,2})(?:点(?:(\d{1,2})分)?|:(\d{2}))'
                         r'(?:前)?(?:要|需要)?(?:到|抵达)(?:医院|院)')
    for match in arrival.finditer(text):
        period, hour, minute, colon_minute = match.groups()
        hour = int(hour)
        if period in ('下午', '晚上') and hour < 12:
            hour += 12
        minute = int(minute or colon_minute or 0)
        if 0 <= hour < 24 and minute < 60:
            add('arrival_deadline', f'{hour:02d}:{minute:02d}', match.group())
    for match in re.finditer(r'((?:家里)?老人|父亲|母亲|爸爸|妈妈)(?:需要|要)(?:有人)?陪同', text):
        add('care_recipient', match.group(1), match.group())

    relatives = r'妹妹|弟弟|哥哥|姐姐|女儿|儿子|丈夫|妻子|爱人|爸爸|妈妈|父亲|母亲'
    for match in re.finditer(rf'({relatives})(?:当天|当日|明天|后天)?(?:上午|下午|早上|晚上)?(?=\d|可以帮忙|能帮忙|有空|负责陪同)', text):
        # 只检查明确可用候选人，不能把“哥哥没空”的人硬塞进安排。
        add('participant_name', match.group(1), match.group())

    window = re.compile(rf'(?:{relatives})(?:当天|当日|明天|后天)?(上午|下午|早上|晚上)?'
                        r'(\d{1,2})(?:点|:)(\d{1,2}分?)?(?:到|至|—|-)(\d{1,2})(?:点|:)(\d{1,2}分?)?有空')
    for match in window.finditer(text):
        period, start_h, start_m, end_h, end_m = match.groups()
        start_h, end_h = int(start_h), int(end_h)
        if period in ('下午', '晚上'):
            start_h += 12 if start_h < 12 else 0
            end_h += 12 if end_h < 12 else 0
        if 0 <= start_h < 24 and 0 <= end_h < 24:
            add('availability_start', f'{start_h:02d}:{int((start_m or "0").rstrip("分")):02d}', match.group())
            add('availability_end', f'{end_h:02d}:{int((end_m or "0").rstrip("分")):02d}', match.group())

    for field, noun in [('meal_required', '午餐'), ('accompaniment_required', '陪同')]:
        negative = re.search(rf'(?:不需要|无需|不用|不必)(?:安排|有人)?{noun}', text)
        positive = re.search(rf'(?<!不)(?<!无)需要(?:安排|有人)?{noun}', text)
        if negative:
            add(field, False, negative.group())
        elif positive:
            add(field, True, positive.group())
    for match in re.finditer(r'(?:还没|还没有|尚未|未)确认接受', text):
        add('acceptance_status', 'unknown', match.group())
    return found


def coverage_issues(fields: NeedFields, raw_text: str) -> list[dict]:
    """仅报告模型遗漏/冲突，不自动用规则值覆盖模型或用户字段。"""
    values = fields.model_dump(mode='json')
    grouped = {}
    for fact in explicit_facts(raw_text):
        grouped.setdefault(fact.field, []).append(fact)
    issues = []
    for field, facts in grouped.items():
        expected = {fact.value for fact in facts}
        if len(expected) > 1:
            issues.append({'field': field, 'reason': '原文包含多个值，需人工核对', 'quotes': [f.quote for f in facts]})
            continue
        actual = values[field]
        if field in ('availability_start', 'availability_end', 'arrival_deadline') and actual:
            actual = actual[:5]
        if field == 'care_recipient' and actual and (actual in facts[0].value or facts[0].value in actual):
            continue  # “家里老人”与“老人”允许称呼粒度不同，不允许编造具体身份。
        if actual != facts[0].value:
            issues.append({'field': field, 'reason': '明确事实漏提或与原文不一致', 'quotes': [f.quote for f in facts]})
    return issues


def evidence_supports(field, value, quote):
    """对关键承诺与称呼加语义下限；原文存在引用仍不代表引用支持该值。"""
    if field == 'acceptance_status' and value == 'confirmed':
        return bool(re.search(r'已(?:经)?(?:确认接受|同意|答应)|愿意(?:陪同|接受)|确认(?:愿意|接受)', quote)) and not re.search(r'没|未|不|尚', quote)
    if field == 'participant_name':
        return str(value) in quote
    if field in ('meal_required', 'accompaniment_required') and value is False:
        return bool(re.search(r'不需要|无需|不用|不必', quote))
    return True
