"""Root-cause diagnostics — detect a problem in a run, explain why, and
recommend what to do about it.

Three-stage pipeline, each stage independently testable:

1. :func:`detect_problems` — threshold-crossing detection over a run's
   tick-by-tick history (the same DataFrame ``OrganizationModel.run()``
   already returns).
2. :func:`diagnose` — root-cause attribution. Deliberately *adapter-
   agnostic*: takes any DataFrame with ``employee_id``, ``department_id``,
   ``team_id`` plus whatever numeric driver columns are present, so the
   same function serves both the webapp's DB-backed employee/wellbeing
   records and the offline dataset pipeline's
   :func:`companysim.ml.turnover_features.build_feature_frame` output.
   Method: for each department/team, compute each driver's deviation from
   the org-wide mean, weight by the trained turnover model's feature
   importance (or equal weight if no model is available), rank. This is a
   transparent substitute for SHAP — no new heavy dependency, and every
   claim it makes is a checkable arithmetic fact, not a black-box score.
3. :func:`recommend` — rule-based map from the top driving feature to a
   specific scenario event (see ``scenarios/events.py``), targeted at the
   worst-affected employees within the diagnosed segment.

:func:`explain` turns the structured findings into a plain-English
paragraph — template-based natural language generation, not a call to an
LLM: there's no free-text corpus in this synthetic system to justify one,
and generation over known structured facts is the right-sized tool here.

**Known simplification**: root-cause attribution uses the org's *current*
driver state, not a replay of per-employee state at the exact problem
tick — ``OrganizationModel`` only snapshots aggregate metrics per tick,
not full per-employee history. The framing is "which segments' current
structural conditions explain their elevated risk," the same read a real
people-analytics team gets from a current HRIS/survey snapshot — not a
claim of exact historical causality.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Collection

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from companysim.ml.registry import TurnoverModelBundle

# Which direction is "bad" for each driver feature: +1 = higher is bad,
# -1 = lower is bad. Only features listed here are used for root-cause
# scoring (others may appear in a driver_frame but are ignored).
#
# Covers both the webapp's DB-backed wellbeing dial names (workload_perceived,
# manager_support_score, ...) and the offline pipeline's trailing pulse-survey
# feature names (mood_pulse_mean, ...) from
# companysim.ml.turnover_features.build_feature_frame — same underlying
# constructs, different column names depending on which adapter produced
# the driver_frame.
BAD_DIRECTION: dict[str, int] = {
    "workload_perceived": +1,
    "stress_level": +1,
    "burnout_exhaustion": +1,
    "effort_reward_imbalance": +1,
    "anxiety_symptom_score": +1,
    "depression_symptom_score": +1,
    "manager_support_score": -1,
    "psychological_safety_perceived": -1,
    "financial_security_score": -1,
    "meaning_at_work_score": -1,
    "mood": -1,
    "sleep_quality": -1,
    "life_satisfaction": -1,
    "autonomy_score": -1,
    "peer_support_score": -1,
    "recognition_score": -1,
    "growth_opportunity_score": -1,
    # offline-pipeline pulse-survey column names
    "mood_pulse_mean": -1,
    "sleep_quality_pulse_mean": -1,
    "energy_level_pulse_mean": -1,
    "stress_level_pulse_mean": +1,
    "burnout_exhaustion_pulse_mean": +1,
    "rating_last": -1,
}

# Top driving feature -> (recommended event type, human-readable rationale).
_RECOMMENDATION_MAP: dict[str, tuple[str, str]] = {
    "workload_perceived": (
        "workload_relief",
        "High perceived workload is the leading driver — redistribute work or add headcount.",
    ),
    "burnout_exhaustion": (
        "workload_relief",
        "Elevated burnout — reduce workload before it converts into attrition.",
    ),
    "manager_support_score": (
        "manager_coaching",
        "Manager support is below baseline — coach or support the team's manager.",
    ),
    "psychological_safety_perceived": (
        "manager_coaching",
        "Psychological safety is depressed — often a manager/team dynamics issue.",
    ),
    "financial_security_score": (
        "retention_bonus",
        "Financial security is depressed — a targeted retention bonus directly addresses this.",
    ),
    "effort_reward_imbalance": (
        "retention_bonus",
        "Effort/reward imbalance — a compensation or recognition adjustment is indicated.",
    ),
    "meaning_at_work_score": (
        "policy_change",
        "Sense of meaning has dropped broadly — a role-clarity or communication initiative may help.",
    ),
    "mood": (
        "policy_change",
        "Mood is broadly depressed with no single standout driver — a wellbeing initiative is indicated.",
    ),
}
_DEFAULT_RECOMMENDATION = (
    "policy_change",
    "No single standout driver — a broad engagement/wellbeing check-in is a safe first step.",
)

_SUGGESTED_PARAMS: dict[str, dict[str, float]] = {
    "retention_bonus": {"amount_pct": 0.15},
    "workload_relief": {"delta": 0.20},
    "manager_coaching": {"delta": 0.20},
    "policy_change": {"delta": 0.10},
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "burnout_rate": 0.15,
    "engagement_drop": 0.10,
    "turnover_risk_rise": 0.10,
    "quit_spike_ratio": 2.0,
}


@dataclass
class ProblemFlag:
    tick: int
    metric: str
    description: str
    severity: float


@dataclass
class DriverContribution:
    segment_type: str  # "department" | "team"
    segment_id: str
    feature: str
    segment_mean: float
    org_mean: float
    deviation: float
    importance: float
    score: float


@dataclass
class Diagnosis:
    problem: ProblemFlag
    primary_drivers: list[DriverContribution]


@dataclass
class Recommendation:
    event_type: str
    rationale: str
    target_department: str | None = None
    target_team: str | None = None
    target_employee_ids: list[str] = field(default_factory=list)
    suggested_params: dict[str, Any] = field(default_factory=dict)


def detect_problems(
    history: pd.DataFrame,
    thresholds: dict[str, float] | None = None,
    window: int = 3,
) -> list[ProblemFlag]:
    """Scan a single-run tick-by-tick history for threshold crossings."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    problems: list[ProblemFlag] = []
    history = history.sort_values("tick").reset_index(drop=True)
    if history.empty:
        return problems

    if "burnout_rate" in history.columns:
        crossings = history[history["burnout_rate"] > th["burnout_rate"]]
        if not crossings.empty:
            row = crossings.iloc[0]
            problems.append(ProblemFlag(
                tick=int(row["tick"]), metric="burnout_rate",
                description=(
                    f"Burnout rate exceeded {th['burnout_rate']:.0%} at week {int(row['tick'])} "
                    f"(reached {row['burnout_rate']:.0%})."
                ),
                severity=float(np.clip(row["burnout_rate"] / th["burnout_rate"] - 0.7, 0.0, 1.0)),
            ))

    if "mean_engagement" in history.columns and len(history) > 1:
        eng = history["mean_engagement"]
        recent_peak = eng.rolling(window, min_periods=1).max().shift(1).fillna(eng.iloc[0])
        drop = recent_peak - eng
        worst_idx = drop.idxmax()
        if drop[worst_idx] >= th["engagement_drop"]:
            tick = int(history.loc[worst_idx, "tick"])
            problems.append(ProblemFlag(
                tick=tick, metric="mean_engagement",
                description=(
                    f"Engagement dropped {drop[worst_idx]:.2f} within a {window}-week window, "
                    f"bottoming at week {tick}."
                ),
                severity=float(np.clip(drop[worst_idx] / th["engagement_drop"] * 0.5, 0.0, 1.0)),
            ))

    if "mean_turnover_risk" in history.columns and len(history) > 1:
        risk = history["mean_turnover_risk"]
        recent_low = risk.rolling(window, min_periods=1).min().shift(1).fillna(risk.iloc[0])
        rise = risk - recent_low
        worst_idx = rise.idxmax()
        if rise[worst_idx] >= th["turnover_risk_rise"]:
            tick = int(history.loc[worst_idx, "tick"])
            problems.append(ProblemFlag(
                tick=tick, metric="mean_turnover_risk",
                description=(
                    f"Mean turnover risk rose {rise[worst_idx]:.2f} within a {window}-week window, "
                    f"peaking at week {tick}."
                ),
                severity=float(np.clip(rise[worst_idx] / th["turnover_risk_rise"] * 0.5, 0.0, 1.0)),
            ))

    if "quits_this_tick" in history.columns and len(history) > window:
        quits = history["quits_this_tick"]
        trailing_mean = quits.rolling(window, min_periods=1).mean().shift(1)
        ratio = quits / trailing_mean.replace(0, np.nan)
        spikes = ratio[(ratio >= th["quit_spike_ratio"]) & (quits >= 2)]
        if not spikes.empty:
            idx = spikes.idxmax()
            tick = int(history.loc[idx, "tick"])
            problems.append(ProblemFlag(
                tick=tick, metric="quits_this_tick",
                description=(
                    f"Quits spiked to {int(quits[idx])} at week {tick} "
                    f"({ratio[idx]:.1f}x the trailing average)."
                ),
                severity=float(np.clip(ratio[idx] / th["quit_spike_ratio"] * 0.4, 0.0, 1.0)),
            ))

    return problems


