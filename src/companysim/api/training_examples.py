"""Collect labeled turnover-model training examples from real webapp runs.

Every ``/simulate`` or ``/diagnose`` call already runs a genuine forward
simulation over a real (user-edited) org and already knows, per employee,
whether they organically quit. :func:`collect_training_examples` turns that
into rows in ``turnover_training_examples`` (see ``db_models.py``);
:func:`load_collected_examples` reconstructs them into a
``ml.turnover_features.FEATURE_COLUMNS``-shaped frame that
``ml.gate.run_training_gate`` can blend into its training cohort. Lives in
``api/`` rather than ``ml/`` because it's DB-coupled webapp glue, not
reusable data-science logic — ``ml.gate`` itself stays DB-agnostic and only
ever sees an already-built DataFrame.

Labels are organic-only — see
:attr:`companysim.model.organization.OrganizationModel.organic_quit_ids` —
so an employee removed by an injected ``Layoff``/``Termination`` event is
never recorded as a "quit" example; that would teach the model that being
laid off looks like voluntary attrition.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from companysim.api.db_models import TurnoverTrainingExample
from companysim.api.scoring_frame import build_scoring_frame
from companysim.ml.turnover_features import FEATURE_COLUMNS
from companysim.model.organization import OrganizationModel

# Shorter runs don't give the organic quit Bernoulli enough ticks to produce
# a meaningful negative — a 2-tick "didn't quit" is much weaker evidence
# than a 12-tick one, so we simply don't collect from very short runs.
MIN_TRAINING_HORIZON_TICKS = 6

_STORED_COLUMNS: tuple[str, ...] = (
    "level", "department_id", "role", "tenure_months", "base_salary",
    "team_size", "is_manager", "promotions_count",
    "mood_pulse_mean", "stress_level_pulse_mean", "sleep_quality_pulse_mean",
    "energy_level_pulse_mean", "burnout_exhaustion_pulse_mean",
)


def collect_training_examples(
    db: Session, org_id: int, run_id: int, ticks: int, model: OrganizationModel,
) -> None:
    if ticks < MIN_TRAINING_HORIZON_TICKS:
        return
    frame = build_scoring_frame(db, org_id)
    if frame.empty:
        return

    organic_quit_ids = {
        int(s.split("_", 1)[1]) for s in model.organic_quit_ids if s.startswith("emp_")
    }
    examples = [
        TurnoverTrainingExample(
            org_id=org_id, run_id=run_id, employee_id=int(row.employee_id), horizon_ticks=ticks,
            quit_within_horizon=int(row.employee_id) in organic_quit_ids,
            level=row.level, department_id=row.department_id, role=row.role,
            tenure_months=int(row.tenure_months), base_salary=float(row.base_salary),
            team_size=int(row.team_size), is_manager=int(row.is_manager),
            promotions_count=int(row.promotions_count),
            mood_pulse_mean=float(row.mood_pulse_mean),
            stress_level_pulse_mean=float(row.stress_level_pulse_mean),
            sleep_quality_pulse_mean=float(row.sleep_quality_pulse_mean),
            energy_level_pulse_mean=float(row.energy_level_pulse_mean),
            burnout_exhaustion_pulse_mean=float(row.burnout_exhaustion_pulse_mean),
        )
        for row in frame.itertuples()
    ]
    db.add_all(examples)
    db.commit()


def load_collected_examples(db: Session) -> pd.DataFrame:
    """All collected examples, reshaped to ``FEATURE_COLUMNS`` + label —
    ready to concatenate onto ``ml.gate.run_training_gate``'s synthetic
    cohort. The constant placeholder columns (``*_pulse_trend``,
    ``rating_*``) aren't stored per-row; they're filled in here instead,
    matching ``api.scoring_frame.build_scoring_frame`` exactly.
    """
    rows = db.query(TurnoverTrainingExample).all()
    if not rows:
        return pd.DataFrame(columns=[*FEATURE_COLUMNS, "quit_within_horizon"])

    frame = pd.DataFrame([
        {**{col: getattr(r, col) for col in _STORED_COLUMNS}, "quit_within_horizon": r.quit_within_horizon}
        for r in rows
    ])
    for col in ("mood_pulse_trend", "stress_level_pulse_trend", "sleep_quality_pulse_trend",
                "energy_level_pulse_trend", "burnout_exhaustion_pulse_trend"):
        frame[col] = 0.0
    frame["rating_last"] = 3.0
    frame["rating_prev"] = 3.0
    frame["rating_delta"] = 0.0
    return frame[[*FEATURE_COLUMNS, "quit_within_horizon"]]
