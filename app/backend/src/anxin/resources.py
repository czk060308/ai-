"""人工溯源的公开资源目录：精确地区匹配、来源校验与时效提示。

页面查证不等于机构当前营业，更不等于本次预约。此模块不调用模型，
也不根据用户或资源文本自动访问任何网络地址。
"""

import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from .config import APP_ROOT

DISTRICTS = ('思明区', '湖里区', '集美区', '海沧区', '同安区', '翔安区')
SOURCE_HOSTS = {'mzt.fj.gov.cn', 'mzt.fujian.gov.cn', 'www.ixiamen.org.cn', 'mzj.gz.gov.cn'}


def load_catalog():
    demo = json.loads((APP_ROOT / 'data/seeds/resources.json').read_text(encoding='utf-8'))
    public = json.loads((APP_ROOT / 'data/seeds/public_resources.json').read_text(encoding='utf-8'))
    public += json.loads((APP_ROOT / 'data/seeds/panyu_resources.json').read_text(encoding='utf-8'))
    for item in public:
        item['catalog_managed_by'] = 'anxin_public_seed'
        parsed = urlparse(item['source_url'])
        if parsed.scheme != 'https' or parsed.hostname not in SOURCE_HOSTS or parsed.username or parsed.password:
            raise ValueError('Unapproved public resource source')
        if item['data_type'] != 'public' or item['evidence_status'] != 'public_source_only':
            raise ValueError('Public source classification required')
        if item['price'] is not None or item['availability'] is not None:
            raise ValueError('Public source does not verify current price or availability')
        if item['scope'] not in ('local_site', 'city_directory') or item['city'] not in ('厦门市', '广州市'):
            raise ValueError('Invalid resource scope')
        if item['district'] is not None and item['district'] not in DISTRICTS + ('番禺区',):
            raise ValueError('Invalid district')
        date.fromisoformat(item['checked_at'])
        if item['published_at']:
            date.fromisoformat(item['published_at'])
    records = demo + public
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('Resource IDs must be unique')
    return records


def region_scope(region):
    """只支持明确的厦门市/区别名，不对模糊地址作地理推断。"""
    region = ''.join((region or '').split())
    if region in ('番禺', '番禺区', '广州番禺', '广州番禺区', '广州市番禺区'):
        return '广州市', '番禺区'
    if region in ('厦门', '厦门市'):
        return '厦门市', None
    for district in DISTRICTS:
        if region in (district, district[:-1], '厦门' + district, '厦门市' + district):
            return '厦门市', district
    return None, None


def match_resource(payload, region, include_demo):
    if payload['data_type'] == 'demo':
        return include_demo and region == payload['region']
    city, district = region_scope(region)
    if not city or payload.get('city') != city:
        return False
    return district is None or payload.get('scope') == 'city_directory' or payload.get('district') == district


def present_resource(payload, region):
    """附加匹配理由和资料时效，供界面解释，不改写已保存草案。"""
    if payload['data_type'] == 'demo':
        return payload
    published = payload.get('published_at')
    today = datetime.now(timezone(timedelta(hours=8))).date()
    stale = not published or (today - date.fromisoformat(published)).days > 365
    _, district = region_scope(region)
    reason = ((payload['city'] + '官方查询入口，非具体服务商' if payload['category'] == 'directory' else payload['city'] + '官方服务说明，非具体服务商') if payload['scope'] == 'city_directory'
              else '同区公开地点候选，实际服务范围待核实' if district
              else '同城公开地点候选，未按距离排序，实际服务范围待核实')
    return {**payload, 'source_stale': stale, 'match_reason': reason}
