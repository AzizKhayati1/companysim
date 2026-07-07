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
- ``rating_last``/``rating_prev``/``rating_delta`` default to a neutral
  3.0/3.0/0.0 — no performance_history table in this schema.
- ``department_id`` is the one field that's genuinely lossy: the model
  learned the offline pipeline's ``"dept_00".."dept_08"`` categories, not
  the webapp's integer ids, so that one-hot slice contributes nothing
  (``OneHotEncoder(handle_unknown="ignore")``) rather than erroring — a
  real but bounded accuracy cost, not a crash.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from companysim.api.db_models import EmployeeRecord, EmployeeWellbeingRecord


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

    records = []
    for emp, wb in rows:
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
            "rating_last": 3.0,
            "rating_prev": 3.0,
            "rating_delta": 0.0,
        })
    return pd.DataFrame(records)
