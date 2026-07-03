"""What-if workflow — the payoff for the whole reframe.

Ties the turnover classifier, the individual-targeted scenario events, and
the simulation together to answer the actual decision-support question:
*given our at-risk employees, does this intervention predictably reduce
their exits, and by how much relative to what it costs?*

The key methodological point: company-wide cumulative quits is the *wrong*
denominator for evaluating a targeted intervention. If a program touches
120 of 2,000 employees, the other 1,880 employees' quit noise swamps any
signal from the 120 — so :func:`compare_intervention` tracks outcomes
*within the targeted cohort specifically*, which is both the correct
statistic and the one a retention program actually gets judged on.

Baseline and treated runs are paired — same population, same per-replicate
seed — diverging only at the intervention's tick, which is a much
lower-variance comparison than independently sampling two Monte Carlo runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Collection

import numpy as np
import pandas as pd

from companysim.data.schemas import Organization
from companysim.mc.runner import MonteCarloResult, MonteCarloRunner, compute_percentile_bands
from companysim.ml.registry import TurnoverModelBundle
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import RetentionBonus
from companysim.scenarios.scenario import BASELINE, Scenario


def rank_at_risk(
    bundle: TurnoverModelBundle,
    features: pd.DataFrame,
    *,
    top_k: int | None = None,
) -> pd.DataFrame:
    """Score employees and sort by predicted turnover probability, descending."""
    scored = bundle.predict_risk(features)
    scored = scored.sort_values("turnover_probability", ascending=False).reset_index(drop=True)
    return scored.head(top_k) if top_k is not None else scored


def estimate_intervention_cost(scenario: Scenario, org: Organization) -> float:
    """Dollar estimate for the scenario's :class:`RetentionBonus` events.

    Only ``RetentionBonus`` carries an explicit spend; ``WorkloadRelief`` /
    ``ManagerCoaching`` are organizational choices without a direct per-head
    dollar figure in this model, so they contribute 0 here (their cost is
    real but out of scope for this estimate — e.g. hiring backup coverage).
    """
    salary_by_id = {e.id: e.salary for e in org.employees}
    total = 0.0
    for event in scenario.events:
        if isinstance(event, RetentionBonus):
            for eid in event.employee_ids:
                salary = salary_by_id.get(eid)
                if salary is not None:
                    total += event.amount_pct * salary
    return total


@dataclass
class InterventionComparison:
    baseline: MonteCarloResult
    treated: MonteCarloResult
    target_employee_ids: tuple[str, ...]
    baseline_target_quits_p50: float
    treated_target_quits_p50: float
    target_quits_avoided_mean: float
    target_quits_avoided_p50: float
    target_quits_avoided_p05: float
    target_quits_avoided_p95: float
    estimated_cost: float

    def summary(self) -> str:
        n = len(self.target_employee_ids)
        return (
            f"Targeted cohort: {n} employees\n"
            f"Baseline quits within cohort (median): {self.baseline_target_quits_p50:.1f}\n"
            f"Treated quits within cohort (median):  {self.treated_target_quits_p50:.1f}\n"
            f"Quits avoided — mean: {self.target_quits_avoided_mean:.2f}, "
            f"median (p05-p95): {self.target_quits_avoided_p50:.1f} "
            f"({self.target_quits_avoided_p05:.1f} - {self.target_quits_avoided_p95:.1f})\n"
            f"  (small targeted cohorts produce discrete, noisy per-replicate\n"
            f"  counts — mean is the more stable read on the average effect)\n"
            f"Estimated cost: ${self.estimated_cost:,.0f}"
        )


def compare_intervention(
    base_org: Organization,
    human_factors: pd.DataFrame,
    treated_scenario: Scenario,
    *,
    target_employee_ids: Collection[str],
    baseline_scenario: Scenario | None = None,
    replicates: int = 20,
    horizon_ticks: int = 12,
    base_seed: int = 5000,
) -> InterventionComparison:
    """Run baseline vs. treated scenario as paired replicates and measure
    the effect *within the targeted cohort* — see module docstring for why
    company-wide totals are the wrong metric here.

    Both scenarios share ``base_org``/``human_factors`` and, per replicate,
    the same seed — replicate ``r`` starts from an identical population and
    identical stochastic path up to the point the treated scenario's events
    fire, isolating the intervention's effect from population/path noise.
    """
    baseline_scenario = baseline_scenario or BASELINE
    target_ids = set(target_employee_ids)

    baseline_runs: list[pd.DataFrame] = []
    treated_runs: list[pd.DataFrame] = []
    baseline_target_quits: list[int] = []
    treated_target_quits: list[int] = []

    for r in range(replicates):
        seed = base_seed + r

        b_model = OrganizationModel(
            organization=base_org.model_copy(deep=True), seed=seed,
            scenario=baseline_scenario, human_factors=human_factors,
        )
        t_model = OrganizationModel(
            organization=base_org.model_copy(deep=True), seed=seed,
            scenario=treated_scenario, human_factors=human_factors,
        )

        b_hist = b_model.run(horizon_ticks)
        b_hist.insert(0, "replicate", r)
        baseline_runs.append(b_hist)

        t_hist = t_model.run(horizon_ticks)
        t_hist.insert(0, "replicate", r)
        treated_runs.append(t_hist)

        baseline_target_quits.append(
            sum(1 for eid in target_ids if not b_model.employees[eid].active)
        )
        treated_target_quits.append(
            sum(1 for eid in target_ids if not t_model.employees[eid].active)
        )

    baseline_combined = pd.concat(baseline_runs, ignore_index=True)
    treated_combined = pd.concat(treated_runs, ignore_index=True)
    baseline_result = MonteCarloResult(
        scenario_name=baseline_scenario.name, replicates=replicates, ticks=horizon_ticks,
        per_run=baseline_runs,
        bands=compute_percentile_bands(baseline_combined, MonteCarloRunner.METRIC_COLUMNS),
    )
    treated_result = MonteCarloResult(
        scenario_name=treated_scenario.name, replicates=replicates, ticks=horizon_ticks,
        per_run=treated_runs,
        bands=compute_percentile_bands(treated_combined, MonteCarloRunner.METRIC_COLUMNS),
    )

    b_arr = np.array(baseline_target_quits)
    t_arr = np.array(treated_target_quits)
    avoided = b_arr - t_arr

    return InterventionComparison(
        baseline=baseline_result,
        treated=treated_result,
        target_employee_ids=tuple(target_ids),
        baseline_target_quits_p50=float(np.median(b_arr)),
        treated_target_quits_p50=float(np.median(t_arr)),
        target_quits_avoided_mean=float(np.mean(avoided)),
        target_quits_avoided_p50=float(np.median(avoided)),
        target_quits_avoided_p05=float(np.percentile(avoided, 5)),
        target_quits_avoided_p95=float(np.percentile(avoided, 95)),
        estimated_cost=estimate_intervention_cost(treated_scenario, base_org),
    )
