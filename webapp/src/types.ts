// Mirrors src/companysim/api/schemas.py — the wire format the backend speaks.

export interface OrgSummary {
  id: number;
  name: string;
  seed: number;
  headcount: number;
  department_count: number;
  team_count: number;
}

export interface DepartmentOut {
  id: number;
  name: string;
  salary_multiplier: number;
  head_employee_id: number | null;
}

export interface DepartmentIn {
  name?: string;
  salary_multiplier?: number;
}

export interface TeamOut {
  id: number;
  name: string;
  department_id: number;
  manager_employee_id: number | null;
  member_count: number;
}

export interface TeamIn {
  name?: string;
  department_id?: number;
  manager_employee_id?: number;
}

export interface EmployeeOut {
  id: number;
  full_name: string;
  email: string;
  department_id: number;
  team_id: number;
  manager_id: number | null;
  level: string;
  role: string;
  tenure_months: number;
  base_salary: number;
  work_mode: string;
  promotions_count: number;
  workload_perceived: number;
  manager_support_score: number;
  psychological_safety_perceived: number;
  financial_security_score: number;
}

export interface EmployeeIn {
  full_name?: string;
  department_id?: number;
  team_id?: number;
  manager_id?: number;
  level?: string;
  role?: string;
  tenure_months?: number;
  base_salary?: number;
  work_mode?: string;
  workload_perceived?: number;
  manager_support_score?: number;
  psychological_safety_perceived?: number;
  financial_security_score?: number;
}

export type ScenarioEventType =
  | "layoff"
  | "hire"
  | "promotion"
  | "policy_change"
  | "retention_bonus"
  | "workload_relief"
  | "manager_coaching"
  | "budget_cut"
  | "reorg"
  | "termination"
  | "transfer"
  | "life_event";

export interface ScenarioEventIn {
  type: ScenarioEventType;
  at_tick: number;
  params: Record<string, unknown>;
}

export interface SimulateRequest {
  ticks: number;
  replicates: number;
  seed: number;
  events: ScenarioEventIn[];
}

export interface SimulateResponse {
  mode: "single" | "monte_carlo";
  ticks: number;
  replicates: number;
  columns: string[];
  rows: Record<string, number>[];
}

export interface ProblemOut {
  tick: number;
  metric: string;
  description: string;
  severity: number;
}

export interface DriverOut {
  segment_type: string;
  segment_id: string;
  feature: string;
  segment_mean: number;
  org_mean: number;
  deviation: number;
  score: number;
}

export interface RecommendationOut {
  event_type: string;
  rationale: string;
  target_department: number | null;
  target_team: number | null;
  target_employee_ids: number[];
  suggested_params: Record<string, unknown>;
}

export interface NotesSummaryOut {
  n_notes: number;
  mean_sentiment: number;
  top_themes: string[];
  sample_quotes: string[];
}

export interface DiagnosisReportOut {
  problem: ProblemOut;
  drivers: DriverOut[];
  recommendation: RecommendationOut;
  explanation: string;
  notes_summary: NotesSummaryOut | null;
}

export interface DiagnoseResponse {
  model_available: boolean;
  problems_detected: number;
  reports: DiagnosisReportOut[];
}

export const LEVELS = ["IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3", "VP", "CXO"] as const;
export const WORK_MODES = ["onsite", "hybrid", "remote"] as const;
export const LIFE_EVENT_TYPES = [
  "bereavement", "birth_or_adoption", "moved_house", "divorce_or_separation",
  "serious_illness", "caregiving_onset", "financial_shock",
] as const;

export interface AtRiskEmployeeOut {
  employee_id: number;
  full_name: string;
  department_id: number;
  team_id: number;
  level: string;
  turnover_probability: number;
  risk_tier: string;
}

export interface AtRiskResponse {
  model_available: boolean;
  employees: AtRiskEmployeeOut[];
}

export type InterventionType = "retention_bonus" | "workload_relief" | "manager_coaching";

export interface CompareInterventionRequest {
  intervention_type: InterventionType;
  top_k: number;
  at_tick: number;
  params: Record<string, unknown>;
  horizon_ticks: number;
  replicates: number;
  seed: number;
}

export interface CompareInterventionResponse {
  model_available: boolean;
  target_employee_count: number;
  baseline_target_quits_p50: number;
  treated_target_quits_p50: number;
  quits_avoided_mean: number;
  quits_avoided_p50: number;
  quits_avoided_p05: number;
  quits_avoided_p95: number;
  estimated_cost: number;
}

export interface ModelStatusResponse {
  model_available: boolean;
  metadata: Record<string, unknown>;
  pending_training_examples: number;
}

export interface TrainModelRequest {
  headcount: number;
  replicates: number;
  horizon: number;
  seed: number;
  tolerance: number;
  force_promote: boolean;
}

export interface TrainModelResponse {
  decision: "PROMOTE" | "BLOCK";
  reason: string;
  candidate_eval: Record<string, number>;
  production_eval: Record<string, number> | null;
  train_report: Record<string, number>;
  promoted_at: string | null;
  n_live_examples: number;
}

export type RunType = "simulate" | "diagnose";

export interface RunSummaryOut {
  id: number;
  run_type: RunType;
  created_at: string;
  summary: string;
}

export interface RunDetailOut extends RunSummaryOut {
  request: SimulateRequest;
  response: SimulateResponse | DiagnoseResponse;
}

export interface RiskHistoryPoint {
  run_id: number;
  computed_at: string;
  turnover_probability: number;
  risk_tier: string;
  model_available: boolean;
}

export interface RiskTrendPoint {
  run_id: number;
  computed_at: string;
  mean_risk: number;
  employee_count: number;
  model_available: boolean;
}
