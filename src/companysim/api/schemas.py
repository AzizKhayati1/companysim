"""Pydantic request/response models for the HTTP API.

Distinct from `companysim.data.schemas` (the simulation engine's internal
contract) — these are the wire-format models the frontend talks to, using
plain integer DB ids rather than the engine's internal string ids.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str
    headcount: int = 200
    seed: int = 42


class OrgSummary(BaseModel):
    id: int
    name: str
    seed: int
    headcount: int
    department_count: int
    team_count: int


class DepartmentOut(BaseModel):
    id: int
    name: str
    salary_multiplier: float
    head_employee_id: int | None = None


class DepartmentIn(BaseModel):
    name: str | None = None
    salary_multiplier: float | None = None


class TeamOut(BaseModel):
    id: int
    name: str
    department_id: int
    manager_employee_id: int | None = None
    member_count: int = 0


class TeamIn(BaseModel):
    name: str | None = None
    department_id: int | None = None
    manager_employee_id: int | None = None


class EmployeeOut(BaseModel):
    id: int
    full_name: str
    email: str
    department_id: int
    team_id: int
    manager_id: int | None = None
    level: str
    role: str
    tenure_months: int
    base_salary: float
    work_mode: str
    promotions_count: int
    # Wellbeing dials exposed for editing — see plan for why only these 4.
    workload_perceived: float
    manager_support_score: float
    psychological_safety_perceived: float
    financial_security_score: float


class EmployeeIn(BaseModel):
    full_name: str | None = None
    department_id: int | None = None
    team_id: int | None = None
    manager_id: int | None = None
    level: str | None = None
    role: str | None = None
    tenure_months: int | None = None
    base_salary: float | None = None
    work_mode: str | None = None
    workload_perceived: float | None = None
    manager_support_score: float | None = None
    psychological_safety_perceived: float | None = None
    financial_security_score: float | None = None


class ScenarioEventIn(BaseModel):
    type: str
    at_tick: int
    params: dict[str, Any] = {}


class SimulateRequest(BaseModel):
    ticks: int = 12
    replicates: int = 1
    seed: int = 1234
    events: list[ScenarioEventIn] = []


class SimulateResponse(BaseModel):
    mode: str
    ticks: int
    replicates: int
    columns: list[str]
    rows: list[dict[str, Any]]


class ProblemOut(BaseModel):
    tick: int
    metric: str
    description: str
    severity: float


class DriverOut(BaseModel):
    segment_type: str
    segment_id: str
    feature: str
    segment_mean: float
    org_mean: float
    deviation: float
    score: float


class RecommendationOut(BaseModel):
    event_type: str
    rationale: str
    target_department: int | None = None
    target_team: int | None = None
    target_employee_ids: list[int] = []
    suggested_params: dict[str, Any] = {}


class NotesSummaryOut(BaseModel):
    n_notes: int
    mean_sentiment: float
    top_themes: list[str] = []
    sample_quotes: list[str] = []
    n_llm_generated: int = 0


class DiagnosisReportOut(BaseModel):
    problem: ProblemOut
    drivers: list[DriverOut]
    recommendation: RecommendationOut
    explanation: str
    notes_summary: NotesSummaryOut | None = None


class DiagnoseResponse(BaseModel):
    model_available: bool
    problems_detected: int
    reports: list[DiagnosisReportOut]


class ThemeFrequencyOut(BaseModel):
    theme: str
    count: int


class ExitNoteSentimentPointOut(BaseModel):
    run_id: int
    generated_at: str
    mean_sentiment: float
    n_notes: int


class ExitNoteQuoteOut(BaseModel):
    id: int
    run_id: int
    employee_id: int | None
    text: str
    sentiment: float
    themes: list[str]
    is_llm_generated: bool
    is_backfilled: bool
    generated_at: str


class ExitNotesInsightsResponse(BaseModel):
    n_notes_total: int
    mean_sentiment_overall: float
    n_llm_generated_total: int
    n_backfilled_total: int
    theme_frequency: list[ThemeFrequencyOut]
    sentiment_trend: list[ExitNoteSentimentPointOut]
    recent_quotes: list[ExitNoteQuoteOut]


class AtRiskEmployeeOut(BaseModel):
    employee_id: int
    full_name: str
    department_id: int
    team_id: int
    level: str
    turnover_probability: float
    risk_tier: str


class AtRiskResponse(BaseModel):
    model_available: bool
    employees: list[AtRiskEmployeeOut]


class CompareInterventionRequest(BaseModel):
    intervention_type: str  # "retention_bonus" | "workload_relief" | "manager_coaching"
    top_k: int = 20
    at_tick: int = 1
    params: dict[str, Any] = {}
    horizon_ticks: int = 12
    replicates: int = 15
    seed: int = 5000


class CompareInterventionResponse(BaseModel):
    model_available: bool
    target_employee_count: int
    baseline_target_quits_p50: float
    treated_target_quits_p50: float
    quits_avoided_mean: float
    quits_avoided_p50: float
    quits_avoided_p05: float
    quits_avoided_p95: float
    estimated_cost: float


class ModelStatusResponse(BaseModel):
    model_available: bool
    metadata: dict[str, Any] = {}
    pending_training_examples: int = 0
    pending_document_examples: int = 0


class TrainModelRequest(BaseModel):
    headcount: int = 2000
    replicates: int = 4
    horizon: int = 12
    seed: int = 2024
    tolerance: float = 0.02
    force_promote: bool = False


class TrainModelResponse(BaseModel):
    decision: str
    reason: str
    candidate_eval: dict[str, Any]
    production_eval: dict[str, Any] | None
    train_report: dict[str, Any]
    promoted_at: str | None
    n_live_examples: int = 0
    n_document_examples: int = 0
    extra_example_counts: dict[str, int] = {}


class PromotionLogEntryOut(BaseModel):
    timestamp: str
    decision: str
    reason: str
    candidate_eval: dict[str, Any]
    production_eval: dict[str, Any] | None
    n_live_examples: int = 0
    # Absent from log lines written before document ingestion existed —
    # defaulted rather than required so historical entries still parse.
    extra_example_counts: dict[str, int] = {}
    training_seed: int
    training_headcount: int


class FeatureImportanceOut(BaseModel):
    feature: str
    importance: float


class ModelQualityResponse(BaseModel):
    history: list[PromotionLogEntryOut]
    feature_importances: list[FeatureImportanceOut]


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessageIn] = []


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str] = []
    llm_available: bool


class RunSummaryOut(BaseModel):
    id: int
    run_type: str
    created_at: str
    summary: str


class RunDetailOut(RunSummaryOut):
    request: dict[str, Any]
    response: dict[str, Any]


class RiskHistoryPointOut(BaseModel):
    run_id: int
    computed_at: str
    turnover_probability: float
    risk_tier: str
    model_available: bool


class RiskTrendPointOut(BaseModel):
    run_id: int
    computed_at: str
    mean_risk: float
    employee_count: int
    model_available: bool


class SourceDocumentOut(BaseModel):
    id: int
    kind: str
    filename: str
    content_hash: str
    uploaded_at: str
    as_of_date: str | None
    extraction_status: str
    extractor: str | None
    extraction_error: str | None


class ExtractedFactOut(BaseModel):
    id: int
    document_id: int
    target_table: str
    target_employee_id: int | None
    field_name: str
    proposed_value: str
    current_value: str | None
    confidence: float
    review_status: str
    evidence_span: str
    applied_at: str | None


class DocumentDetailOut(SourceDocumentOut):
    raw_text: str
    pending_facts: list[ExtractedFactOut]


class ExtractDocumentResponse(BaseModel):
    document: SourceDocumentOut
    n_facts_staged: int
    facts: list[ExtractedFactOut]


class ApplyFactsRequest(BaseModel):
    approved_fact_ids: list[int]


class ApplyFactsResponse(BaseModel):
    n_applied: int
    n_rejected: int
    n_employees_created: int = 0
    # Approved facts that could not be applied (an unknown department name,
    # an employee deleted since staging) — surfaced by message so the
    # reviewer sees exactly what didn't land.
    unapplied: list[str] = []


class IngestTotalsOut(BaseModel):
    n_documents: int
    n_pending_facts: int
    n_applied_facts: int
    n_performance_reviews: int
    n_ingested_exit_notes: int


class TokenTotalsOut(BaseModel):
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class FeatureUsageOut(BaseModel):
    feature: str
    requests: int
    total_tokens: int


class LlmRequestOut(BaseModel):
    id: int
    feature: str
    model: str
    org_id: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    created_at: str


class LlmUsageResponse(BaseModel):
    """Token spend across every LLM-backed feature. Windows are UTC;
    ``week`` is a rolling 7×24h window, not a calendar week."""

    all_time: TokenTotalsOut
    today: TokenTotalsOut
    week: TokenTotalsOut
    by_feature: list[FeatureUsageOut] = []
    recent: list[LlmRequestOut] = []


class LlmStatusResponse(BaseModel):
    """What the *running server* thinks its LLM configuration is.

    Exists because the environment a server was started with is otherwise
    unknowable from outside it, and that is exactly the thing that goes
    wrong: editing ``.env`` after launch changes nothing, and a provider
    left at its default silently ignores whatever credentials were set for
    the other one. Reading a file on disk cannot answer either question —
    only the process can.

    Reports no credential values, just whether they resolved.
    """

    provider: str
    model: str
    provider_ready: bool
    # Human-readable and specific; None when everything is configured.
    provider_problem: str | None = None
    features: dict[str, bool] = {}


class LineageFieldOut(BaseModel):
    column: str
    value: str
    # What this column feeds once written — empty when it's a plain stored
    # value with no downstream consumer.
    note: str = ""


class LineageTargetOut(BaseModel):
    """One database row a document wrote (or proposes to write)."""

    table: str
    # "written"  — the row exists now
    # "pending"  — staged, awaiting approval, nothing written yet
    # "applied"  — was staged and has since been approved and written
    state: str
    row_id: int | None = None
    employee_id: int | None = None
    employee_name: str | None = None
    fields: list[LineageFieldOut] = []


class DocumentLineageOut(BaseModel):
    """Where a document's extracted content lands in the schema, and what
    that lands in turn feeds — the provenance chain behind the review UI.
    """

    document_id: int
    kind: str
    extraction_status: str
    extractor: str | None = None
    targets: list[LineageTargetOut] = []
    downstream: list[str] = []


class DocumentCohortOut(BaseModel):
    """Whether this org's documents can produce labeled training examples.
    ``usable=False`` carries the reason in ``reason`` — the denominator
    rule (see ``ingest.cohorts``) surfaced rather than failing silently.
    """

    usable: bool
    reason: str = ""
    window_start: str | None = None
    window_end: str | None = None
    n_positives: int = 0
    n_negatives: int = 0
    base_rate: float = 0.0
    n_unmatched_resignations: int = 0
