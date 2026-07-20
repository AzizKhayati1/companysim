"""Turnover label generation — real simulated exit events, not hand-set latents.

The previous ML approach trained a regressor to predict ``turnover_risk``
(a continuous latent) from features that *deterministically generated* that
latent in the first place — a formula-inversion exercise dressed up as
prediction. This module replaces that with a genuine predictive task: run
the agent-based simulation forward from a realistic day-0 snapshot and
record whether each employee *actually quit* (the stochastic Bernoulli
event in :meth:`EmployeeAgent.step`) within a horizon.

This is learnable-but-imperfect by construction:

- The per-tick quit draw is irreducible noise — even a high-risk employee
  usually doesn't quit in any single week.
- Team climate depends on the emergent, noisy behavior of *other* agents,
  not a static feature of the employee being predicted.
- ``horizon_ticks`` of compounding burnout/stress/engagement drift adds
  further noise no day-0 snapshot can fully resolve.

Multiple replicates per starting population give the *same* day-0 features
several independent stochastic label draws, which is what keeps a model
trained on this data from learning a deterministic feature→label mapping.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from companysim.data.datasets import DatasetBuilder, DatasetConfig, to_organization
from companysim.model.organization import OrganizationModel
from companysim.scenarios.scenario import BASELINE, Scenario


@dataclass
class LabeledCohort:
    """Everything downstream feature engineering + training need.

    ``tables`` is the standard :class:`DatasetBuilder` output (employees,
    human_factors, wellness_snapshots, performance_history, teams,
    departments) describing the day-0 population — replicate-invariant.
    ``labels`` has one row per (employee_id, replicate): whether that
    employee quit within the horizon in that particular stochastic replay.
    """

    tables: dict[str, pd.DataFrame]
    labels: pd.DataFrame
    horizon_ticks: int
    replicates: int


def build_turnover_cohort(
    config: DatasetConfig,
    *,
    horizon_ticks: int = 12,
    replicates: int = 5,
    scenario: Scenario | None = None,
    sim_base_seed: int = 9000,
) -> LabeledCohort:
    """Generate a day-0 population once, then forward-simulate it
    ``replicates`` times to collect real exit-event labels.

    The population (and its ``human_factors`` day-0 snapshot) is generated
    once from ``config`` — every replicate starts from the *same* people.
    Only the stochastic forward path differs per replicate, via
    ``sim_base_seed + replicate_index`` (mirrors the seeding convention in
    :class:`~companysim.mc.runner.MonteCarloRunner`).
    """
    scenario = scenario or BASELINE
    builder = DatasetBuilder(config)
    tables = builder.build()
    base_org = to_organization(tables, org_name=config.org_name)

    label_rows: list[dict] = []
    for r in range(replicates):
        org = base_org.model_copy(deep=True)
        model = OrganizationModel(
            organization=org,
            seed=sim_base_seed + r,
            scenario=scenario,
            human_factors=tables["human_factors"],
        )
        employee_ids = list(model.employees.keys())
        exit_tick: dict[str, int] = {}

        for t in range(horizon_ticks):
            model.step()
            for eid in employee_ids:
                if eid not in exit_tick and not model.employees[eid].active:
                    exit_tick[eid] = t

        for eid in employee_ids:
            label_rows.append({
                "employee_id": eid,
                "replicate": r,
                "quit_within_horizon": eid in exit_tick,
                "tick_of_exit": exit_tick.get(eid, np.nan),
            })

    labels = pd.DataFrame(label_rows)
    return LabeledCohort(
        tables=tables, labels=labels,
        horizon_ticks=horizon_ticks, replicates=replicates,
    )
