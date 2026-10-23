import { useEffect, useState } from 'react';
import { Alert, Button, Collapse, Input, InputNumber, Select, Spin, Switch, Tag, Tooltip } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, DatabaseOutlined, EditOutlined, ExperimentOutlined, FileTextOutlined, HeartOutlined, HistoryOutlined, LinkOutlined, PlusOutlined, ReloadOutlined, SafetyCertificateOutlined, SettingOutlined, TeamOutlined } from '@ant-design/icons';
import { api, dateTime, sourceLabels, timeText } from './api';
import type { AuditEvent, Fields, Health, History, Need, Plan, Rule } from './api';
import { ResourceCard } from './components/ResourceCard';

const SAMPLE = '2026年10月24日上午9点要到医院，家里老人需要有人陪同。我上午没空，妹妹8点到12点有空，回来后还需要安排午餐。生活服务预算150元，具体交通时间还没有确认。';
const ruleLabels: Record<Rule['status'], string> = { pass: '通过', conflict: '冲突', unknown: '未知', not_applicable: '不适用' };
const eventLabels: Record<string, string> = { need_created: '需求已保存', extraction_finished: '字段处理结束', extraction_discarded: '旧识别结果已丢弃', fields_reviewed: '字段已核对或修改', draft_saved: '草案已保存' };

