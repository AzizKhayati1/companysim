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


class DiagnosisReportOut(BaseModel):
    problem: ProblemOut
    drivers: list[DriverOut]
    recommendation: RecommendationOut
    explanation: str


class DiagnoseResponse(BaseModel):
    model_available: bool
    problems_detected: int
    reports: list[DiagnosisReportOut]
