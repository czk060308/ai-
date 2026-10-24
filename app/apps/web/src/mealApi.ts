/** 助餐业务类型；操作者记录与商家预约严格区分。 */
import type { Resource, Rule, Evidence } from './api';

export interface MealFields {
  service_date: string | null; region: string | null; town: string | null; care_recipient: string | null;
  meal_people: number | null; handover_deadline: string | null; handover_place: string | null;
  diet_notes: string | null; budget_limit: number | null; pickup_person: string | null;
  availability_start: string | null; availability_end: string | null; planned_pickup: string | null;
  travel_minutes: number | null;
}
export interface MealResource extends Resource {
  town: string; source_phone: string; source_open_days: string; source_external_residents: boolean;
  snapshot_date: string;
}
export interface MealCase {
  id: string; version: number; raw_text: string; fields: MealFields; data_type: 'demo' | 'pilot'; status: string;
  family_code: string | null; consent_confirmed: boolean; extraction_status: string; extraction_message: string;
  extraction_review: { model_calls?: number; repair_applied?: boolean }; evidence: Record<string, Evidence>;
  checks: { missing_fields: { field: string; label: string }[]; rules: Rule[]; ready_to_accept: boolean; suggested_steps: string[];
    pickup_window: { feasible: boolean; earliest: string | null; latest: string | null; basis: string } | null };
  supply_check: { resource_id: string; resource_snapshot: MealResource; supply_start: string; supply_end: string;
    quoted_total: number; note: string; verified_by: string; checked_at: string } | null;
  acceptance: { actor: string; note: string; at: string } | null;
  latest_exception: { actor: string; note: string; at: string } | null;
  feedback: { comment: string; rating: number | null; actual_cost: number | null; reporter: string } | null;
  created_at: string; updated_at: string;
}
export interface MealHistory { id: string; version: number; status: string; data_type: string; service_date: string | null; town: string | null; updated_at: string }
export interface MealStats { pilot_cases: number; demo_cases: number; families: number; completed: number;
  feedback_count: number; rating_count: number; rating_mean: number | null; completion_denominator: number; notes: string }
export interface MealResources { items: MealResource[]; total: number; towns: string[]; snapshot_date: string }
export const mealStatuses: Record<string, string> = { draft: '待补问与核实', verified: '已记录供餐核实', accepted: '已确认接受',
  picked_up: '已记录取餐', handed_over: '已交接待反馈', completed: '反馈闭环完成', blocked: '受阻待重排', cancelled: '已取消' };
