import { Tag } from 'antd';
import type { Resource } from '../api';

/** 公开资料只核对来源页面，不代表商家营业、价格或本次可用性。 */
export function ResourceCard({ resource: r }: { resource: Resource }) {
  const demo = r.data_type === 'demo';
  const source = r.source_url && /^https:\/\//.test(r.source_url) ? r.source_url : null;
  return <article className={`resource-card ${demo ? 'resource-demo' : 'resource-public'}`}>
    <Tag color={demo ? 'gold' : 'blue'}>{demo ? '合成演示 · 未核实' : '公开资料 · 本次服务待核实'}</Tag>
    {!demo && r.scope === 'city_directory' && <Tag>{r.category === 'directory' ? '官方查询入口' : '官方服务说明'}</Tag>}
    {!demo && r.source_stale && <Tag color="orange">资料较早或日期未知，请先核实</Tag>}
    <h4>{r.name}</h4><p>{r.description}</p>
    <div className="resource-meta">{r.region} · 价格{r.price === null ? '未知' : r.price + '元'}</div>
    {r.address && <p>地点线索：{r.address}</p>}
    {r.match_reason && <p>{r.match_reason}</p>}
    <p className="source-note">来源：{r.source_note}</p>
    {source && <a className="resource-source" href={source} target="_blank" rel="noopener noreferrer" title={r.source_title}>查看官方来源 ↗</a>}
    {!demo && <p className="source-note">发布：{r.published_at || '未标明'} · 页面核对：{r.checked_at || '待核对'}<br />仅核对公开页面，未联系服务主体。</p>}
    <span className="microcopy">待核实：{r.unknown_fields.join('、')}</span>
  </article>;
}