def _aggregate_feature_importances(
    classifier: Any, categorical_columns: Collection[str],
) -> dict[str, float]:
    """Sum a fitted Pipeline's one-hot-expanded feature_importances_ back
    to their parent (pre-encoding) feature names.
    """
    prep = classifier.named_steps.get("prep")
    model = classifier.named_steps.get("model")
    if prep is None or model is None or not hasattr(model, "feature_importances_"):
        return {}
    encoded_names = prep.get_feature_names_out()
    importances = model.feature_importances_
    agg: dict[str, float] = {}
    for name, imp in zip(encoded_names, importances):
        rest = name.split("__", 1)[1] if "__" in name else name
        parent = rest
        for col in categorical_columns:
            if rest == col or rest.startswith(f"{col}_"):
                parent = col
                break
        agg[parent] = agg.get(parent, 0.0) + float(imp)
    return agg


def diagnose(
    problem: ProblemFlag,
    driver_frame: pd.DataFrame,
    *,
    turnover_bundle: "TurnoverModelBundle | None" = None,
    categorical_columns: Collection[str] = (),
    top_n: int = 3,
) -> Diagnosis:
    """Rank (segment, feature) pairs by importance-weighted deviation from
    the org-wide mean. ``driver_frame`` needs only ``department_id``
    and/or ``team_id`` plus numeric columns overlapping :data:`BAD_DIRECTION`.
    """
    numeric_cols = [
        c for c in driver_frame.columns
        if c in BAD_DIRECTION and pd.api.types.is_numeric_dtype(driver_frame[c])
    ]
    if not numeric_cols:
        return Diagnosis(problem=problem, primary_drivers=[])

    importances: dict[str, float] = {}
    if turnover_bundle is not None:
        importances = _aggregate_feature_importances(turnover_bundle.classifier, categorical_columns)
    default_weight = 1.0 / len(numeric_cols)
    for col in numeric_cols:
        importances.setdefault(col, default_weight)

    org_means = driver_frame[numeric_cols].mean()
    contributions: list[DriverContribution] = []

    for segment_type, seg_col in (("department", "department_id"), ("team", "team_id")):
        if seg_col not in driver_frame.columns:
            continue
        for seg_id, group in driver_frame.groupby(seg_col):
            if len(group) < 2:
                continue
            seg_means = group[numeric_cols].mean()
            for col in numeric_cols:
                deviation = float(seg_means[col] - org_means[col])
                badness = deviation * BAD_DIRECTION[col]
                importance = float(importances.get(col, default_weight))
                score = max(0.0, badness) * importance
                if score <= 0:
                    continue
                contributions.append(DriverContribution(
                    segment_type=segment_type, segment_id=str(seg_id), feature=col,
                    segment_mean=float(seg_means[col]), org_mean=float(org_means[col]),
                    deviation=deviation, importance=importance, score=float(score),
                ))

    contributions.sort(key=lambda c: c.score, reverse=True)
    return Diagnosis(problem=problem, primary_drivers=contributions[:top_n])


