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

export const EVENT_TYPE_LABELS: Record<ScenarioEventType, string> = {
  layoff: "Layoff",
  hire: "Hire",
  promotion: "Promotion",
  policy_change: "Policy Change",
  retention_bonus: "Retention Bonus",
  workload_relief: "Workload Relief",
  manager_coaching: "Manager Coaching",
  budget_cut: "Budget Cut",
  reorg: "Reorg",
  termination: "Termination",
  transfer: "Transfer",
  life_event: "Life Event",
};

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
  n_llm_generated: number;
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

export interface ThemeFrequencyOut {
  theme: string;
  count: number;
}

export interface ExitNoteSentimentPointOut {
  run_id: number;
  generated_at: string;
  mean_sentiment: number;
  n_notes: number;
}

export interface ExitNoteQuoteOut {
  id: number;
  run_id: number;
  employee_id: number | null;
  text: string;
  sentiment: number;
  themes: string[];
  is_llm_generated: boolean;
  is_backfilled: boolean;
  generated_at: string;
}

export interface ExitNotesInsightsResponse {
  n_notes_total: number;
  mean_sentiment_overall: number;
  n_llm_generated_total: number;
  n_backfilled_total: number;
  theme_frequency: ThemeFrequencyOut[];
  sentiment_trend: ExitNoteSentimentPointOut[];
  recent_quotes: ExitNoteQuoteOut[];
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

export interface PromotionLogEntryOut {
  timestamp: string;
  decision: "PROMOTE" | "BLOCK";
  reason: string;
  candidate_eval: Record<string, number>;
  production_eval: Record<string, number> | null;
  n_live_examples: number;
  training_seed: number;
  training_headcount: number;
}

export interface FeatureImportanceOut {
  feature: string;
  importance: number;
}

export interface ModelQualityResponse {
  history: PromotionLogEntryOut[];
  feature_importances: FeatureImportanceOut[];
}

export interface ChatMessageIn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  tools_used: string[];
  llm_available: boolean;
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

export const DOCUMENT_KINDS = [
  "roster",
  "offer_letter",
  "cv",
  "performance_review",
  "resignation_letter",
  "pulse_export",
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];

export interface SourceDocumentOut {
  id: number;
  kind: string;
  filename: string;
  content_hash: string;
  uploaded_at: string;
  as_of_date: string | null;
  extraction_status: string;
  extractor: string | null;
  extraction_error: string | null;
}

export interface ExtractedFactOut {
  id: number;
  document_id: number;
  target_table: string;
  target_employee_id: number | null;
  field_name: string;
  proposed_value: string;
  current_value: string | null;
  confidence: number;
  review_status: string;
  evidence_span: string;
  applied_at: string | null;
}

export interface DocumentDetailOut extends SourceDocumentOut {
  raw_text: string;
  pending_facts: ExtractedFactOut[];
}

export interface ExtractDocumentResponse {
  document: SourceDocumentOut;
  n_facts_staged: number;
  facts: ExtractedFactOut[];
}

export interface ApplyFactsResponse {
  n_applied: number;
  n_rejected: number;
  n_employees_created: number;
  unapplied: string[];
}

export interface IngestTotalsOut {
  n_documents: number;
  n_pending_facts: number;
  n_applied_facts: number;
  n_performance_reviews: number;
  n_ingested_exit_notes: number;
}

export interface TokenTotalsOut {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface FeatureUsageOut {
  feature: string;
  requests: number;
  total_tokens: number;
}

export interface LlmRequestOut {
  id: number;
  feature: string;
  model: string;
  org_id: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  created_at: string;
}

export interface LlmUsageResponse {
  all_time: TokenTotalsOut;
  today: TokenTotalsOut;
  week: TokenTotalsOut;
  by_feature: FeatureUsageOut[];
  recent: LlmRequestOut[];
}

export interface LineageFieldOut {
  column: string;
  value: string;
  note: string;
}

export interface LineageTargetOut {
  table: string;
  state: "written" | "pending" | "applied";
  row_id: number | null;
  employee_id: number | null;
  employee_name: string | null;
  fields: LineageFieldOut[];
}

export interface DocumentLineageOut {
  document_id: number;
  kind: string;
  extraction_status: string;
  extractor: string | null;
  targets: LineageTargetOut[];
  downstream: string[];
}

export interface DocumentCohortOut {
  usable: boolean;
  reason: string;
  window_start: string | null;
  window_end: string | null;
  n_positives: number;
  n_negatives: number;
  base_rate: number;
  n_unmatched_resignations: number;
}
