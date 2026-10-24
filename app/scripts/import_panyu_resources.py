"""人工审核后的官方表格导入器；仅获取指定政府页面，不探测商家接口。

运行后更新公开目录快照；名单中的营业描述和电话是历史资料，不能作为本次核实。
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

SOURCE = 'https://mzj.gz.gov.cn/gk/fwjgylb/content/post_10111922.html'
APP = Path(__file__).resolve().parents[1]


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def main():
    response = httpx.get(SOURCE, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, follow_redirects=False)
    response.raise_for_status()
    parser = Rows()
    parser.feed(response.text)
    checked = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    records = []
    for row in parser.rows:
        if len(row) != 8 or row[1] != '番禺区':
            continue
        number, district, town, name, address, days, phone, public = row
        if not number.isdigit() or not address or public not in ('是', '否'):
            raise ValueError('Official table format changed; manual review required')
        records.append({
            'id': 'gz_panyu_meal_' + number, 'name': name, 'category': 'meal',
            'region': '广州市番禺区', 'city': '广州市', 'district': district,
            'town': town, 'scope': 'local_site', 'data_type': 'public',
            'address': address, 'phone': None, 'source_phone': phone,
            'source_open_days': days, 'source_external_residents': public == '是',
            'price': None, 'availability': None, 'evidence_status': 'public_source_only',
            'source_name': '广州市民政局·长者饭堂一览表', 'source_url': SOURCE,
            'source_title': '广州市长者饭堂一览表（截至2025年2月5日）',
            'description': '广州市民政局公开名单中的番禺助餐地点；本次供餐、代取及价格待人工核实。',
            'source_note': '官方历史名单，不代表实时服务供给或已预约。',
            'published_at': '2025-02-12', 'snapshot_date': '2025-02-05', 'checked_at': checked,
            'catalog_version': 1, 'unknown_fields': ['当前营业', '当天供餐时段', '实际价格', '打包与代取', '本次服务资格', '电话是否仍有效'],
            'notes': '名单为2025-02-05快照；历史开放日/咨询电话不代表本次可用，须人工联系核实。',
        })
    if not records or len({r['id'] for r in records}) != len(records):
        raise ValueError('Missing or duplicate Panyu records')
    target = APP / 'data/seeds/panyu_resources.json'
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    runtime = APP / 'runtime'
    runtime.mkdir(exist_ok=True)
    evidence = {'source_url': SOURCE, 'http_status': response.status_code, 'checked_at': checked,
                'body_sha256': hashlib.sha256(response.content).hexdigest(), 'records': len(records),
                'towns': sorted({r['town'] for r in records}), 'snapshot_date': '2025-02-05'}
    (runtime / 'panyu-source-check.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
