"""Monte Carlo runner — sweeps stochastic uncertainty across a scenario.

For each of ``replicates`` runs we:

1. Regenerate the org from the *same* generator seed — the starting
   population is held fixed so results reflect scenario noise, not
   population noise.
2. Give the :class:`OrganizationModel` a distinct seed, so per-agent RNG
   streams differ across replicates.
3. Run the scenario for ``ticks`` steps and collect the history.

Aggregate output is a per-tick DataFrame with p05 / p50 / p95 bands for
every metric — that's what the dashboard will plot as a fan chart, and
what a policymaker actually needs to read a "layoff N%" scenario: not the
mean outcome but the range of plausible outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.data.schemas import Organization
from companysim.model.organization import OrganizationModel
from companysim.scenarios.scenario import BASELINE, Scenario


@dataclass
class MonteCarloResult:
    scenario_name: str
    replicates: int
    ticks: int
    per_run: list[pd.DataFrame] = field(default_factory=list)
    bands: pd.DataFrame = field(default_factory=pd.DataFrame)

    def band_for(self, metric: str) -> pd.DataFrame:
        cols = ["tick", f"{metric}_p05", f"{metric}_p50", f"{metric}_p95"]
        missing = [c for c in cols if c not in self.bands.columns]
        if missing:
            raise KeyError(f"Unknown metric bands: {missing}")
        return self.bands[cols]


class MonteCarloRunner:
    """Run a scenario N times and aggregate into percentile bands."""

    METRIC_COLUMNS: tuple[str, ...] = (
        "active_headcount",
        "quits_this_tick",
        "hires_this_tick",
        "mean_productivity",
        "mean_engagement",
        "mean_collaboration",
        "mean_turnover_risk",
        "mean_burnout",
        "mean_stress",
        "mean_sleep_quality",
        "mean_mood",
        "mean_psychological_safety",
        "burnout_rate",
    )

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        generator_config: GeneratorConfig | None = None,
        replicates: int = 50,
        ticks: int = 30,
        base_seed: int = 2024,
        base_org: Organization | None = None,
        human_factors: pd.DataFrame | None = None,
    ) -> None:
        """``base_org`` (+ optional ``human_factors``) lets callers supply a
        pre-built population — e.g. the rich :class:`DatasetBuilder` org
        paired with its human-factors snapshot — instead of generating a
        minimal one from ``generator_config``. Used by
        :mod:`companysim.intervene` to run before/after intervention
        comparisons on the same starting population the turnover model
        was trained on.
        """
        self.scenario = scenario or BASELINE
        self.generator_config = generator_config or GeneratorConfig()
        self.replicates = replicates
        self.ticks = ticks
        self.base_seed = base_seed
        self.base_org = base_org
        self.human_factors = human_factors

    def run(self) -> MonteCarloResult:
        runs: list[pd.DataFrame] = []
        if self.base_org is not None:
            base_org = self.base_org
        else:
            base_org = WorkforceGenerator(self.generator_config).generate()

        for r in range(self.replicates):
            # Deep-copy the org each replicate — cheap for a few thousand
            # employees, and keeps replicates independent since agents
            # mutate the underlying pydantic records (level, engagement, ...).
            org = base_org.model_copy(deep=True)
            model = OrganizationModel(
                organization=org,
                seed=self.base_seed + r,
                scenario=self.scenario,
                human_factors=self.human_factors,
            )
            hist = model.run(self.ticks)
            hist.insert(0, "replicate", r)
            runs.append(hist)

        combined = pd.concat(runs, ignore_index=True)
        bands = self._bands(combined)
        return MonteCarloResult(
            scenario_name=self.scenario.name,
            replicates=self.replicates,
            ticks=self.ticks,
            per_run=runs,
            bands=bands,
        )

    def _bands(self, combined: pd.DataFrame) -> pd.DataFrame:
        return compute_percentile_bands(combined, self.METRIC_COLUMNS)


def compute_percentile_bands(combined: pd.DataFrame, metric_columns: tuple[str, ...]) -> pd.DataFrame:
    """p05/p50/p95 per tick across replicates, for any (tick, replicate,
    metric...) long DataFrame. Standalone so callers that build their own
    replicate loop (e.g. :mod:`companysim.intervene`) can reuse the exact
    aggregation :class:`MonteCarloRunner` uses.
    """
    grouped = combined.groupby("tick")
    out = pd.DataFrame({"tick": sorted(combined["tick"].unique())})
    for col in metric_columns:
        if col not in combined.columns:
            continue
        q = grouped[col].quantile([0.05, 0.5, 0.95]).unstack()
        q.columns = [f"{col}_p05", f"{col}_p50", f"{col}_p95"]
        out = out.merge(q.reset_index(), on="tick")
    return out
