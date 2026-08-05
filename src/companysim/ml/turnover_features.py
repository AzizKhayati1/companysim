"""Feature engineering for the turnover classifier — the leakage boundary.

Every column here must be something a real HRIS or pulse-survey platform
(Lattice, CultureAmp, Peakon) could actually observe *before* the outcome
window starts. That explicitly excludes the simulation's internal latents
(``engagement``, ``collaboration``, ``productivity``, ``turnover_risk``) —
those mechanistically determine the label (see
:mod:`companysim.ml.turnover_labels`) and including them would reintroduce
the same circularity this whole module exists to remove.

What's allowed instead: job/comp facts, and rolling aggregates of
self-reported pulse-survey data + performance ratings — proxies for the
same underlying state, observed with realistic noise and non-response
(``wellness_snapshots`` already drops ~25% of rows per week).

Real ingested documents (``companysim.ingest``) introduce a *second*
leakage boundary that the column-name check above cannot see. A feature
can be perfectly legitimate by column and still be cheating by date: a
performance review written after the outcome window opened describes the
future, and a resignation letter is written *at* the outcome itself.
:func:`assert_no_temporal_leakage` is the guard for that axis; the
structural half of the defense is that the resignation-letter extraction
schema carries no feature fields at all, so it cannot contribute one.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

CATEGORICAL_FEATURES: tuple[str, ...] = ("level", "department_id", "role")
NUMERIC_FEATURES: tuple[str, ...] = (
    "tenure_months", "base_salary", "team_size", "is_manager", "promotions_count",
    "mood_pulse_mean", "stress_level_pulse_mean", "sleep_quality_pulse_mean",
    "energy_level_pulse_mean", "burnout_exhaustion_pulse_mean",
    "mood_pulse_trend", "stress_level_pulse_trend", "sleep_quality_pulse_trend",
    "energy_level_pulse_trend", "burnout_exhaustion_pulse_trend",
    "rating_last", "rating_prev", "rating_delta",
)
FEATURE_COLUMNS: tuple[str, ...] = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# Internal sim latents that must never appear as training features — they
# are the mechanism that produces the label, not something an HRIS observes.
EXCLUDED_LEAKAGE_COLUMNS: tuple[str, ...] = (
    "engagement", "collaboration", "productivity", "turnover_risk",
)

_PULSE_METRICS: tuple[str, ...] = (
    "mood", "stress_level", "sleep_quality", "energy_level", "burnout_exhaustion",
)


def assert_no_leakage(df: pd.DataFrame) -> None:
    leaked = set(df.columns) & set(EXCLUDED_LEAKAGE_COLUMNS)
    if leaked:
        raise ValueError(
            f"Leakage columns present in training features: {sorted(leaked)}. "
            "These are internal sim latents that mechanistically determine the "
            "label — see companysim.ml.turnover_features module docstring."
        )


def assert_no_temporal_leakage(
    feature_dates: dict[str, date], window_start: date,
) -> None:
    """Every document contributing a *feature* must predate the outcome
    window. ``feature_dates`` maps a human-readable source label (a
    filename, a review period) to the date its facts are true as of;
    ``window_start`` is the day the outcome window opens.

    Strict inequality is deliberate: a review dated exactly on
    ``window_start`` was written at the boundary, and there's no way from
    a date alone to know whether it was recorded before or after the
    outcome began accruing. Rejecting the tie is the conservative reading,
    and matches how :mod:`companysim.ml.turnover_labels` treats a horizon
    as strictly forward-looking from day 0.
    """
    leaked = {
        label: as_of for label, as_of in feature_dates.items() if as_of >= window_start
    }
    if leaked:
        detail = ", ".join(f"{label} (as of {as_of})" for label, as_of in sorted(leaked.items()))
        raise ValueError(
            f"Temporal leakage: {len(leaked)} feature source(s) are dated on or after "
            f"the outcome window start {window_start}: {detail}. Features must describe "
            "state observable strictly before the window opens — see the "
            "companysim.ml.turnover_features module docstring."
        )


def build_feature_frame(tables: dict[str, pd.DataFrame], *, pulse_window: int = 4) -> pd.DataFrame:
    """One row per employee_id, columns = :data:`FEATURE_COLUMNS` (+ id)."""
    emps = tables["employees"]
    wellness = tables["wellness_snapshots"]
    perf = tables["performance_history"]

    team_size = emps.groupby("team_id").size().rename("team_size")
    base = emps[[
        "employee_id", "level", "department_id", "role",
        "tenure_months", "base_salary", "team_id", "promotions_count",
    ]].copy()
    base = base.merge(team_size, left_on="team_id", right_index=True, how="left")
    base["is_manager"] = base["level"].isin(["M1", "M2", "M3", "VP", "CXO"]).astype(int)
    base = base.drop(columns=["team_id"])

    pulse = _pulse_features(wellness, window=pulse_window)
    perf_feat = _performance_features(perf)

    out = (
        base
        .merge(pulse, on="employee_id", how="left")
        .merge(perf_feat, on="employee_id", how="left")
    )

    # Employees with too little tenure to have pulse history / reviews yet —
    # fill with neutral midpoints rather than dropping them.
    mean_cols = [f"{m}_pulse_mean" for m in _PULSE_METRICS]
    trend_cols = [f"{m}_pulse_trend" for m in _PULSE_METRICS]
    out[mean_cols] = out[mean_cols].fillna(0.5)
    out[trend_cols] = out[trend_cols].fillna(0.0)
    out["rating_last"] = out["rating_last"].fillna(3.0)
    out["rating_prev"] = out["rating_prev"].fillna(3.0)
    out["rating_delta"] = out["rating_delta"].fillna(0.0)

    assert_no_leakage(out)
    return out[["employee_id", *FEATURE_COLUMNS]]


def _pulse_features(wellness: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if wellness.empty:
        cols = ["employee_id"] + [f"{m}_pulse_mean" for m in _PULSE_METRICS] \
            + [f"{m}_pulse_trend" for m in _PULSE_METRICS]
        return pd.DataFrame(columns=cols)

    w = wellness.copy()
    w["snapshot_date"] = pd.to_datetime(w["snapshot_date"])
    w = w.sort_values(["employee_id", "snapshot_date"], ascending=[True, False])
    w = w.groupby("employee_id", as_index=False, group_keys=False).head(window)

    means = w.groupby("employee_id")[list(_PULSE_METRICS)].mean()
    means.columns = [f"{c}_pulse_mean" for c in means.columns]

    trends = w.groupby("employee_id").apply(
        lambda g: pd.Series({
            f"{m}_pulse_trend": _slope(g["snapshot_date"], g[m]) for m in _PULSE_METRICS
        }),
        include_groups=False,
    )

    return means.join(trends).reset_index()


def _performance_features(perf: pd.DataFrame) -> pd.DataFrame:
    if perf.empty:
        return pd.DataFrame(columns=["employee_id", "rating_last", "rating_prev", "rating_delta"])

    p = perf.sort_values(["employee_id", "quarter_end"], ascending=[True, False])
    top2 = p.groupby("employee_id", as_index=False, group_keys=False).head(2)

    def extract(g: pd.DataFrame) -> pd.Series:
        ratings = g["rating"].to_numpy()
        last = float(ratings[0])
        prev = float(ratings[1]) if len(ratings) > 1 else last
        return pd.Series({
            "rating_last": last, "rating_prev": prev, "rating_delta": last - prev,
        })

    return top2.groupby("employee_id").apply(extract, include_groups=False).reset_index()


def _slope(dates: pd.Series, values: pd.Series) -> float:
    if len(values) < 2:
        return 0.0
    x = (dates - dates.min()).dt.days.to_numpy(dtype=float)
    y = values.to_numpy(dtype=float)
    if np.all(x == x[0]):
        return 0.0
    return float(np.polyfit(x, y, 1)[0])