def recommend(diagnosis: Diagnosis, driver_frame: pd.DataFrame, *, top_k: int = 10) -> Recommendation:
    """Map the top driving feature to a specific scenario event, targeted
    at the worst-affected employees (by that same feature) within the
    diagnosed segment.
    """
    if not diagnosis.primary_drivers:
        event_type, rationale = _DEFAULT_RECOMMENDATION
        return Recommendation(event_type=event_type, rationale=rationale)

    top = diagnosis.primary_drivers[0]
    event_type, rationale = _RECOMMENDATION_MAP.get(top.feature, _DEFAULT_RECOMMENDATION)

    seg_col = "department_id" if top.segment_type == "department" else "team_id"
    target_ids: list[str] = []
    if seg_col in driver_frame.columns and "employee_id" in driver_frame.columns:
        segment_rows = driver_frame[driver_frame[seg_col] == top.segment_id]
        if top.feature in segment_rows.columns:
            # Higher-is-bad -> worst = highest first; lower-is-bad -> worst = lowest first.
            ascending = BAD_DIRECTION.get(top.feature, 1) < 0
            segment_rows = segment_rows.sort_values(top.feature, ascending=ascending)
        target_ids = segment_rows["employee_id"].head(top_k).tolist()

    return Recommendation(
        event_type=event_type,
        rationale=rationale,
        target_department=top.segment_id if top.segment_type == "department" else None,
        target_team=top.segment_id if top.segment_type == "team" else None,
        target_employee_ids=target_ids,
        suggested_params=dict(_SUGGESTED_PARAMS.get(event_type, {})),
    )


def explain(problem: ProblemFlag, diagnosis: Diagnosis, recommendation: Recommendation) -> str:
    """Template-based NLG — a plain-English paragraph over the structured findings."""
    parts = [problem.description]

    if diagnosis.primary_drivers:
        top = diagnosis.primary_drivers[0]
        direction = "above" if top.deviation > 0 else "below"
        parts.append(
            f"Root cause: {top.segment_type} '{top.segment_id}' shows {top.feature} "
            f"{abs(top.deviation):.2f} {direction} the org average "
            f"(importance-weighted score {top.score:.3f})."
        )
        if len(diagnosis.primary_drivers) > 1:
            others = ", ".join(
                f"{d.feature} in {d.segment_id}" for d in diagnosis.primary_drivers[1:]
            )
            parts.append(f"Contributing factors: {others}.")
    else:
        parts.append("No single segment stood out as the primary driver.")

    target = recommendation.target_department or recommendation.target_team
    action = recommendation.event_type.replace("_", " ").title()
    if target:
        parts.append(f"Recommended: {action} for {target}.")
    else:
        parts.append(f"Recommended: {action}.")
    if recommendation.target_employee_ids:
        parts.append(f"Suggested targets: {len(recommendation.target_employee_ids)} employees.")
    parts.append(recommendation.rationale)

    return " ".join(parts)
