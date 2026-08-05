"""Build a ``ml.turnover_features.FEATURE_COLUMNS``-shaped frame from the
webapp's DB-persisted org state.

Shared by ``routers/at_risk.py`` (live scoring against the production
model) and ``ml/training_examples.py`` (collecting labeled examples from
real simulate/diagnose runs) — one adapter, one set of documented
approximations, reused everywhere a webapp org needs to look like the
offline pipeline's feature frame.

The model was trained on ``ml.turnover_features.FEATURE_COLUMNS``, which the
webapp's DB doesn't persist 1:1 (no pulse-trend history, no performance-
review history), so this fills in the best honest approximation for each:

- job/comp fields (level, role, tenure, salary, team size, is_manager,
  promotions) come straight from ``EmployeeRecord`` — exact match.
- ``*_pulse_mean`` fields use the employee's *current* wellbeing snapshot
  as a stand-in for a trailing average — there's no week-by-week pulse
  history in this schema to average over yet.
- ``*_pulse_trend`` fields default to 0.0 — no history to compute a trend
  from.
- ``rating_last``/``rating_prev``/``rating_delta`` are **real** for any
  employee with ingested performance reviews (``PerformanceReviewRecord``,
  written by ``routers/ingest.py``) — the two most recent reviews by
  ``review_period_end``, exactly the last/prev/delta shape
  ``ml.turnover_features._performance_features`` computes offline. An
  employee with no reviews still falls back to a neutral 3.0/3.0/0.0, and
  an org that has ingested nothing behaves exactly as it did before, so
  ingestion is purely additive. This is the one placeholder document
  ingestion has actually closed; the two above remain approximations.
- ``department_id`` is the one field that's genuinely lossy: the model
  learned the offline pipeline's ``"dept_00".."dept_08"`` categories, not
  the webapp's integer ids, so that one-hot slice contributes nothing
  (``OneHotEncoder(handle_unknown="ignore")``) rather than erroring — a
  real but bounded accuracy cost, not a crash.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from companysim.api.db_models import (
    EmployeeRecord,
    EmployeeRiskSnapshot,
    EmployeeWellbeingRecord,
    PerformanceReviewRecord,
)
from companysim.ml.registry import TurnoverModelBundle, load_bundle
from companysim.ml.turnover_features import FEATURE_COLUMNS

PRODUCTION_MODEL_PATH = Path("models/turnover_production.joblib")

# Neutral fallback for an employee with no ingested reviews — the same
# values build_scoring_frame hardcoded for every employee before
# PerformanceReviewRecord existed, and the same neutral midpoint
# ml.turnover_features.build_feature_frame fills for an offline employee
# too new to have been reviewed.
NEUTRAL_RATING = 3.0

# Wellbeing columns pulled per-employee for root-cause diagnosis (segment- or
# individual-level) — a different, richer slice than build_scoring_frame's
# model-feature columns above, since diagnosis reasons over raw psychological
# constructs rather than the model's engineered pulse/rating features.
DRIVER_COLUMNS: tuple[str, ...] = (
    "workload_perceived", "manager_support_score", "psychological_safety_perceived",
    "financial_security_score", "burnout_exhaustion", "stress_level", "mood",
    "sleep_quality", "meaning_at_work_score", "life_satisfaction",
)


def build_driver_frame(db: Session, org_id: int) -> pd.DataFrame:
    rows = (
        db.query(EmployeeRecord, EmployeeWellbeingRecord)
        .join(EmployeeWellbeingRecord, EmployeeWellbeingRecord.employee_id == EmployeeRecord.id)
        .filter(EmployeeRecord.org_id == org_id)
        .all()
    )
    records = []
    for emp, wb in rows:
        record = {"employee_id": emp.id, "department_id": emp.department_id, "team_id": emp.team_id}
        for col in DRIVER_COLUMNS:
            record[col] = getattr(wb, col)
        records.append(record)
    return pd.DataFrame(records)


def rating_features(db: Session, org_id: int) -> dict[int, tuple[float, float, float]]:
    """employee_id -> (rating_last, rating_prev, rating_delta) from ingested
    reviews. Only employees with at least one review appear; callers fill
    :data:`NEUTRAL_RATING` for the rest.

    With a single review, prev == last (delta 0.0) rather than a neutral
    3.0 — mirroring ``ml.turnover_features._performance_features``, which
    makes the same choice offline so "one review" means the same thing in
    both pipelines. Ordered by ``review_period_end`` (what the rating
    describes), never by upload time.
    """
    rows = (
        db.query(PerformanceReviewRecord)
        .filter(PerformanceReviewRecord.org_id == org_id)
        .order_by(
            PerformanceReviewRecord.employee_id,
            PerformanceReviewRecord.review_period_end.desc(),
        )
        .all()
    )
    by_employee: dict[int, list[float]] = {}
    for row in rows:
        ratings = by_employee.setdefault(row.employee_id, [])
        if len(ratings) < 2:
            ratings.append(float(row.rating))

    out: dict[int, tuple[float, float, float]] = {}
    for employee_id, ratings in by_employee.items():
        last = ratings[0]
        prev = ratings[1] if len(ratings) > 1 else last
        out[employee_id] = (last, prev, last - prev)
    return out


def build_scoring_frame(db: Session, org_id: int) -> pd.DataFrame:
    rows = (
        db.query(EmployeeRecord, EmployeeWellbeingRecord)
        .join(EmployeeWellbeingRecord, EmployeeWellbeingRecord.employee_id == EmployeeRecord.id)
        .filter(EmployeeRecord.org_id == org_id)
        .all()
    )
    team_sizes: dict[int, int] = {}
    for emp, _ in rows:
        team_sizes[emp.team_id] = team_sizes.get(emp.team_id, 0) + 1
    ratings = rating_features(db, org_id)

    records = []
    for emp, wb in rows:
        rating_last, rating_prev, rating_delta = ratings.get(
            emp.id, (NEUTRAL_RATING, NEUTRAL_RATING, 0.0),
        )
        records.append({
            "employee_id": emp.id,
            "department_id": str(emp.department_id),
            "team_id": emp.team_id,
            "full_name": emp.full_name,
            "level": emp.level,
            "role": emp.role,
            "tenure_months": emp.tenure_months,
            "base_salary": emp.base_salary,
            "team_size": team_sizes[emp.team_id],
            "is_manager": int(emp.level in ("M1", "M2", "M3", "VP", "CXO")),
            "promotions_count": emp.promotions_count,
            "mood_pulse_mean": wb.mood,
            "stress_level_pulse_mean": wb.stress_level,
            "sleep_quality_pulse_mean": wb.sleep_quality,
            "energy_level_pulse_mean": wb.energy_level,
            "burnout_exhaustion_pulse_mean": wb.burnout_exhaustion,
            "mood_pulse_trend": 0.0,
            "stress_level_pulse_trend": 0.0,
            "sleep_quality_pulse_trend": 0.0,
            "energy_level_pulse_trend": 0.0,
            "burnout_exhaustion_pulse_trend": 0.0,
            "rating_last": rating_last,
            "rating_prev": rating_prev,
            "rating_delta": rating_delta,
        })
    return pd.DataFrame(records)


def load_production_bundle() -> TurnoverModelBundle | None:
    """Load the trained production model, or ``None`` if it doesn't exist
    or fails to load — callers fall back to the simulation's own raw
    ``turnover_risk`` latent rather than treating this as fatal.
    """
    if not PRODUCTION_MODEL_PATH.exists():
        return None
    try:
        return load_bundle(PRODUCTION_MODEL_PATH, expected_type=TurnoverModelBundle)
    except Exception:
        return None


def score_current_employees(db: Session, org_id: int) -> tuple[pd.DataFrame, bool]:
    """Score every current employee of ``org_id`` with the production model.

    Returns ``(frame, model_used)`` where ``frame`` has at least
    ``employee_id``/``turnover_probability``/``risk_tier`` columns (plus
    whatever :func:`build_scoring_frame` already produces, so callers can
    merge in display fields for free). Falls back to the org's raw
    ``EmployeeRecord.turnover_risk`` latent, tiered the same way the model
    would be, when no production model is available.
    """
    frame = build_scoring_frame(db, org_id)
    if frame.empty:
        return frame.assign(turnover_probability=pd.Series(dtype=float), risk_tier=pd.Series(dtype=str)), False

    bundle = load_production_bundle()
    if bundle is not None:
        scored = bundle.predict_risk(frame[["employee_id", *FEATURE_COLUMNS]])
        merged = frame.merge(
            scored[["employee_id", "turnover_probability", "risk_tier"]], on="employee_id",
        )
        return merged, True

    raw = db.query(EmployeeRecord).filter(EmployeeRecord.org_id == org_id).all()
    risk_by_id = {e.id: e.turnover_risk for e in raw}
    out = frame.copy()
    out["turnover_probability"] = out["employee_id"].map(risk_by_id)
    out["risk_tier"] = pd.cut(
        out["turnover_probability"], bins=[-1, 0.25, 0.5, 2], labels=["low", "medium", "high"],
    ).astype(str)
    return out, False


def risk_trend_rows(db: Session, org_id: int) -> list[dict[str, Any]]:
    """Org-wide mean risk per run, oldest first — a group-by-run rollup of
    the ``EmployeeRiskSnapshot`` rows collected from every Simulate/Diagnose
    run (see ``api/risk_snapshots.py``). Shared by the Dashboard's trend
    chart (``routers/at_risk.py::get_risk_trend``) and the org chatbot's
    trend tool (``api/org_chat.py``) — one query, two consumers.
    """
    rows = (
        db.query(
            EmployeeRiskSnapshot.run_id,
            func.min(EmployeeRiskSnapshot.computed_at).label("computed_at"),
            func.avg(EmployeeRiskSnapshot.turnover_probability).label("mean_risk"),
            func.count(EmployeeRiskSnapshot.id).label("employee_count"),
            func.max(EmployeeRiskSnapshot.model_available).label("model_available"),
        )
        .filter(EmployeeRiskSnapshot.org_id == org_id)
        .group_by(EmployeeRiskSnapshot.run_id)
        .order_by(func.min(EmployeeRiskSnapshot.computed_at))
        .all()
    )
    return [
        {
            "run_id": r.run_id,
            "computed_at": r.computed_at.isoformat(),
            "mean_risk": float(r.mean_risk),
            "employee_count": int(r.employee_count),
            "model_available": bool(r.model_available),
        }
        for r in rows
    ]
