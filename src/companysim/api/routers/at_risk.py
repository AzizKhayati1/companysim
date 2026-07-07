"""At-risk employee ranking + intervention comparison.

Scores current employees with the trained turnover model
(``models/turnover_production.joblib``), reusing it exactly as trained —
no retraining, no schema changes. Feature adaptation from the webapp's DB
shape to the model's trained feature shape lives in
``api.scoring_frame.build_scoring_frame`` (shared with
``ml.training_examples``, which uses the same adapter to collect labeled
examples from real runs) — see that module for the documented, honest
approximations it makes.

If no trained model exists yet, ranking falls back to the org's raw
``turnover_risk`` field (the simulation's own internal latent) — clearly
weaker and clearly labelled (``model_available: false``) rather than
silently pretending to be a real prediction.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.converters import emp_str_id, org_to_pydantic, team_str_id
from companysim.api.database import get_db
from companysim.api.db_models import EmployeeRecord
from companysim.api.scoring_frame import build_scoring_frame
from companysim.api.schemas import (
    AtRiskEmployeeOut,
    AtRiskResponse,
    CompareInterventionRequest,
    CompareInterventionResponse,
)
from companysim.intervene import compare_intervention as run_compare_intervention
from companysim.ml.registry import TurnoverModelBundle, load_bundle
from companysim.ml.turnover_features import FEATURE_COLUMNS
from companysim.scenarios.events import ManagerCoaching, RetentionBonus, WorkloadRelief
from companysim.scenarios.scenario import Scenario

router = APIRouter(prefix="/orgs/{org_id}/at-risk", tags=["at-risk"])

PRODUCTION_MODEL_PATH = Path("models/turnover_production.joblib")


def _load_turnover_bundle() -> TurnoverModelBundle | None:
    if not PRODUCTION_MODEL_PATH.exists():
        return None
    try:
        return load_bundle(PRODUCTION_MODEL_PATH, expected_type=TurnoverModelBundle)
    except Exception:
        return None


def _rank_employee_ids(db: Session, org_id: int, frame: pd.DataFrame) -> tuple[list[int], bool]:
    """Return (employee ids ranked worst-first, whether a real model was used)."""
    bundle = _load_turnover_bundle()
    if bundle is not None and not frame.empty:
        scored = bundle.predict_risk(frame[["employee_id", *FEATURE_COLUMNS]])
        ranked = scored.sort_values("turnover_probability", ascending=False)
        return ranked["employee_id"].astype(int).tolist(), True

    raw = db.query(EmployeeRecord).filter(EmployeeRecord.org_id == org_id).all()
    ranked_raw = sorted(raw, key=lambda e: e.turnover_risk, reverse=True)
    return [e.id for e in ranked_raw], False


@router.get("", response_model=AtRiskResponse)
def get_at_risk(org_id: int, top_k: int = 50, db: Session = Depends(get_db)):
    frame = build_scoring_frame(db, org_id)
    if frame.empty:
        raise HTTPException(404, "org not found or has no employees")

    bundle = _load_turnover_bundle()
    if bundle is not None:
        scored = bundle.predict_risk(frame[["employee_id", *FEATURE_COLUMNS]])
        ranked = scored.merge(
            frame[["employee_id", "full_name", "department_id", "team_id", "level"]],
            on="employee_id",
        )
        ranked = ranked.sort_values("turnover_probability", ascending=False)
    else:
        raw = db.query(EmployeeRecord).filter(EmployeeRecord.org_id == org_id).all()
        risk_by_id = {e.id: e.turnover_risk for e in raw}
        ranked = frame.copy()
        ranked["turnover_probability"] = ranked["employee_id"].map(risk_by_id)
        ranked["risk_tier"] = pd.cut(
            ranked["turnover_probability"], bins=[-1, 0.25, 0.5, 2], labels=["low", "medium", "high"],
        ).astype(str)
        ranked = ranked.sort_values("turnover_probability", ascending=False)

    ranked = ranked.head(top_k)
    employees_out = [
        AtRiskEmployeeOut(
            employee_id=int(row["employee_id"]), full_name=row["full_name"],
            department_id=int(row["department_id"]), team_id=int(row["team_id"]),
            level=row["level"], turnover_probability=float(row["turnover_probability"]),
            risk_tier=str(row["risk_tier"]),
        )
        for _, row in ranked.iterrows()
    ]
    return AtRiskResponse(model_available=bundle is not None, employees=employees_out)


@router.post("/compare-intervention", response_model=CompareInterventionResponse)
def compare_intervention_endpoint(
    org_id: int, req: CompareInterventionRequest, db: Session = Depends(get_db),
):
    try:
        org, hf_df = org_to_pydantic(db, org_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    frame = build_scoring_frame(db, org_id)
    ranked_ids, model_used = _rank_employee_ids(db, org_id, frame)
    top_ids = ranked_ids[: req.top_k]
    if not top_ids:
        raise HTTPException(400, "no employees to target")
    target_str_ids = tuple(emp_str_id(i) for i in top_ids)

    if req.intervention_type == "retention_bonus":
        scenario = Scenario(name="at_risk_bonus", events=[
            RetentionBonus(at_tick=req.at_tick, employee_ids=target_str_ids,
                            amount_pct=req.params.get("amount_pct", 0.15)),
        ])
    elif req.intervention_type == "workload_relief":
        scenario = Scenario(name="at_risk_workload", events=[
            WorkloadRelief(at_tick=req.at_tick, employee_ids=target_str_ids,
                            delta=req.params.get("delta", 0.20)),
        ])
    elif req.intervention_type == "manager_coaching":
        team_ids = {
            e.team_id for e in db.query(EmployeeRecord)
            .filter(EmployeeRecord.org_id == org_id, EmployeeRecord.id.in_(top_ids)).all()
        }
        scenario = Scenario(name="at_risk_coaching", events=[
            ManagerCoaching(at_tick=req.at_tick, team_id=team_str_id(tid),
                            delta=req.params.get("delta", 0.20))
            for tid in team_ids
        ])
    else:
        raise HTTPException(400, f"unknown intervention type '{req.intervention_type}'")

    result = run_compare_intervention(
        org, hf_df, scenario,
        target_employee_ids=target_str_ids,
        replicates=req.replicates, horizon_ticks=req.horizon_ticks, base_seed=req.seed,
    )

    return CompareInterventionResponse(
        model_available=model_used,
        target_employee_count=len(top_ids),
        baseline_target_quits_p50=result.baseline_target_quits_p50,
        treated_target_quits_p50=result.treated_target_quits_p50,
        quits_avoided_mean=result.target_quits_avoided_mean,
        quits_avoided_p50=result.target_quits_avoided_p50,
        quits_avoided_p05=result.target_quits_avoided_p05,
        quits_avoided_p95=result.target_quits_avoided_p95,
        estimated_cost=result.estimated_cost,
    )
