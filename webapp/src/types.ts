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

export interface DiagnosisReportOut {
  problem: ProblemOut;
  drivers: DriverOut[];
  recommendation: RecommendationOut;
  explanation: string;
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
