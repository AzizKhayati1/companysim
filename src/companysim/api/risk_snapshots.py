"""Snapshot each employee's current turnover-risk score at the moment a
Simulate/Diagnose run happens, so a per-employee risk trend can be charted
across runs later.

Deliberately simpler than ``api.training_examples.collect_training_examples``:
this only reflects *current* org state via
``scoring_frame.score_current_employees`` (not the run's own simulated
outcome), so it applies to every run — no minimum-horizon gate, no
Monte-Carlo exclusion.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from companysim.api.db_models import EmployeeRiskSnapshot
from companysim.api.scoring_frame import score_current_employees


def record_risk_snapshots(db: Session, org_id: int, run_id: int) -> None:
    frame, model_used = score_current_employees(db, org_id)
    if frame.empty:
        return
    db.add_all(
        EmployeeRiskSnapshot(
            org_id=org_id,
            run_id=run_id,
            employee_id=int(row.employee_id),
            turnover_probability=float(row.turnover_probability),
            risk_tier=str(row.risk_tier),
            model_available=model_used,
        )
        for row in frame.itertuples()
    )
    db.commit()
