"""Root-cause diagnosis endpoint.

Runs a simulation (same request shape as ``/simulate``), scans the
resulting history for problems, and for each one attributes a root cause
and recommends an intervention — see ``ml/diagnostics.py`` for the
methodology and its stated simplifications.

Builds the driver frame directly from the webapp's own
``EmployeeRecord``/``EmployeeWellbeingRecord`` tables — no new
persistence, and it uses plain integer department/team/employee ids
throughout (matching the rest of the API), converting the diagnostics
module's generic string segment ids back to ints at this boundary.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.converters import org_to_pydantic
from companysim.api.database import get_db
from companysim.api.db_models import EmployeeRecord, EmployeeWellbeingRecord
from companysim.api.scenario_builder import build_scenario
from companysim.api.schemas import (
    DiagnoseResponse,
    DiagnosisReportOut,
    DriverOut,
    ProblemOut,
    RecommendationOut,
    SimulateRequest,
)
from companysim.ml.diagnostics import detect_problems, explain, recommend
from companysim.ml.diagnostics import diagnose as run_diagnose
from companysim.ml.registry import TurnoverModelBundle, load_bundle
from companysim.model.organization import OrganizationModel

router = APIRouter(prefix="/orgs/{org_id}", tags=["diagnose"])

PRODUCTION_MODEL_PATH = Path("models/turnover_production.joblib")

_DRIVER_COLUMNS: tuple[str, ...] = (
    "workload_perceived", "manager_support_score", "psychological_safety_perceived",
    "financial_security_score", "burnout_exhaustion", "stress_level", "mood",
    "sleep_quality", "meaning_at_work_score", "life_satisfaction",
)


def _build_driver_frame(db: Session, org_id: int) -> pd.DataFrame:
    rows = (
        db.query(EmployeeRecord, EmployeeWellbeingRecord)
        .join(EmployeeWellbeingRecord, EmployeeWellbeingRecord.employee_id == EmployeeRecord.id)
        .filter(EmployeeRecord.org_id == org_id)
        .all()
    )
    records = []
    for emp, wb in rows:
        record = {"employee_id": emp.id, "department_id": emp.department_id, "team_id": emp.team_id}
        for col in _DRIVER_COLUMNS:
            record[col] = getattr(wb, col)
        records.append(record)
    return pd.DataFrame(records)


def _load_turnover_bundle() -> TurnoverModelBundle | None:
    if not PRODUCTION_MODEL_PATH.exists():
        return None
    try:
        return load_bundle(PRODUCTION_MODEL_PATH, expected_type=TurnoverModelBundle)
    except Exception:
        return None


@router.post("/diagnose", response_model=DiagnoseResponse)
def diagnose_run(org_id: int, req: SimulateRequest, db: Session = Depends(get_db)):
    try:
        org, hf_df = org_to_pydantic(db, org_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    scenario = build_scenario(req.events)
    model = OrganizationModel(organization=org, seed=req.seed, scenario=scenario, human_factors=hf_df)
    history = model.run(req.ticks)

    problems = detect_problems(history)
    driver_frame = _build_driver_frame(db, org_id)
    bundle = _load_turnover_bundle()

    reports: list[DiagnosisReportOut] = []
    for problem in problems:
        diagnosis = run_diagnose(problem, driver_frame, turnover_bundle=bundle)
        rec = recommend(diagnosis, driver_frame)
        text = explain(problem, diagnosis, rec)

        reports.append(DiagnosisReportOut(
            problem=ProblemOut(
                tick=problem.tick, metric=problem.metric,
                description=problem.description, severity=problem.severity,
            ),
            drivers=[
                DriverOut(
                    segment_type=d.segment_type, segment_id=d.segment_id, feature=d.feature,
                    segment_mean=d.segment_mean, org_mean=d.org_mean,
                    deviation=d.deviation, score=d.score,
                )
                for d in diagnosis.primary_drivers
            ],
            recommendation=RecommendationOut(
                event_type=rec.event_type,
                rationale=rec.rationale,
                target_department=int(rec.target_department) if rec.target_department else None,
                target_team=int(rec.target_team) if rec.target_team else None,
                target_employee_ids=[int(eid) for eid in rec.target_employee_ids],
                suggested_params=rec.suggested_params,
            ),
            explanation=text,
        ))

    return DiagnoseResponse(
        model_available=bundle is not None,
        problems_detected=len(problems),
        reports=reports,
    )
