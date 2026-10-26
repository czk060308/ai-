import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Collapse, Input, Select, Tag } from 'antd';
import { api, dateTime } from './api';
import type { MealCase } from './mealApi';

interface BoardItem { id: string; data_type: string; title: string; town: string | null; service_date: string | null; overdue: boolean; questions: string[] }
interface Candidate { id: string; code: string; start: string; end: string; eligible: boolean; reasons: string[] }
interface Comparison { id: string; name: string; current_case_checked: boolean; current_quote: number | null; reason: string; source_url: string; historical_external: boolean }
interface Playbook { guide_version: string; case_id: string; case_version: number; data_type: string; next_action: { title: string; questions: string[] }; contact_script: string[]; handover_checklist: string[]; replication_tasks: string[] }
interface Sources { checked_at: string; official_records: number; leading_panyu_records: number; cross_matched: number; unmatched_leading: { name: string }[]; sources: { url: string }[]; limitations: string[]; comparisons: { differences: string[] }[] }

/** 运营功能独立于主表单：候选匹配不替代接受，待办不假装外部通知。 */
export default function MealOperations({ record, towns, locked, onLoad, onChanged }: {
  record: MealCase | null; towns: string[]; locked: boolean;
  onLoad: (id: string) => Promise<void>; onChanged: () => Promise<void>;
}) {
  const [board, setBoard] = useState<BoardItem[]>([]);
  const [sources, setSources] = useState<Sources | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [comparison, setComparison] = useState<Comparison[]>([]);
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [code, setCode] = useState('');
  const [date, setDate] = useState('');
  const [town, setTown] = useState<string>();
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [kind, setKind] = useState('demo');
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const [b, s] = await Promise.all([api<{ items: BoardItem[] }>('/meal/board'), api<Sources>('/meal/source-evidence')]);
    setBoard(b.items); setSources(s);
    if (record) {
      const [c, r, p] = await Promise.all([api<{ items: Candidate[] }>(`/meal/cases/${record.id}/candidates`),
        api<{ items: Comparison[] }>(`/meal/cases/${record.id}/resource-comparison`), api<Playbook>(`/meal/cases/${record.id}/playbook`)]);
      setCandidates(c.items); setComparison(r.items); setPlaybook(p);
    } else { setCandidates([]); setComparison([]); setPlaybook(null); }
  }
  async function run(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void run(refresh); }, [record?.id, record?.version]);
  function downloadCard() {
    if (!playbook) return;
    const content = [`# 安心接力志愿者操作卡（${playbook.guide_version}）`,
      `记录 ${playbook.case_id} v${playbook.case_version}；${playbook.data_type === 'demo' ? '合成演示，不计真实服务' : '人工填报试点，非独立核验'}`,
      '此卡对应导出时版本，安排变更后重新下载。', `下一步：${playbook.next_action.title}`,
      '## 待补问', ...playbook.next_action.questions.map(q => `- ${q}`), '## 联系供餐点的话术',
      ...playbook.contact_script.map(q => `- ${q}`), '## 交接检查', ...playbook.handover_checklist.map(q => `- ${q}`),
      '## 非开发者复用测试', ...playbook.replication_tasks.map(q => `- ${q}`),
      '复用测试须由另一名实际操作者执行并记录用时/求助，机器演练不能代替。',
      '当前卡片不含姓名电话、详细地址、饮食备注和家庭原文；线下核实与交接后据实记录。'].join('\n\n');
    const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = '安心接力-志愿者操作卡.md'; a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="meal-operations panel" aria-label="运营与志愿者复用">
    <div className="panel-heading"><h2>运营与志愿者复用</h2><Button size="small" disabled={busy || locked} onClick={() => void run(refresh)}>刷新待办与匹配</Button></div>
    {error && <Alert type="error" title="运营操作未完成" description={error} />}{notice && <Alert type="success" title={notice} />}
    <Collapse ghost items={[
      { key: 'sources', label: `公开数据核对：${sources?.official_records ?? '—'}条 / ${sources?.cross_matched ?? '—'}条双来源同名`, children: sources && <div className="ops-body">
        <p>查阅：{dateTime(sources.checked_at)}。第二份“引领性长者饭堂”名单含{sources.leading_panyu_records}个番禺点位，{sources.cross_matched}个名称与基础名单完全一致。</p>
        <p>{sources.unmatched_leading.length}个名称未完全匹配、{sources.comparisons.filter(c => c.differences.length).length}条同名记录存在字段差异，保留原始来源，不自动合并。</p>
        {sources.sources.map(s => <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">查看官方页面 ↗</a>)}
        <p>{sources.limitations.join('；')}。</p></div> },
      { key: 'board', label: `待办看板：${board.filter(b => b.data_type === 'pilot').length}条试点 / ${board.filter(b => b.data_type === 'demo').length}条演示`, children: <div className="ops-body">
        <p>按北京时间计算待核对事项，未发送外部通知。演示超时不计真实服务事故。</p>
        {!board.length && <p>目前没有未终结记录。</p>}{board.slice(0, 30).map(b => <div className="ops-row" key={b.id}>
          <Tag color={b.data_type === 'demo' ? 'gold' : 'cyan'}>{b.data_type === 'demo' ? '演示' : '试点'}</Tag><b>{b.title}</b>{b.overdue && <Tag color="orange">计划时间已过，待核对实际情况</Tag>}
          <p>{b.service_date || '日期未知'} · {b.town || '镇街未知'}</p>
          <Button size="small" disabled={locked || busy} onClick={() => void run(() => onLoad(b.id))}>载入这条待办</Button></div>)}</div> },
      { key: 'volunteers', label: '志愿者排班与候选匹配', children: <div className="ops-body">
        <p>登记仅用代号。候选须同日期、同镇街和同用途；对登记人员检查已接受任务的取餐—交接区间重叠，不包含去饭堂的行程。手工称呼未绑定排班时无法检查跨任务人员冲突。</p>
        <div className="ops-form"><label>志愿者代号<Input aria-label="排班志愿者代号" value={code} onChange={e => setCode(e.target.value)} placeholder="如V001，仅字母数字_-" /></label>
        <label>登记用途<Select aria-label="排班用途" value={kind} onChange={setKind} options={[{ value: 'demo', label: '演示排班' }, { value: 'pilot', label: '真实排班' }]} /></label>
        <label>服务日期<Input aria-label="排班日期" type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
        <label>服务镇街<Select aria-label="排班镇街" value={town} onChange={setTown} options={towns.map(t => ({ value: t, label: t }))} /></label>
        <label>可用起点<Input aria-label="排班起点" type="time" value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>可用终点<Input aria-label="排班终点" type="time" value={end} onChange={e => setEnd(e.target.value)} /></label></div>
        {kind === 'pilot' && <Checkbox checked={consent} onChange={e => setConsent(e.target.checked)}>该志愿者已同意登记代号与时段</Checkbox>}
        <Button disabled={locked || busy || !code || !date || !town || !start || !end} onClick={() => void run(async () => {
          await api('/meal/volunteers', { method: 'POST', body: JSON.stringify({ code, data_type: kind, service_date: date, town, start, end, consent_confirmed: consent }) });
          setCode(''); await refresh(); setNotice('排班已登记，尚未认领任何任务。');
        })}>保存排班</Button>
        {record ? <><h3>当前需求的登记候选</h3>{!candidates.length && <p>无同日期同镇街同用途的登记候选；不会虚构志愿者。</p>}
          {candidates.map(c => <div className="ops-row" key={c.id}><b>{c.code}</b><Tag color={c.eligible ? 'green' : 'gold'}>{c.eligible ? '当前约束可行，仍须接受' : '待核实或存在约束'}</Tag>
          <p>{c.start.slice(0, 5)}—{c.end.slice(0, 5)} · {c.reasons.join('；')}</p>
          <Button size="small" disabled={locked || busy || ['completed', 'cancelled', 'picked_up', 'handed_over'].includes(record.status)} onClick={() => void run(async () => {
            await api(`/meal/cases/${record.id}/assign`, { method: 'POST', body: JSON.stringify({ expected_version: record.version, volunteer_id: c.id }) });
            await onChanged(); setNotice('已选候选人；原供餐核实和接受失效，请重新核实。');
          })}>选择候选并重新核实</Button></div>)}</> : <p>请先建档或载入需求，再查看匹配。</p>}</div> },
      { key: 'comparison', label: `候选饭堂对比：${comparison.length}条同镇街`, children: <div className="ops-body"><p>仅本次已记录核实优先，其余按固定ID；不按距离、价格或“引领性”标记推断当前质量。</p>
        <div className="ops-comparison">{comparison.map(c => <div className="ops-row" key={c.id}><b>{c.name}</b><p>{c.reason}</p><p>本次总报价：{c.current_quote == null ? '未知' : `${c.current_quote}元`}；历史对外开放：{c.historical_external ? '是' : '否'}（需重核）</p>
          <a href={c.source_url} target="_blank" rel="noopener noreferrer">官方来源</a></div>)}</div></div> },
      { key: 'playbook', label: '补问助手与志愿者标准操作卡', children: <div className="ops-body">{playbook ? <>
        <h3>下一步：{playbook.next_action.title}</h3>{playbook.next_action.questions.map(q => <p key={q}>□ {q}</p>)}
        <h3>联系供餐点话术</h3>{playbook.contact_script.map(q => <p key={q}>{q}</p>)}
        <h3>非开发者复用测试任务</h3>{playbook.replication_tasks.map(q => <p key={q}>□ {q}</p>)}
        <p>机器演练不代替另一名真实操作者复用。请分别记录操作者代号、用时、求助次数与卡点。</p>
        <Button aria-label="下载志愿者操作卡" onClick={downloadCard} disabled={locked || busy}>下载当前版本操作卡（Markdown）</Button>
        </> : <p>先建档，再生成针对当前需求的补问清单与操作卡。</p>}</div> },
    ]} />
  </section>;
}
