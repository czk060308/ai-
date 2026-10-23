/** HTTP边界与共享类型：页面只连接本项目API，绝不携带供应商密钥。 */
export interface CostItem { label: string; amount: number | null }
export interface Fields {
  scene_id: 'care_visit_day'; timezone: 'Asia/Shanghai'; currency: 'CNY';
  service_date: string | null; arrival_deadline: string | null;
  region: string | null; origin: string | null; destination: string | null; meeting_point: string | null;
  care_recipient: string | null; accompaniment_required: boolean | null;
  participant_name: string | null; availability_start: string | null; availability_end: string | null;
  acceptance_status: 'unknown' | 'confirmed' | 'declined'; requester_unavailable: string | null;
  transport: string | null; travel_minutes: number | null; return_time: string | null;
  meal_required: boolean | null; meal_time: string | null; meal_people: number | null; diet_notes: string | null;
  budget_limit: number | null; budget_scope: string | null; costs: CostItem[];
}
export interface Evidence { source: string; quote: string; confirmed: boolean }
export interface Missing { field: string; label: string; reason: string }
export interface Need {
  id: string; raw_text: string; fields: Fields; evidence: Record<string, Evidence>; version: number;
  extraction_status: string; extraction_message: string; missing_fields: Missing[];
  extraction_review?: { policy_version?: string; model_calls?: number; repair_applied?: boolean; repair_reason?: string; explicit_fact_checks?: string };
  created_at: string; updated_at: string;
}
export interface Task {
  id: string; title: string; timing: string; dependencies: string[]; owner_candidate: string | null;
  acceptance_status: string; status: string; reason: string; evidence: (Evidence & { field: string })[]; template_source: string;
}
export interface Rule { code: string; status: 'pass' | 'conflict' | 'unknown' | 'not_applicable'; title: string; detail: string }
export interface Resource {
  id: string; name: string; category: string; region: string; data_type: string; description: string;
  source_note: string; evidence_status: string; price: number | null; unknown_fields: string[];
  address?: string | null; source_url?: string; source_title?: string; published_at?: string | null;
  checked_at?: string; source_stale?: boolean; match_reason?: string; scope?: 'local_site' | 'city_directory';
}
export interface Plan {
  id: string; need_id: string; need_version: number; version: number; created_at: string; is_stale: boolean;
  status: string; tasks: Task[]; rules: Rule[]; missing_fields: Missing[]; fields_snapshot: Fields; resources: Resource[];
  budget: { limit: number | null; known_subtotal: number | null; has_unknown_costs: boolean; total: null };
}
export interface Health { status: string; storage: string; model_configured: boolean; version: string }
export interface History { id: string; raw_text: string; version: number; updated_at: string; extraction_status: string }
export interface AuditEvent { id: string; action: string; created_at: string; payload: Record<string, unknown> }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  // 超时与服务端错误统一转为可见提示；不使用空对象伪装请求成功。
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 65000);
  try {
    const response = await fetch('/api' + path, { ...options, signal: controller.signal, headers: { 'Content-Type': 'application/json', ...options.headers } });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.errors?.map((e: { field: string; message: string }) => `${e.field}: ${e.message}`).join('；');
      throw new Error(`${data.message || '请求失败'}${detail ? '：' + detail : ''}${data.trace_id ? `（追踪号 ${data.trace_id}）` : ''}`);
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('请求超时，输入已保留，请检查服务状态后重试。');
    if (error instanceof TypeError) throw new Error('无法连接本机API，请确认后端已启动。');
    throw error;
  } finally { window.clearTimeout(timeout); }
}

export function dateTime(value?: string) {
  // 数据库时间戳按UTC保存，所有页面统一转换为北京时间。
  return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未保存';
}

export function timeText(value?: string | null) { return value ? value.slice(0, 5) : '待确认'; }

export const sourceLabels: Record<string, string> = {
  demo_fixture: '演示字段', model_quote: '模型提取原话', user_edit: '用户补充',
};
