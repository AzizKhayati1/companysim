"""Pydantic request/response models for the HTTP API.

Distinct from `companysim.data.schemas` (the simulation engine's internal
contract) — these are the wire-format models the frontend talks to, using
plain integer DB ids rather than the engine's internal string ids.
"""
from __future__ import annotations

from typing import Any

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


class PromotionLogEntryOut(BaseModel):
    timestamp: str
    decision: str
    reason: str
    candidate_eval: dict[str, Any]
    production_eval: dict[str, Any] | None
    n_live_examples: int = 0
    training_seed: int
    training_headcount: int


class FeatureImportanceOut(BaseModel):
    feature: str
    importance: float


class ModelQualityResponse(BaseModel):
    history: list[PromotionLogEntryOut]
    feature_importances: list[FeatureImportanceOut]


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
