"""重新读取两份官方名单，交叉核对公开资料；不推断当前营业或联系结果。"""

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from import_panyu_resources import Rows, SOURCE

APP = Path(__file__).resolve().parents[1]
LEADING = 'https://mzj.gz.gov.cn/gk/fwjgylb/content/post_10144469.html'
INDEX = 'https://mzj.gz.gov.cn/gk/fwjgylb/'


def main():
    checked = datetime.now(timezone(timedelta(hours=8))).isoformat()
    collected = {}
    for url in (INDEX, SOURCE, LEADING):
        response = httpx.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, follow_redirects=False)
        response.raise_for_status()
        parser = Rows()
        parser.feed(response.text)
        collected[url] = {'url': url, 'http_status': response.status_code,
                          'sha256': hashlib.sha256(response.content).hexdigest(), 'rows': parser.rows}
    official = [r for r in collected[SOURCE]['rows'] if len(r) == 8 and r[1] == '番禺区']
    leading = [r for r in collected[LEADING]['rows'] if len(r) == 6 and r[1] == '番禺区']
    if not official or not leading:
        raise RuntimeError('Official format changed; retain existing snapshot and review manually')
    seeds_path = APP / 'data/seeds/panyu_resources.json'
    seeds = json.loads(seeds_path.read_text(encoding='utf-8'))
    names = {r['name']: r for r in seeds}
    comparisons, unmatched = [], []
    for row in leading:
        _, _, town, name, address, phone = row
        seed = names.get(name)
        if seed is None:
            unmatched.append({'name': name, 'town': town, 'address': address})
            continue
        differences = [key for key, actual in [('town', town), ('address', address), ('source_phone', phone)] if seed.get(key) != actual]
        ref = {'source_url': LEADING, 'source_title': '广州市引领性长者饭堂一览表',
               'published_at': '2025-03-06', 'checked_at': checked[:10], 'address': address,
               'source_phone': phone, 'differences': differences,
               'meaning': '另一份官方历史名单有此名称；不是当前服务质量、实时可用性或合作资质背书'}
        comparisons.append({'resource_id': seed['id'], 'name': name, 'differences': differences})
        # 只增加第二来源，不拿第二来源覆盖原地址和历史电话。
        seed['additional_sources'] = [ref]
    by_id = {'gz_panyu_meal_' + r[0]: r for r in official}
    drift = []
    for seed in seeds:
        row = by_id.get(seed['id'])
        if row is None or (row[3], row[4], row[6]) != (seed['name'], seed['address'], seed['source_phone']):
            drift.append(seed['id'])
        seed['checked_at'] = checked[:10]
        seed['catalog_version'] = max(seed.get('catalog_version', 1), 2)
    report = {'checked_at': checked, 'sources': [{k: v for k, v in x.items() if k != 'rows'} for x in collected.values()],
              'official_records': len(official), 'local_records': len(seeds), 'town_counts': dict(sorted(Counter(r['town'] for r in seeds).items())),
              'leading_panyu_records': len(leading), 'cross_matched': len(comparisons), 'comparisons': comparisons,
              'unmatched_leading': unmatched, 'primary_snapshot_drift': drift,
              'basis': 'public_pages_only_no_operator_contact',
              'limitations': ['主名单截至2025-02-05', '第二名单发布于2025-03-06', '查阅日期不等于营业核实日期', '未核实本次供餐/价格/资格/代取', '存在差异时保留两份来源，不自动合并为当前事实']}
    if drift:
        raise RuntimeError('Primary source changed; manual review required before updating seeds')
    research = APP / 'data/research'
    research.mkdir(exist_ok=True)
    (research / 'panyu-public-evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    seeds_path.write_text(json.dumps(seeds, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('comparisons', 'town_counts', 'sources')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