/** 家庭照护工作台：本地状态只用于编辑，已保存结果以服务端为准。 */
export default function App() {
  const [raw, setRaw] = useState(SAMPLE);
  const [health, setHealth] = useState<Health | null>(null);
  const [need, setNeed] = useState<Need | null>(null);
  const [fields, setFields] = useState<Fields | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [busy, setBusy] = useState('正在连接本机服务');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [includeDemo, setIncludeDemo] = useState(false);
  // 编辑字段或原始文本后，旧草案立即标记过期，避免展示成当前安排。
  const dirty = Boolean(need && fields && JSON.stringify(fields) !== JSON.stringify(need.fields));
  const textChanged = Boolean(need && raw !== need.raw_text);
  const stale = Boolean(plan && (plan.is_stale || plan.need_version !== need?.version || dirty || textChanged));

  async function refreshHistory() { setHistory(await api<History[]>('/needs')); }
  async function refreshEvents(id: string) { setEvents(await api<AuditEvent[]>(`/needs/${id}/events`)); }

  async function loadNeed(id: string) {
    // localStorage只存对象ID；刷新后重新请求数据库，不把浏览器缓存当权威。
    const loaded = await api<Need>(`/needs/${id}`);
    const plans = await api<Plan[]>(`/needs/${id}/plans`);
    setNeed(loaded); setFields(loaded.fields); setRaw(loaded.raw_text); setPlan(plans[0] || null);
    setIncludeDemo(Boolean(plans[0]?.resources.some(r => r.data_type === 'demo')));
    localStorage.setItem('anxin.need_id', loaded.id);
    await refreshEvents(id);
  }

  useEffect(() => {
    let active = true;
    async function start() {
      try {
        const status = await api<Health>('/health');
        if (!active) return;
        setHealth(status);
        await refreshHistory();
        const saved = localStorage.getItem('anxin.need_id');
        if (saved) await loadNeed(saved);
      } catch (err) { if (active) setError(String(err instanceof Error ? err.message : err)); }
      finally { if (active) setBusy(''); }
    }
    void start();
    const timer = window.setInterval(() => { void api<Health>('/health').then(h => { if (active) setHealth(h); }).catch(() => { if (active) setHealth(null); }); }, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function run(label: string, operation: () => Promise<void>) {
    // 处理状态由实际异步动作控制，失败时保留页面输入并显示错误。
    setBusy(label); setError(''); setNotice('');
    try { await operation(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(''); }
  }

  function edit(key: keyof Fields, value: unknown) {
    setFields(old => old ? { ...old, [key]: value } as Fields : old);
    setNotice('');
  }

  async function create(mode: 'model' | 'manual' | 'demo') {
    // 三种模式显式区分，只有model调用真实供应商，demo不能冒充AI识别。
    await run(mode === 'model' ? '正在调用模型识别需求' : '正在保存需求', async () => {
      const created = await api<Need>('/needs', { method: 'POST', body: JSON.stringify({ raw_text: raw, mode }) });
      setNeed(created); setFields(created.fields); setPlan(null); setEvents([]);
      localStorage.setItem('anxin.need_id', created.id);
      await Promise.all([refreshHistory(), refreshEvents(created.id)]);
      setNotice(created.extraction_message);
    });
  }

  async function saveFields() {
    if (!need || !fields) return;
    await run('正在保存核对后的字段', async () => {
      const saved = await api<Need>(`/needs/${need.id}`, { method: 'PATCH', body: JSON.stringify({ fields, expected_version: need.version }) });
      setNeed(saved); setFields(saved.fields);
      if (plan) setPlan({ ...plan, is_stale: true });
      await Promise.all([refreshHistory(), refreshEvents(saved.id)]);
      setNotice('字段已保存，请按当前版本重新生成草案。');
    });
  }

  async function generate() {
    if (!need || !fields || textChanged) return;
    await run('正在核对字段并生成、保存草案', async () => {
      // 先保存用户修改，再用返回的新版本生成；不能沿用模型的旧字段。
      let current = need;
      if (dirty || Object.values(need.evidence).some(e => !e.confirmed)) {
        current = await api<Need>(`/needs/${need.id}`, { method: 'PATCH', body: JSON.stringify({ fields, expected_version: need.version }) });
        setNeed(current); setFields(current.fields);
      }
      const saved = await api<Plan>(`/needs/${current.id}/plan-drafts`, { method: 'POST', body: JSON.stringify({ expected_version: current.version, include_demo: includeDemo }) });
      setPlan(saved);
      await Promise.all([refreshHistory(), refreshEvents(current.id)]);
      setNotice('草案已保存。可刷新页面验证回读；待确认项仍需继续完善。');
    });
  }

  function reset() {
    if ((dirty || textChanged) && !window.confirm('当前有未保存的修改，确定新建需求吗？')) return;
    setNeed(null); setFields(null); setPlan(null); setEvents([]); setRaw(''); setError(''); setNotice('');
    localStorage.removeItem('anxin.need_id');
  }

  function textField(key: keyof Fields, label: string, type = 'text', placeholder = '待补充') {
    // 空输入映射为null；没有填写不等于零费用或默认满足条件。
    const value = fields?.[key];
    return <label className="field" key={key}><span>{label}</span><Input aria-label={label} type={type} value={value == null ? '' : String(value).slice(0, type === 'time' ? 5 : undefined)} placeholder={placeholder} onChange={e => edit(key, e.target.value || null)} disabled={!!busy} /></label>;
  }
  function numberField(key: keyof Fields, label: string, min = 0, max = 1000000) {
    const value = fields?.[key];
    return <label className="field" key={key}><span>{label}</span><InputNumber aria-label={label} min={min} max={max} value={typeof value === 'number' ? value : null} placeholder="未知" onChange={v => edit(key, v)} disabled={!!busy} style={{ width: '100%' }} /></label>;
  }

  // 页面只汇总后端规则结果，不能自行把unknown显示为通过。
  const counts = plan ? { pass: plan.rules.filter(r => r.status === 'pass').length, unknown: plan.rules.filter(r => r.status === 'unknown').length, conflict: plan.rules.filter(r => r.status === 'conflict').length } : null;

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#" onClick={e => e.preventDefault()}><span className="brand-mark"><HeartOutlined /></span><span>安心接力<small>ANXIN RELAY</small></span></a>
      <nav aria-label="主导航"><button className="nav-active"><FileTextOutlined /> 工作台</button><Tooltip title="将在后续版本开放"><button disabled><TeamOutlined /> 家庭任务 <span>后续</span></button></Tooltip><Tooltip title="将在后续版本开放"><button disabled><SettingOutlined /> 资源运营 <span>后续</span></button></Tooltip></nav>
      <div className="top-status"><span className={`status-dot ${health ? 'online' : ''}`} />{health ? '本机服务已连接' : '服务未连接'}<Tag>V0.1</Tag></div>
    </header>

    <main>
      <section className="page-heading"><div><div className="eyebrow">家庭照护 · 需求编排工作台</div><h1>把照护安排，稳稳接住。</h1><p className="tagline">把家庭照护需求变成有依据、可追踪的服务安排</p></div><Button aria-label="新建需求" icon={<PlusOutlined />} onClick={reset} disabled={!!busy}>新建需求</Button></section>
      <section className="scenario-bar"><div><span className="scene-icon"><HeartOutlined /></span><div><strong>老人复诊当日准备与返家助餐安排</strong><p>{fields?.region || '演示片区待设置'} <span>·</span> 北京时间 <span>·</span> 生活事务协调</p></div></div><Tag icon={<SafetyCertificateOutlined />} color="blue">依据可查 · 状态可追踪</Tag></section>

      {!health?.model_configured && <div className="model-notice"><ExperimentOutlined /><span>模型API尚未配置。可用演示字段跑通草案，也可手工填写；这两种模式均不调用模型。</span><a href="#setup">配置说明</a></div>}
      {error && <Alert className="global-alert" type="error" showIcon title="操作未完成" description={error} closable onClose={() => setError('')} />}
      {notice && <Alert className="global-alert" type="info" showIcon title={notice} closable onClose={() => setNotice('')} />}

      {/* 三栏按需求核对、草案依赖、资源依据分类；窄屏由CSS顺序堆叠。 */}
      <div className="workspace">
        <section className="panel need-panel" aria-labelledby="need-title"><div className="panel-heading"><div><span className="section-number">01</span><h2 id="need-title">说清需求</h2></div><span className="subtle">输入与核对</span></div>
          <div className="panel-body"><label className="input-label" htmlFor="need-input">今天，家里需要怎样的安排？</label><Input.TextArea id="need-input" aria-label="家庭照护需求" value={raw} onChange={e => setRaw(e.target.value)} autoSize={{ minRows: 6, maxRows: 12 }} maxLength={6000} disabled={!!busy} placeholder="例如：哪天需要陪同，谁能帮忙，返家后还需要安排什么？" />
          <div className="input-meta"><Button aria-label="载入演示需求" type="link" size="small" icon={<ExperimentOutlined />} onClick={() => setRaw(SAMPLE)} disabled={!!busy}>载入演示需求</Button><span>{raw.length}/6000</span></div><p className="microcopy">合成演示需求不代表真实预约或服务供给。</p>
          <div className="input-actions"><Button aria-label="识别需求" type="primary" block onClick={() => void create('model')} disabled={!!busy || raw.trim().length < 2} icon={<ArrowRightOutlined />}>识别需求</Button><div className="secondary-actions"><Button onClick={() => void create('demo')} disabled={!!busy || raw !== SAMPLE}>使用演示字段</Button><Button onClick={() => void create('manual')} disabled={!!busy || raw.trim().length < 2}>手工填写</Button></div></div>
          {need && <div className="extraction-mode"><Tag color={need.extraction_status === 'succeeded' ? 'blue' : 'gold'}>{need.extraction_status === 'succeeded' ? '真实API识别' : need.extraction_status === 'demo' ? '演示字段 · 未调用模型' : need.extraction_status === 'manual' ? '手工填写 · 未调用模型' : '自动识别未完成'}</Tag><p>{need.extraction_message}</p>{need.extraction_review?.policy_version && <p className="microcopy">明确事实检查：{need.extraction_review.explicit_fact_checks === 'passed' ? '已通过（仍需人工核对）' : '未接受结果'} · 模型调用{need.extraction_review.model_calls || 0}次{need.extraction_review.repair_applied ? ' · 已进行一次自动修正' : ''}</p>}</div>}
          {textChanged && <Alert type="warning" showIcon title="原始需求已修改，请重新识别或进入手工填写后再生成。" />}

          {fields && <div className="field-editor"><div className="block-heading"><h3>核对关键信息</h3><Tag>需求 v{need?.version}</Tag></div><div className="field-grid">{textField('service_date', '服务日期', 'date')}{textField('arrival_deadline', '到院截止时间', 'time')}{numberField('budget_limit', '预算上限（元）')}{textField('region', '服务地区', 'text', '演示可填：演示片区')}{textField('origin', '出发地点')}{textField('destination', '医院目的地')}</div>
          <Collapse ghost items={[{ key: 'details', label: '完善陪同、交通与午餐信息', children: <>
            <div className="field-grid">{textField('meeting_point', '集合地点')}{textField('care_recipient', '被照护人')}{textField('participant_name', '候选陪同人')}{textField('requester_unavailable', '本人不可用说明')}{textField('availability_start', '陪同可用起点', 'time')}{textField('availability_end', '陪同可用终点', 'time')}
              <label className="field"><span>是否需要陪同</span><Select aria-label="是否需要陪同" value={fields.accompaniment_required === null ? 'unknown' : fields.accompaniment_required ? 'yes' : 'no'} options={[{ value: 'unknown', label: '待核对' }, { value: 'yes', label: '需要' }, { value: 'no', label: '不需要' }]} onChange={v => edit('accompaniment_required', v === 'unknown' ? null : v === 'yes')} disabled={!!busy} /></label>
              <label className="field"><span>陪同接受情况</span><Select aria-label="陪同接受情况" value={fields.acceptance_status} options={[{ value: 'unknown', label: '未确认' }, { value: 'confirmed', label: '用户填报已接受' }, { value: 'declined', label: '已拒绝' }]} onChange={v => edit('acceptance_status', v)} disabled={!!busy} /></label>
              {textField('transport', '交通方式')}{numberField('travel_minutes', '单程时长（分钟）', 1, 1440)}{textField('return_time', '预计返家时间', 'time')}{textField('budget_scope', '预算包含的费用')}
              <label className="field"><span>是否需要午餐</span><Select aria-label="是否需要午餐" value={fields.meal_required === null ? 'unknown' : fields.meal_required ? 'yes' : 'no'} options={[{ value: 'unknown', label: '待核对' }, { value: 'yes', label: '需要' }, { value: 'no', label: '不需要' }]} onChange={v => edit('meal_required', v === 'unknown' ? null : v === 'yes')} disabled={!!busy} /></label>
              {textField('meal_time', '午餐时间', 'time')}{numberField('meal_people', '用餐人数', 1, 30)}{textField('diet_notes', '饮食限制说明')}
            </div><div className="cost-editor"><h4>费用核对</h4><p>仅填写已明确的项目；金额留空表示未知。</p>{fields.costs.map((cost, i) => <div className="cost-row" key={i}><Input aria-label={`费用项目${i + 1}`} placeholder="项目名称" value={cost.label} disabled={!!busy} onChange={e => edit('costs', fields.costs.map((c, j) => j === i ? { ...c, label: e.target.value } : c))} /><InputNumber aria-label={`费用金额${i + 1}`} placeholder="未知" min={0} value={cost.amount} disabled={!!busy} onChange={v => edit('costs', fields.costs.map((c, j) => j === i ? { ...c, amount: v } : c))} /><Button aria-label={`移除费用${i + 1}`} disabled={!!busy} onClick={() => edit('costs', fields.costs.filter((_, j) => j !== i))}>移除</Button></div>)}<Button size="small" icon={<PlusOutlined />} disabled={!!busy} onClick={() => edit('costs', [...fields.costs, { label: '', amount: null }])}>添加费用项目</Button></div>
          </> }]} />
          <Button aria-label="保存核对字段" block icon={<EditOutlined />} disabled={!!busy || textChanged} onClick={() => void saveFields()}>保存核对字段</Button>
          {need && need.missing_fields.length > 0 && <div className="missing-summary"><strong>还需补充或核对</strong><p>先确认出发地点与医院、交通时长、家属接受情况。</p><div className="missing-tags">{need.missing_fields.slice(0, 6).map(m => <Tag key={m.field}>{m.label}</Tag>)}</div><span className="microcopy">共{need.missing_fields.length}项，以保存后的字段为准；缺项不阻止保存草案。</span></div>}
          </div>}
          <div className="history-section"><h3><HistoryOutlined /> 最近需求</h3>{history.length === 0 ? <p className="subtle">保存后的需求会出现在这里</p> : history.slice(0, 5).map(h => <button key={h.id} disabled={!!busy} className={`history-item ${need?.id === h.id ? 'selected' : ''}`} onClick={() => {
            if ((dirty || textChanged) && !window.confirm('当前有未保存的修改，确定切换需求吗？')) return;
            void run('正在回读已保存需求', () => loadNeed(h.id));
          }}><span>{h.raw_text}</span><small>{dateTime(h.updated_at)} · v{h.version}</small></button>)}</div>
          </div>
        </section>

        <section className="panel plan-panel" aria-labelledby="plan-title"><div className="panel-heading"><div><span className="section-number">02</span><h2 id="plan-title">当天的接力安排</h2></div><Tag color={plan?.status === 'conflict' ? 'red' : 'gold'}>{plan ? plan.status === 'conflict' ? '存在冲突' : '待补充草案' : '等待生成'}</Tag></div>
          <div className="plan-toolbar"><span><ClockCircleOutlined /> {fields?.service_date || '日期待核对'}<span className="toolbar-divider">/</span>到院 {timeText(fields?.arrival_deadline)}</span><span>生活事务草案</span></div>
          <div className="panel-body plan-content">
          {!plan ? <div className="plan-empty"><div className="empty-illustration"><span /><span /><span /><HeartOutlined /></div><h3>从一个需求，接好一天的安排</h3><p>核对左侧信息后，生成准备、出行、陪同、返家与午餐的草案。</p><div className="empty-flow">说明需求 <ArrowRightOutlined /> 核对条件 <ArrowRightOutlined /> 保存安排</div><p className="microcopy">每项安排保留依据；尚不确定的条件会明确标出。</p></div> : <>
            <div className="plan-intro"><div><span className="eyebrow">CARE RELAY / 草案 v{plan.version}</span><h3>{plan.fields_snapshot.care_recipient || '家庭成员'}的当日安排</h3></div><span className="plan-version">基于需求 v{plan.need_version}</span></div>
            {stale ? <Alert type="warning" showIcon title="需求已有修改，当前显示旧版草案，请重新生成。" /> : <div className="draft-warning"><ClockCircleOutlined /> 仍有待确认项，暂不能作为已落实的服务安排。</div>}
            <div className="timeline">{plan.tasks.map((task, index) => <article className="timeline-item" key={task.id}><div className="timeline-marker">{String(index + 1).padStart(2, '0')}</div><div className="task-card"><div className="task-heading"><h4>{task.title}</h4><Tag>草案</Tag></div><p className="task-time"><ClockCircleOutlined /> {task.timing}</p>{task.owner_candidate && <div className="owner-line"><TeamOutlined /> 候选：{task.owner_candidate}<span>{task.acceptance_status === 'confirmed' ? '用户填报已接受' : task.acceptance_status === 'declined' ? '已拒绝，需更换' : '尚未确认接受'}</span></div>}<p className="task-reason">{task.reason}</p><div className="task-footer"><span><LinkOutlined /> {task.dependencies.length ? `依赖：${task.dependencies.map(d => plan.tasks.find(t => t.id === d)?.title || d).join('、')}` : '起始事项'}</span><Tag color="blue">模板建议</Tag></div>{task.evidence.length > 0 && <Collapse ghost size="small" items={[{ key: 'evidence', label: `${task.evidence.length}条字段依据`, children: <div className="task-evidence">{task.evidence.map(e => <p key={e.field}><Tag>{sourceLabels[e.source] || e.source}</Tag> {e.quote}</p>)}</div> }]} />}</div></article>)}</div>
            <div className="rules-block"><div className="block-heading"><h3><SafetyCertificateOutlined /> 约束检查</h3><span className="subtle">确定性规则</span></div><div className="rule-counts"><span>{counts?.pass} 项通过</span><span>{counts?.unknown} 项未知</span><span>{counts?.conflict} 项冲突</span></div>{plan.rules.map(rule => <div className={`rule-row rule-${rule.status}`} key={rule.code}><span className="rule-symbol">{rule.status === 'pass' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}</span><div><strong>{rule.title}</strong><p>{rule.detail}</p></div><Tag color={rule.status === 'conflict' ? 'red' : rule.status === 'unknown' ? 'gold' : undefined}>{ruleLabels[rule.status]}</Tag></div>)}</div>
          </>}
          </div>
          <div className="plan-bottom"><div className="demo-switch"><Switch size="small" checked={includeDemo} onChange={setIncludeDemo} disabled={!!busy} aria-label="显示合成演示资源" /><span>包含合成演示资源</span><Tooltip title="仅在地区填为“演示片区”时匹配；不代表真实供给"><ExperimentOutlined /></Tooltip></div><Button aria-label={plan ? '按当前信息重新生成并保存' : '确认并生成草案'} type="primary" size="large" block icon={plan ? <ReloadOutlined /> : <ArrowRightOutlined />} disabled={!!busy || !need || textChanged} loading={!!busy && busy.includes('生成')} onClick={() => void generate()}>{plan ? '按当前信息重新生成并保存' : '确认并生成草案'}</Button><p>生成成功即写入数据库，不触发预约或派单。</p></div>
        </section>

        <aside className="evidence-column"><section className="panel"><div className="panel-heading"><div><span className="section-number">03</span><h2>资源与依据</h2></div><SafetyCertificateOutlined /></div><div className="panel-body"><div className="evidence-intro"><span className="evidence-icon"><LinkOutlined /></span><h3>有依据，才放心</h3><p>把用户原话、模板建议与资源资料分开呈现，未知的信息始终保留。</p></div>
          <div className="block-heading"><h3>匹配资源</h3><Tag>{plan?.resources.length || 0} 条</Tag></div><Button size="small" className="public-resource-query" disabled={!!busy || !fields} onClick={() => { edit('region', '厦门市'); setNotice('已将查询地区补充为厦门市，请重新生成并核对具体地址。此操作不会创建预约。'); }}>查询厦门公开资源</Button><p className="microcopy">点击会把地区补为厦门市；重新生成后匹配公开地点与官方查询入口。</p>{plan?.resources.length ? plan.resources.map(r => <ResourceCard key={r.id} resource={r} />) : <div className="resource-empty"><DatabaseOutlined /><p>当前没有匹配的公开资源</p><span>补充厦门市或具体区后重新生成。公开资料不代表本次已确认供给；演示资料需主动开启。</span></div>}
          <div className="evidence-legend"><div><i className="legend-blue" /><span>用户原话／用户补充</span></div><div><i className="legend-gray" /><span>场景模板建议</span></div><div><i className="legend-amber" /><span>资源资料／合成演示</span></div></div><p className="microcopy">公开资料也不代表本次已预约，价格与可用时段仍需确认。</p>
          </div></section>

          <section className="panel budget-panel"><div className="panel-body"><div className="block-heading"><h3>生活服务预算</h3><span className="subtle">CNY</span></div><div className="budget-value">{fields?.budget_limit == null ? '待补充' : <><small>¥</small>{fields.budget_limit}<span>预算上限</span></>}</div><div className="budget-row"><span>已填写费用小计</span><strong>{plan?.budget.known_subtotal == null ? '未知' : `¥${plan.budget.known_subtotal}`}</strong></div><div className="budget-row"><span>预计总价</span><strong>待核实</strong></div><p className="microcopy">未知价格不按0元计入，预算上限不是预计支出。</p></div></section>

          <section className="panel"><div className="panel-body"><h3><HistoryOutlined /> 真实操作记录</h3>{events.length ? <div className="audit-list">{events.slice(0, 6).map(e => <div key={e.id}><i /><strong>{eventLabels[e.action] || e.action}</strong><time>{dateTime(e.created_at)}</time></div>)}</div> : <p className="subtle">保存需求后显示服务端事件记录。</p>}</div></section>
          <details id="setup" className="setup-note"><summary>模型API配置说明</summary><p>复制工程根目录的.env.example为.env，填写MODEL_BASE_URL、MODEL_NAME与MODEL_API_KEY，再重启后端。密钥只留在本机后端，不填写到页面。</p><p>地址使用供应商提供的兼容API基础地址。配置存在不表示调用已经验证，需用“识别需求”实际测试。</p></details>
        </aside>
      </div>
      <div className="privacy-note"><SafetyCertificateOutlined /> 本机开发版 · 请使用演示或脱敏信息 · 当前未开放成员认领与真实预约</div>
    </main>

    <footer className="statusbar"><div>{busy ? <Spin size="small" /> : <span className={`status-dot ${health ? 'online' : ''}`} />}<span role="status">{busy || (health ? '服务就绪' : '服务未连接')}</span><span className="footer-separator">|</span><DatabaseOutlined /><span>存储 {health?.storage === 'ok' ? '已连接' : '待连接'}</span></div><div><span>{need ? `需求 v${need.version}` : '尚未创建需求'}</span><span>{plan ? `草案 v${plan.version}${stale ? ' · 已过期' : ''}` : '尚未生成草案'}</span><span>保存：{dateTime(plan?.created_at)}（北京时间）</span></div></footer>
  </div>;
}
