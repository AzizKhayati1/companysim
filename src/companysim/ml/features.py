"""Feature extraction for the behavioral models.

Split into *observable* features (what a real HRIS would expose — level,
tenure, salary, department, team size, etc.) and *target* traits (the
latent scores the sim uses to drive behavior). The models learn the
observable → latent mapping on synthetic data, so at inference time we
can score real (or scenario-projected) employees using only observables.
"""
from __future__ import annotations

import pandas as pd

from companysim.data.schemas import Organization

FEATURE_COLUMNS: tuple[str, ...] = (
    "level",
    "department_id",
    "role",
    "tenure_months",
    "salary",
    "team_size",
    "is_manager",
)

TARGET_COLUMNS: tuple[str, ...] = (
    "productivity",
    "engagement",
    "collaboration",
    "turnover_risk",
)

CATEGORICAL_FEATURES: tuple[str, ...] = ("level", "department_id", "role")
NUMERIC_FEATURES: tuple[str, ...] = ("tenure_months", "salary", "team_size", "is_manager")


def employee_features(org: Organization) -> pd.DataFrame:
    """One row per employee, observable features only.

    ``team_size`` is derived from the org structure — a common HRIS field
    even when it isn't stored directly, and one that meaningfully affects
    engagement in real data.
    """
    team_size = {t.id: len(t.member_ids) for t in org.teams}
    rows = []
    for e in org.employees:
        rows.append({
            "id": e.id,
            "level": e.level,
            "department_id": e.department_id,
            "role": e.role,
            "tenure_months": e.tenure_months,
            "salary": e.salary,
            "team_size": team_size.get(e.team_id, 0),
            "is_manager": int(e.level in ("M1", "M2", "M3", "VP", "CXO")),
        })
    return pd.DataFrame(rows)


def employee_targets(org: Organization) -> pd.DataFrame:
    rows = [
        {
            "id": e.id,
            "productivity": e.productivity,
            "engagement": e.engagement,
            "collaboration": e.collaboration,
            "turnover_risk": e.turnover_risk,
        }
        for e in org.employees
    ]
    return pd.DataFrame(rows)


def build_dataset(org: Organization) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(X, y)`` aligned by employee id, ready for sklearn."""
    X = employee_features(org)
    y = employee_targets(org)
    joined = X.merge(y, on="id")
    return joined[list(FEATURE_COLUMNS)], joined[list(TARGET_COLUMNS)]
