import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Collapse, Input, Select, Spin, Tag } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, CoffeeOutlined, DownloadOutlined, HeartOutlined, ReloadOutlined } from '@ant-design/icons';
import { api, dateTime, timeText } from './api';
import type { AuditEvent, Health } from './api';
import type { MealCase, MealFields, MealHistory, MealResource, MealResources, MealStats } from './mealApi';
import { mealStatuses } from './mealApi';
import { ResourceCard } from './components/ResourceCard';

const eventNames: Record<string, string> = { meal_created: '原文已保存', meal_extraction_finished: '字段处理结束',
  meal_replanned: '安排修改，原核实与接受失效', meal_supply_verified: '人工供餐核实已记录', meal_accept: '接受已记录',
  meal_picked_up: '取餐已记录', meal_handed_over: '交接已记录', meal_block: '异常已记录', meal_cancel: '接力已取消', meal_feedback_received: '反馈闭环已记录' };
const ruleNames: Record<string, string> = { pass: '通过', unknown: '待核实', conflict: '冲突' };

/** 志愿者操作台：模型提取、人工承诺和实际结果分步保存，刷新后以数据库为准。 */
export default function MealWorkbench() {
  const [raw, setRaw] = useState('');
  const [sample, setSample] = useState('');
  const [record, setRecord] = useState<MealCase | null>(null);
  const [fields, setFields] = useState<MealFields | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [history, setHistory] = useState<MealHistory[]>([]);
  const [stats, setStats] = useState<MealStats | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [catalog, setCatalog] = useState<MealResources>({ items: [], total: 0, towns: [], snapshot_date: '' });
  const [resourceLoading, setResourceLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState('');
  const [dataType, setDataType] = useState<'demo' | 'pilot'>('demo');
  const [family, setFamily] = useState('');
  const [consent, setConsent] = useState(false);
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [checkNote, setCheckNote] = useState('');
  const [supplyStart, setSupplyStart] = useState('');
  const [supplyEnd, setSupplyEnd] = useState('');
  const [quote, setQuote] = useState('');
  const [method, setMethod] = useState('phone');
  const [takeaway, setTakeaway] = useState(false);
  const [eligible, setEligible] = useState(false);
  const [diet, setDiet] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [reporter, setReporter] = useState('');
  const [channel, setChannel] = useState('oral');
  const [rating, setRating] = useState<string | undefined>();
  const [actualCost, setActualCost] = useState('');
  const [busy, setBusy] = useState('正在连接服务');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dirty = !!(record && fields && JSON.stringify(record.fields) !== JSON.stringify(fields));
  const rawChanged = !!record && raw !== record.raw_text;
  const locked = !!record && ['completed', 'cancelled', 'picked_up', 'handed_over'].includes(record.status);
  const canAct = !!record && !dirty && !rawChanged && !busy;

  async function refresh() {
    const [h, s] = await Promise.all([api<MealHistory[]>('/meal/cases'), api<MealStats>('/meal/stats')]);
    setHistory(h); setStats(s);
  }
  async function install(r: MealCase) {
    setRecord(r); setFields(r.fields); setRaw(r.raw_text); setDataType(r.data_type); setFamily(r.family_code || '');
    setConsent(r.consent_confirmed); setSelected(r.supply_check?.resource_id || '');
    // 不把上一记录/上一版本的核实草稿带入新版本，防止误复用承诺。
    setNote(''); setCheckNote(''); setSupplyStart(''); setSupplyEnd(''); setQuote('');
    setTakeaway(false); setEligible(false); setDiet(false);
    setFeedback(''); setReporter(''); setChannel('oral'); setRating(undefined); setActualCost('');
    localStorage.setItem('anxin.meal_id', r.id);
    await Promise.all([refresh(), api<AuditEvent[]>(`/meal/cases/${r.id}/events`).then(setEvents)]);
  }
  async function run(label: string, action: () => Promise<void>) {
    setBusy(label); setError(''); setNotice('');
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(''); }
  }
  useEffect(() => {
    void run('正在连接服务', async () => {
      const [h, demo] = await Promise.all([api<Health>('/health'), api<{ raw_text: string }>('/meal/demo')]);
      setHealth(h); setSample(demo.raw_text); await refresh();
      const id = localStorage.getItem('anxin.meal_id');
      if (id) await install(await api<MealCase>(`/meal/cases/${id}`));
    });
  }, []);
  useEffect(() => {
    let active = true;
    setResourceLoading(true);
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ limit: '12', query: search });
      if (fields?.town) params.set('town', fields.town);
      void api<MealResources>('/meal/resources?' + params).then(r => { if (active) { setCatalog(r); setResourceLoading(false); } })
        .catch(err => { if (active) { setError(String(err.message)); setCatalog(c => ({ ...c, items: [], total: 0 })); setResourceLoading(false); } });
    }, 200);
    return () => { active = false; window.clearTimeout(timer); };
  }, [fields?.town, search]);

  async function create(mode: 'model' | 'manual' | 'demo') {
    await run('正在保存与核对助餐需求', async () => {
      const r = await api<MealCase>('/meal/cases', { method: 'POST', body: JSON.stringify({ raw_text: raw, mode,
        data_type: dataType, family_code: dataType === 'pilot' ? family.trim() || null : null, consent_confirmed: consent }) });
      await install(r); setNotice(r.extraction_message);
    });
  }
  async function save() {
    if (!record || !fields) return;
    await run('正在保存，旧承诺将失效', async () => {
      await install(await api<MealCase>(`/meal/cases/${record.id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: record.version, fields }) }));
      setNotice('字段已保存。修改后的安排须重新核实供餐并确认取餐人接受。');
    });
  }
  function edit(key: keyof MealFields, value: string | number | null) { setFields(f => f ? { ...f, [key]: value } : f); }
  function input(key: keyof MealFields, label: string, type = 'text') {
    const value = fields?.[key];
    return <label className="field" key={key}><span>{label}</span><Input aria-label={label} type={type}
      min={type === 'number' ? (key === 'budget_limit' ? 0 : 1) : undefined} step={key === 'budget_limit' ? '0.01' : undefined}
      value={value == null ? '' : type === 'time' ? String(value).slice(0, 5) : value}
      disabled={!!busy || locked} placeholder="未知，请核对"
      onChange={e => edit(key, e.target.value === '' ? null : type === 'number' ? Number(e.target.value) : e.target.value)} /></label>;
  }
  async function verify() {
    if (!record || !fields) return;
    await run('正在保存当天供餐核实记录', async () => {
      const r = await api<MealCase>(`/meal/cases/${record.id}/verify`, { method: 'POST', body: JSON.stringify({ expected_version: record.version,
        resource_id: selected, service_date: fields.service_date, supply_start: supplyStart, supply_end: supplyEnd,
        quoted_total: quote === '' ? null : Number(quote), takeaway_confirmed: takeaway, eligibility_confirmed: eligible,
        diet_confirmed: diet, verified_by: actor, method, note: checkNote }) });
      await install(r); setNotice('已保存人工填报的本次核实，不代表商家系统预约。');
    });
  }
  async function action(value: string) {
    if (!record) return;
    await run('正在保存接力进展', async () => {
      const r = await api<MealCase>(`/meal/cases/${record.id}/actions`, { method: 'POST', body: JSON.stringify({ expected_version: record.version, action: value, actor, note }) });
      await install(r); setNote(''); setNotice('进展已保存，请按实际发生情况继续记录。');
    });
  }
  async function finish() {
    if (!record) return;
    await run('正在保存反馈', async () => {
      const r = await api<MealCase>(`/meal/cases/${record.id}/feedback`, { method: 'POST', body: JSON.stringify({ expected_version: record.version,
        reporter, channel, comment: feedback, rating: rating ? Number(rating) : null, actual_cost: actualCost === '' ? null : Number(actualCost) }) });
      await install(r); setNotice('反馈闭环已保存。试点统计与演示统计保持分开。');
    });
  }
  async function exportReport() {
    await run('正在生成脱敏评估导出', async () => {
      const report = await api<unknown>('/meal/export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = '安心接力-脱敏试点评估.json'; a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('已导出统计与最小案例字段，不包含原文、人员、家庭代号、详细地址或备注。');
    });
  }
  function reset() {
    if (dirty && !window.confirm('有未保存字段，确定新建吗？')) return;
    setRecord(null); setFields(null); setEvents([]); setRaw(''); setSelected(''); setDataType('demo'); setFamily(''); setConsent(false);
    setNote(''); setCheckNote(''); setQuote(''); setSupplyStart(''); setSupplyEnd(''); setTakeaway(false); setEligible(false); setDiet(false);
    setFeedback(''); setReporter(''); setRating(undefined); setActualCost(''); setError(''); setNotice(''); localStorage.removeItem('anxin.meal_id');
  }
  const selectedResource = catalog.items.find(r => r.id === selected) || record?.supply_check?.resource_snapshot;

  return <div className="meal-shell">
    <header className="meal-header"><a className="brand" href="/?scene=meal"><span className="brand-mark"><HeartOutlined /></span><span>安心接力<small>ANXIN RELAY</small></span></a>
      <span className="meal-location">广州 · 番禺 <Tag color="cyan">志愿者工作台</Tag></span>
      <span className="meal-online"><i className={`status-dot ${health ? 'online' : ''}`} /> {health ? '本机服务已连接' : '正在连接'}</span>
    </header>
    <main className="meal-main">
      <section className="meal-hero"><div><div className="eyebrow">临时助餐 · 取餐与交接</div><h1>让一顿饭，有人接、有回音。</h1><p>把家庭照护需求变成有依据、可追踪的服务安排</p><span>补问需求 → 核实供餐 → 确认接受 → 取餐交接 → 反馈闭环</span></div>
        <div className="meal-hero-actions"><Button aria-label="导出脱敏评估" icon={<DownloadOutlined />} onClick={() => void exportReport()} disabled={!!busy}>导出脱敏评估</Button><Button type="primary" onClick={reset} disabled={!!busy}>新建助餐需求</Button></div></section>
      <div className="meal-stats" aria-label="试点统计">
        {[['真实试点需求', stats?.pilot_cases ?? '—', '仅人工标记且确认同意'], ['独立家庭', stats?.families ?? '—', '按家庭代号去重'],
          ['完成闭环', stats ? `${stats.completed} / ${stats.completion_denominator}` : '—', '分母含待执行、受阻、取消'], ['演示记录', stats?.demo_cases ?? '—', '不计入真实试点成果']].map(([title, value, detail]) =>
          <div key={title}><span>{title}</span><strong>{value}</strong><small>{detail}</small></div>)}
      </div>
      <Alert className="global-alert" type="info" showIcon title="当前为本机开发与试点记录工具：不自动预约、派单、付款或联系商家。名单、人工核实、实际结果分别记录。" />
      {error && <Alert className="global-alert" type="error" showIcon title="操作未完成" description={error} closable onClose={() => setError('')} />}
      {notice && <Alert className="global-alert" type="success" showIcon title={notice} closable onClose={() => setNotice('')} />}
      {busy && <div className="meal-busy" role="status"><Spin size="small" /> {busy}</div>}
      <div className="meal-grid">
        <section className="panel meal-demand"><div className="panel-heading"><div><span className="section-number">01</span><h2>需求与补问</h2></div>{record && <Tag>v{record.version}</Tag>}</div><div className="panel-body">
          <label className="input-label" htmlFor="meal-raw">家庭需要怎样的午餐安排？</label><Input.TextArea id="meal-raw" aria-label="助餐需求原文" value={raw} maxLength={6000} rows={5} onChange={e => setRaw(e.target.value)} disabled={!!busy} placeholder="日期、镇街、份数、交接时间、预算、谁能代取……不填姓名电话与详细住址。" />
          <Button type="link" onClick={() => { setRaw(sample); setDataType('demo'); }} disabled={!!busy}>载入合成助餐样例</Button>
          <div className="meal-mode"><label className="field"><span>记录用途（创建后不可更改）</span><Select aria-label="记录用途" value={dataType} disabled={!!busy || !!record} onChange={setDataType}
            options={[{ value: 'demo', label: '演示 / 练习，不计真实成果' }, { value: 'pilot', label: '真实试点，需同意与家庭代号' }]} /></label>
          {dataType === 'pilot' && <><label className="field"><span>家庭代号</span><Input aria-label="家庭代号" value={family} onChange={e => setFamily(e.target.value)} disabled={!!busy || !!record} placeholder="例如PY-001，同一家庭复用同一代号" /></label><Checkbox checked={consent} disabled={!!busy || !!record} onChange={e => setConsent(e.target.checked)}>参与者已知情同意记录与脱敏展示</Checkbox></>}
          </div><div className="meal-create-buttons"><Button type="primary" onClick={() => void create('model')} disabled={!!busy || !!record || raw.trim().length < 2}>AI识别并保存</Button><Button onClick={() => void create('manual')} disabled={!!busy || !!record || raw.trim().length < 2}>手工建档</Button><Button onClick={() => void create('demo')} disabled={!!busy || !!record || raw !== sample || dataType !== 'demo'}>使用合成字段</Button></div>
          {!health?.model_configured && <p className="microcopy">API未配置时可手工建档或使用合成字段；不伪装为AI识别。</p>}
          {record && <div className="meal-extraction"><Tag color={record.extraction_status === 'succeeded' ? 'blue' : 'gold'}>{record.extraction_status === 'succeeded' ? '真实API识别' : record.extraction_status === 'demo' ? '合成演示 · 未调用模型' : record.extraction_status === 'manual' ? '手工填写' : '识别未完成，可手工接续'}</Tag><p>{record.extraction_message}</p>{record.extraction_review.model_calls && <p>模型调用{record.extraction_review.model_calls}次{record.extraction_review.repair_applied ? '，已进行一次校验修正' : ''}；字段仍需人工核对。</p>}</div>}
          {rawChanged && <Alert type="warning" title="原文已修改。请先恢复已保存原文，或新建一条需求；当前接力操作暂停。" action={<Button size="small" onClick={() => setRaw(record!.raw_text)}>恢复原文</Button>} />}
          {fields && <><div className="block-heading"><h3>核对字段</h3><Tag color="cyan">未知保持空白</Tag></div><div className="field-grid">
            {input('service_date', '服务日期', 'date')}{input('region', '服务地区')}
            {input('care_recipient', '受助对象（称呼或代号）')}
            <label className="field"><span>服务镇街</span><Select aria-label="服务镇街" allowClear value={fields.town} onChange={v => edit('town', v || null)} options={catalog.towns.map(t => ({ value: t, label: t }))} disabled={!!busy || locked} placeholder="请选择镇街" /></label>
            {input('meal_people', '用餐份数', 'number')}{input('handover_deadline', '交接截止', 'time')}{input('handover_place', '交接地点（用概略地点）')}
            {input('budget_limit', '本次总预算（元）', 'number')}{input('pickup_person', '候选取餐人（称呼或代号）')}
            {input('availability_start', '取餐人可用起点', 'time')}{input('availability_end', '取餐人可用终点', 'time')}
            {input('planned_pickup', '约定取餐时刻', 'time')}{input('travel_minutes', '取餐后单程分钟', 'number')}
          </div><label className="field meal-wide"><span>家属饮食要求</span><Input.TextArea aria-label="家属饮食要求" value={fields.diet_notes || ''} onChange={e => edit('diet_notes', e.target.value || null)} disabled={!!busy || locked} rows={2} placeholder="只记录家属提供的要求；无特殊要求也请明确，不生成食疗建议" /></label>
          <Button block onClick={() => void save()} disabled={!!busy || !dirty || locked || rawChanged}>保存核对字段</Button>
          {dirty && <p className="meal-warning">字段有未保存修改。保存后旧供餐核实、接受状态会失效，需要重新确认。</p>}
          <div className="missing-summary"><strong>待补问 {record!.checks.missing_fields.length} 项</strong><div className="missing-tags">{record!.checks.missing_fields.map(m => <Tag key={m.field}>{m.label}</Tag>)}</div></div>
          {!!Object.keys(record!.evidence).length && <Collapse ghost items={[{ key: 'quotes', label: '查看字段原文依据', children: Object.entries(record!.evidence).map(([key, e]) => <p className="meal-quote" key={key}><b>{key}</b><br />{e.quote}<Tag>{e.source === 'model_quote' ? '模型引用' : '人工补充'}</Tag></p>) }]} />}
          </>}
          <div className="history-section"><h3>最近助餐记录</h3>{history.length === 0 && <p className="microcopy">还没有记录。演示与试点都会明确标记。</p>}{history.slice(0, 12).map(h => <button className={`history-item ${record?.id === h.id ? 'selected' : ''}`} key={h.id} disabled={!!busy} onClick={() => void run('正在回读接力记录', async () => { if (dirty && !window.confirm('放弃未保存的字段修改？')) return; await install(await api<MealCase>(`/meal/cases/${h.id}`)); })}><span>{h.data_type === 'pilot' ? '真实试点' : '演示'} · {h.service_date || '日期待补'} · {h.town || '镇街待补'}</span><small>{mealStatuses[h.status]} · v{h.version}</small></button>)}</div>
        </div></section>
        <section className="meal-center">
          <div className="panel"><div className="panel-heading"><div><span className="section-number">02</span><h2>核实与接力进展</h2></div><Tag color={record?.status === 'completed' ? 'green' : 'cyan'}>{record ? mealStatuses[record.status] : '等待建档'}</Tag></div><div className="panel-body">
            {!record ? <div className="meal-empty"><CoffeeOutlined /><h3>先把需求说清，再把这顿饭接好。</h3><p>AI负责提取与检查，志愿者负责核实和记录。历史名单不会自动变成可用服务。</p><span>一次需求，一条可回看的接力链。</span></div> : <>
            <div className="meal-progress">{['核实供餐', '确认接受', '记录取餐', '交接', '反馈'].map((s, i) => {
              const steps: Record<string, number> = { draft: -1, verified: 0, accepted: 1, picked_up: 2, handed_over: 3, completed: 4, blocked: -1, cancelled: -1 };
              return <span key={s} className={i <= steps[record.status] ? 'done' : ''}><CheckCircleOutlined />{s}</span>;
            })}</div>
            {record.latest_exception && <Alert className="global-alert" type="warning" title="已记录的最近异常" description={`${record.latest_exception.note} · ${dateTime(record.latest_exception.at)}`} />}
            <div className="rules-block">{record.checks.rules.map(r => <div className={`rule-row rule-${r.status}`} key={r.code}><span className="rule-symbol">{r.status === 'pass' ? '✓' : r.status === 'conflict' ? '!' : '?'}</span><div><strong>{r.title}</strong><p>{r.detail}</p></div><Tag color={r.status === 'conflict' ? 'red' : r.status === 'pass' ? 'green' : 'gold'}>{ruleNames[r.status]}</Tag></div>)}</div>
            {record.checks.pickup_window && <p className="microcopy">取餐区间依据：{record.checks.pickup_window.basis}。系统不会自动承诺时刻。</p>}
            <h3 className="meal-subtitle">当天供餐核实</h3><p className="microcopy">请先在右侧选择同镇街资源，再通过电话或现场核实；不预填“已经核实”。</p>
            {selectedResource && <div className="meal-selection"><b>{selectedResource.name}</b><span>{selectedResource.address}</span></div>}
            <div className="field-grid"><label className="field"><span>记录人代号</span><Input aria-label="记录人代号" value={actor} onChange={e => setActor(e.target.value)} placeholder="志愿者代号，不填手机号" /></label><label className="field"><span>核实方式</span><Select aria-label="核实方式" value={method} onChange={setMethod} options={[{ value: 'phone', label: '实际电话联系' }, { value: 'on_site', label: '现场核实' }]} /></label>
              <label className="field"><span>当天供餐起点</span><Input aria-label="当天供餐起点" type="time" value={supplyStart} onChange={e => setSupplyStart(e.target.value)} /></label><label className="field"><span>当天供餐终点</span><Input aria-label="当天供餐终点" type="time" value={supplyEnd} onChange={e => setSupplyEnd(e.target.value)} /></label>
              <label className="field"><span>本次总报价（含已核实费用）</span><Input aria-label="本次总报价" type="number" min={0} step="0.01" value={quote} onChange={e => setQuote(e.target.value)} placeholder="未知保持空白" /></label></div>
            <div className="meal-confirmations"><Checkbox checked={takeaway} onChange={e => setTakeaway(e.target.checked)}>已核实可打包及代取</Checkbox><Checkbox checked={eligible} onChange={e => setEligible(e.target.checked)}>已核实本次就餐资格</Checkbox><Checkbox checked={diet} onChange={e => setDiet(e.target.checked)}>已转达并核对家属饮食要求</Checkbox></div>
            <Input.TextArea aria-label="供餐核实记录" rows={2} value={checkNote} onChange={e => setCheckNote(e.target.value)} placeholder="实际联系结果、针对哪天、费用包含什么；演练必须注明模拟，不填对方姓名电话" />
            <Button block onClick={() => void verify()} disabled={!canAct || locked || !selected || !actor.trim() || !supplyStart || !supplyEnd || quote === '' || checkNote.trim().length < 4}>保存当天供餐核实</Button>
            {record.supply_check && <div className="meal-saved"><b>已保存核实：{record.supply_check.resource_snapshot.name}</b><p>{timeText(record.supply_check.supply_start)}—{timeText(record.supply_check.supply_end)} · 填报总报价 ¥{record.supply_check.quoted_total}</p><p>{record.supply_check.note}</p><small>{record.supply_check.verified_by} · {dateTime(record.supply_check.checked_at)} · 人工填报，非预约回执</small></div>}
            <h3 className="meal-subtitle">确认接受与实际进展</h3><p className="microcopy">记录人代号沿用上方填写；每一步都要补充本次依据。有空不等于接受，交接不等于反馈。</p>
            {record.acceptance && <p className="meal-acceptance">接受记录：{record.acceptance.note}</p>}
            <Input.TextArea aria-label="进展或异常依据" rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="例如：候选人已明确接受；或食堂临时停供，需更换资源。请据实记录。" />
            <div className="meal-action-buttons"><Button type="primary" onClick={() => void action('accept')} disabled={!canAct || record.status !== 'verified' || !record.checks.ready_to_accept || !actor.trim() || note.trim().length < 4}>记录取餐人已接受</Button><Button onClick={() => void action('picked_up')} disabled={!canAct || record.status !== 'accepted' || !actor.trim() || note.trim().length < 4}>记录已取餐</Button><Button onClick={() => void action('handed_over')} disabled={!canAct || record.status !== 'picked_up' || !actor.trim() || note.trim().length < 4}>记录已交接</Button></div>
            <div className="meal-action-buttons"><Button danger onClick={() => void action('block')} disabled={!canAct || ['completed', 'cancelled', 'blocked'].includes(record.status) || !actor.trim() || note.trim().length < 4}>记录受阻 / 待重排</Button><Button onClick={() => void action('cancel')} disabled={!canAct || ['completed', 'cancelled'].includes(record.status) || !actor.trim() || note.trim().length < 4}>取消并保留原因</Button></div>
            {record.status === 'blocked' && <Alert type="warning" title="请修改候选人/取餐时刻或重新选择资源，再核实供餐并重新确认接受。原记录仍保留在事件中。" />}
            <h3 className="meal-subtitle">家庭反馈与闭环</h3><div className="field-grid"><label className="field"><span>反馈人代号或称呼</span><Input aria-label="反馈人代号" value={reporter} onChange={e => setReporter(e.target.value)} /></label><label className="field"><span>反馈方式</span><Select aria-label="反馈方式" value={channel} onChange={setChannel} options={[{ value: 'oral', label: '口头反馈' }, { value: 'message', label: '消息反馈' }, { value: 'on_site', label: '现场反馈' }]} /></label>
              <label className="field"><span>实际支出（未知不填）</span><Input aria-label="实际支出" type="number" min={0} step="0.01" value={actualCost} onChange={e => setActualCost(e.target.value)} /></label><label className="field"><span>满意度（可不提供）</span><Select aria-label="满意度" allowClear placeholder="未评价" value={rating} onChange={setRating} options={[1, 2, 3, 4, 5].map(n => ({ value: String(n), label: `${n}分` }))} /></label></div>
            <Input.TextArea aria-label="家庭反馈内容" rows={2} value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="收到什么反馈、还有哪些问题；不能用默认好评代替实际反馈" />
            <Button type="primary" block onClick={() => void finish()} disabled={!canAct || record.status !== 'handed_over' || !reporter.trim() || feedback.trim().length < 4}>保存反馈并完成闭环</Button>
            {record.feedback && <div className="meal-saved"><b>已保存反馈</b><p>{record.feedback.comment}</p><small>评价：{record.feedback.rating ?? '未提供'} · 实际支出：{record.feedback.actual_cost == null ? '未知' : `¥${record.feedback.actual_cost}`}</small></div>}
            </>}
          </div></div>
          {record && <section className="panel meal-events"><div className="panel-heading"><h2>这次接力的记录</h2><Button size="small" icon={<ReloadOutlined />} disabled={!!busy} onClick={() => void run('正在回读记录', async () => { await install(await api<MealCase>(`/meal/cases/${record.id}`)); })}>重新载入</Button></div><div className="panel-body audit-list">{events.slice().reverse().map(e => <div key={e.id}><i /><strong>{eventNames[e.action] || e.action}</strong><time>{dateTime(e.created_at)}</time><p>{typeof e.payload.note === 'string' ? e.payload.note : ''}</p></div>)}</div></section>}
        </section>
        <aside className="panel meal-resources"><div className="panel-heading"><div><span className="section-number">03</span><h2>番禺助餐资源</h2></div><Tag>{resourceLoading ? '正在读取' : `${catalog.total} 条候选`}</Tag></div><div className="panel-body">
          <Alert type="warning" title="官方历史名单，不能直接接单" description={`名单截至${catalog.snapshot_date || '2025-02-05'}，当前营业、价格、代取和资格须核实。未按距离或实时可用性排序。`} />
          <Input.Search aria-label="搜索饭堂或地址" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索饭堂或地址" allowClear />
          <p className="microcopy">{fields?.town ? `当前筛选：${fields.town}` : '当前浏览全区；建档后按服务镇街筛选'}。展示前12条，可搜索缩小范围。</p>
          <div className="meal-resource-list">{catalog.items.map(r => <div className={`meal-resource-wrap ${selected === r.id ? 'selected' : ''}`} key={r.id}><ResourceCard resource={r} />
            <p className="meal-source-phone">历史咨询电话：{r.source_phone || '未列出'}<br />历史开放日：{r.source_open_days} · 当时是否对外：{r.source_external_residents ? '是' : '否'}<br />以上均不是当前核实结果。</p>
            <Button size="small" block disabled={!record || !!busy || locked || dirty || rawChanged || resourceLoading} onClick={() => { setSelected(r.id); setCheckNote(''); setSupplyStart(''); setSupplyEnd(''); setQuote(''); setTakeaway(false); setEligible(false); setDiet(false); }}>{selected === r.id ? '已选择，仍需当天核实' : '选择并核实这处资源'}<ArrowRightOutlined /></Button>
          </div>)}</div>{resourceLoading ? <p className="microcopy"><Spin size="small" /> 正在读取对应镇街资源…</p> : catalog.total === 0 && <p className="microcopy">未找到匹配资源，请调整关键词或核对镇街；系统不编造替代点。</p>}
        </div></aside>
      </div>
      <footer className="privacy-note">请用家庭/志愿者代号，不输入身份证、病历、电话与详细住址。真实试点须取得知情同意；模型原文会发送至已配置的供应商。当前本机未鉴权版不应开放公网。</footer>
    </main>
  </div>;
}
