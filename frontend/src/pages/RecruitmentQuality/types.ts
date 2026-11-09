export interface QualityRules {
  screening_days: number;
  department_assignment_days: number;
  department_decision_days: number;
  interview_arrangement_days: number;
  next_interview_days: number;
  interview_decision_days: number;
  offer_send_days: number;
  result_update_days: number;
  exception_days: number;
  department_review_required: boolean;
}
export interface Metrics {
  completed_nodes: number; required_nodes: number; process_rate: number | null;
  overdue_count: number; missing_count: number; unknown_count: number;
  historical_count: number; longest_overdue_hours: number;
  business_completed_nodes?: number; business_pending_nodes?: number; business_terminated_nodes?: number;
}
export interface Person extends Metrics {
  user_id: string | null; name: string; position_count: number; candidate_count: number;
  open_position_count: number; active_candidate_count: number;
}
export interface QualityNode {
  flow_id?: string;
  id: string; binding_id: string; key: string; position_id: string; position_title: string;
  resume_id: string | null; candidate_name: string | null; owner_id: string | null; owner_name: string;
  current_owner_id?: string | null; current_owner_name?: string;
  executor_id: string | null; executor_name: string; stage: string; label: string;
  status: string; eligible: boolean; complete: boolean; historical: boolean;
  business_status?: 'completed' | 'pending' | 'terminated' | 'paused'; business_result?: string;
  timeliness_status?: string;
  fields: { label: string; valid: boolean; status?: string; started_at?: string | null; completed_at?: string | null; due_at?: string | null; late_due_at?: string | null; policy_version?: number | null; business_completed?: boolean; business_stopped?: boolean }[]; missing: string[];
  due_at: string | null; paused: boolean; overdue: boolean; overdue_hours: number;
  href: string; policy_id: string; policy_name: string; policy_version: number; evidence: string[];
  actions: { kind: string; reason: string; actor_id: string | null; actor_name?: string;
    occurred_at: string; details: Record<string, string> }[];
}
export interface QualityFlow {
  id: string; binding_id: string; resume_id: string; position_id: string; position_title: string;
  started_at: string; is_current: boolean; status: string; previous_status: string | null;
  candidate_name?: string;
  department_required: boolean; owner_id: string | null; owner_name: string;
  ended_at?: string | null; end_reason?: 'transfer' | 'restart' | null;
  interviews: { id: string; round: number; status: string | null; result: string | null;
    scheduled_at: string | null; ended_at: string | null; cancelled_at: string | null }[];
}
export interface Report {
  enabled: boolean; as_of: string; rollout_at: string | null; summary: Metrics; people: Person[];
  nodes: QualityNode[]; positions: { id: string; title: string }[];
  flows?: QualityFlow[];
}
export interface Policy {
  id: string; name: string; version: number; position_id: string | null;
  rules: QualityRules; created_at: string;
}
export interface Config {
  enabled: boolean; rollout_at: string | null; defaults: QualityRules; policies: Policy[];
}
