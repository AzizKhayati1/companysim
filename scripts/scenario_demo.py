"""Compare a baseline against a 10% layoff and an RTO mandate.

Prints tick-by-tick medians so you can eyeball whether the sim is
responding sensibly before opening the dashboard.
"""
from __future__ import annotations

from companysim.data.generators import GeneratorConfig
from companysim.mc.runner import MonteCarloRunner
from companysim.scenarios.events import Layoff, PolicyChange
from companysim.scenarios.scenario import BASELINE, Scenario


def run(scenario: Scenario, ticks: int = 20) -> None:
    result = MonteCarloRunner(
        scenario=scenario,
        generator_config=GeneratorConfig(headcount=200, seed=42),
        replicates=25, ticks=ticks, base_seed=1000,
    ).run()
    print(f"\n== {scenario.name} ==")
    b = result.bands
    cols = ["tick", "active_headcount_p50", "mean_engagement_p50",
            "mean_productivity_p50", "mean_turnover_risk_p50"]
    print(b[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    run(BASELINE)
    run(Scenario(name="layoff_10pct",
                 events=[Layoff(at_tick=5, fraction=0.10)]))
    run(Scenario(name="rto_mandate",
                 events=[PolicyChange(at_tick=3, delta=-0.15)]))
