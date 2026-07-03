"""Streamlit dashboard — retention risk & intervention simulator.

Run with:

    streamlit run src/companysim/dashboard/app.py

Two tabs:

- **At-Risk Employees** (headline): ranked turnover risk from the trained
  classifier, plus a what-if workflow — pick an intervention, target the
  riskiest employees, see the predicted retention effect and its cost.
- **Org Health** (secondary): the original scenario/fan-chart view over
  company-wide productivity/engagement/turnover metrics.

Kept intentionally thin. Everything interesting lives in the underlying
modules; this file is just the surface.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from companysim.data.datasets import DatasetBuilder, DatasetConfig, to_organization
from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.intervene import compare_intervention, rank_at_risk
from companysim.mc.runner import MonteCarloRunner
from companysim.ml.registry import TurnoverModelBundle, load_bundle
from companysim.ml.train import train_turnover_model
from companysim.ml.turnover_features import build_feature_frame
from companysim.ml.turnover_labels import build_turnover_cohort
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import Hire, Layoff, ManagerCoaching, PolicyChange, RetentionBonus, WorkloadRelief
from companysim.scenarios.scenario import BASELINE, Scenario

PRODUCTION_MODEL_PATH = Path("models/turnover_production.joblib")


# ---- caching ------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _build_rich_org(headcount: int, seed: int):
    cfg = DatasetConfig(name="dashboard", headcount=headcount, seed=seed)
    tables = DatasetBuilder(cfg).build()
    org = to_organization(tables, org_name=cfg.org_name)
    return org, tables


@st.cache_resource(show_spinner=False)
def _get_turnover_bundle(headcount: int, seed: int, horizon: int, replicates: int):
    if PRODUCTION_MODEL_PATH.exists():
        try:
            return load_bundle(PRODUCTION_MODEL_PATH, expected_type=TurnoverModelBundle), "production"
        except Exception:
            pass
    cfg = DatasetConfig(name="dashboard_train", headcount=headcount, seed=seed)
    cohort = build_turnover_cohort(cfg, horizon_ticks=horizon, replicates=replicates)
    feats = build_feature_frame(cohort.tables)
    merged = cohort.labels.merge(feats, on="employee_id")
    bundle, _report = train_turnover_model(merged, seed=seed)
    return bundle, "trained_live"


# ---- shared chart helper --------------------------------------------------


def _fan_chart(bands: pd.DataFrame, metric: str, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=bands["tick"], y=bands[f"{metric}_p95"],
        mode="lines", line={"width": 0}, showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=bands["tick"], y=bands[f"{metric}_p05"],
        mode="lines", line={"width": 0},
        fill="tonexty", fillcolor="rgba(31,119,180,0.2)",
        name="p05–p95",
    ))
    fig.add_trace(go.Scatter(
        x=bands["tick"], y=bands[f"{metric}_p50"],
        mode="lines", line={"color": "rgb(31,119,180)", "width": 2},
        name="median",
    ))
    fig.update_layout(
        title=title, xaxis_title="tick (week)", yaxis_title=metric,
        height=340, margin={"t": 40, "b": 40, "l": 40, "r": 20},
    )
    return fig


# ---- At-Risk Employees tab -------------------------------------------------


def _render_at_risk_tab() -> None:
    st.caption(
        "Who's likely to leave in the next quarter, and does a targeted "
        "intervention actually move the needle? Model predicts an actual "
        "simulated exit event — not a hand-set risk score — from features "
        "a real HRIS/pulse-survey platform would have (see sidebar note)."
    )

    with st.sidebar:
        st.header("At-Risk Employees")
        headcount = st.slider("Org headcount", 200, 2000, 800, step=100, key="risk_hc")
        seed = st.number_input("Seed", value=61, step=1, key="risk_seed")
        horizon = st.slider("Horizon (weeks)", 8, 20, 12, key="risk_horizon")
        top_k = st.slider("Target top-K at-risk employees", 5, 150, 40, key="risk_topk")
        intervention_type = st.selectbox(
            "Intervention", ["Retention Bonus", "Workload Relief", "Manager Coaching"],
        )
        magnitude = st.slider("Intervention magnitude", 0.05, 0.40, 0.20, step=0.05)
        comparison_replicates = st.slider("Comparison replicates", 10, 40, 20, key="risk_reps")
        run = st.button("Score org & run intervention", type="primary")

    if not run:
        st.info("Configure the analysis in the sidebar and click **Score org & run intervention**.")
        return

    with st.spinner("Generating org..."):
        org, tables = _build_rich_org(int(headcount), int(seed))

    with st.spinner("Loading/training turnover model..."):
        bundle, model_source = _get_turnover_bundle(
            min(int(headcount), 1200), int(seed), int(horizon), 3,
        )

    if model_source == "production":
        st.success("Using the production model from `models/turnover_production.joblib`.")
    else:
        st.warning(
            "No production model found — trained a fresh one on this session's "
            "population. Run `python scripts/train_turnover_model.py` to create "
            "a versioned production model instead."
        )

    feats = build_feature_frame({
        "employees": tables["employees"],
        "human_factors": tables["human_factors"],
        "wellness_snapshots": tables["wellness_snapshots"],
        "performance_history": tables["performance_history"],
    })
    ranked = rank_at_risk(bundle, feats)
    ranked_full = ranked.merge(
        tables["employees"][["employee_id", "full_name", "department_id", "level"]],
        on="employee_id",
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Headcount", org.headcount())
    col2.metric("High-risk employees", int((ranked["risk_tier"] == "high").sum()))
    col3.metric("Medium-risk employees", int((ranked["risk_tier"] == "medium").sum()))

    st.subheader("Top at-risk employees")
    st.dataframe(
        ranked_full.head(20)[["employee_id", "full_name", "department_id", "level", "turnover_probability", "risk_tier"]],
        height=300,
    )

    st.subheader("Risk by department")
    dept_risk = ranked_full.groupby("department_id")["turnover_probability"].mean().sort_values(ascending=False)
    st.bar_chart(dept_risk)

    # ---- Build the targeted scenario ----
    targets = tuple(ranked_full.head(int(top_k))["employee_id"].tolist())
    if intervention_type == "Retention Bonus":
        event = RetentionBonus(at_tick=1, employee_ids=targets, amount_pct=float(magnitude))
    elif intervention_type == "Workload Relief":
        event = WorkloadRelief(at_tick=1, employee_ids=targets, delta=float(magnitude))
    else:
        # Manager Coaching targets a team, not individuals — coach every
        # team that has at least one of the top-K at-risk employees.
        team_ids = tables["employees"].set_index("employee_id").loc[list(targets), "team_id"].unique()
        st.caption(f"Manager Coaching applied to {len(team_ids)} team(s) containing top-K at-risk employees.")
        scenario = Scenario(
            name="manager_coaching", description="Manager coaching for at-risk teams",
            events=[ManagerCoaching(at_tick=1, team_id=tid, delta=float(magnitude)) for tid in team_ids],
        )
        event = None

    if event is not None:
        scenario = Scenario(name=intervention_type.lower().replace(" ", "_"), events=[event])

    with st.spinner(f"Running {comparison_replicates} paired replicates..."):
        result = compare_intervention(
            org, tables["human_factors"], scenario,
            target_employee_ids=targets,
            replicates=int(comparison_replicates), horizon_ticks=int(horizon),
            base_seed=int(seed) + 5000,
        )

    st.subheader("Predicted impact")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baseline quits (targeted cohort)", f"{result.baseline_target_quits_p50:.0f}")
    c2.metric("Treated quits (targeted cohort)", f"{result.treated_target_quits_p50:.0f}")
    c3.metric("Quits avoided (mean)", f"{result.target_quits_avoided_mean:.2f}")
    c4.metric("Estimated cost", f"${result.estimated_cost:,.0f}")
    st.caption(
        f"Median avoided: {result.target_quits_avoided_p50:.1f} "
        f"(p05-p95: {result.target_quits_avoided_p05:.1f} to {result.target_quits_avoided_p95:.1f}). "
        "Small targeted cohorts produce noisy, discrete per-replicate counts — "
        "treat the band, not the point estimate, as the answer."
    )

    st.subheader("Company-wide context (baseline vs. treated)")
    left, right = st.columns(2)
    left.plotly_chart(_fan_chart(result.baseline.bands, "active_headcount", "Active headcount — baseline"),
                      use_container_width=True)
    right.plotly_chart(_fan_chart(result.treated.bands, "active_headcount", "Active headcount — treated"),
                       use_container_width=True)


# ---- Org Health tab (original scenario/fan-chart view) --------------------


def _build_org_health_scenario(name: str, department_ids: list[str]) -> Scenario:
    if name == "baseline":
        return BASELINE
    if name == "layoff_10pct":
        return Scenario(
            name="layoff_10pct",
            description="10% company-wide layoff at tick 5",
            events=[Layoff(at_tick=5, fraction=0.10)],
        )
    if name == "aggressive_hiring":
        dept = department_ids[0] if department_ids else "dept_00"
        return Scenario(
            name="aggressive_hiring",
            description="Hire 20 into engineering at ticks 2, 6, 10",
            events=[
                Hire(at_tick=2, count=20, department=dept),
                Hire(at_tick=6, count=20, department=dept),
                Hire(at_tick=10, count=20, department=dept),
            ],
        )
    if name == "wfh_policy_win":
        return Scenario(
            name="wfh_policy_win",
            description="Positive engagement shock at tick 3",
            events=[PolicyChange(at_tick=3, delta=+0.10)],
        )
    if name == "rto_mandate":
        return Scenario(
            name="rto_mandate",
            description="Negative engagement shock at tick 3",
            events=[PolicyChange(at_tick=3, delta=-0.15)],
        )
    return BASELINE


def _render_org_health_tab() -> None:
    st.caption("Company-wide productivity/engagement/turnover trends under broad policy scenarios.")

    with st.sidebar:
        st.header("Org Health")
        headcount = st.slider("Starting headcount", 50, 1000, 200, step=50, key="health_hc")
        ticks = st.slider("Simulation horizon (weeks)", 8, 80, 30, key="health_ticks")
        replicates = st.slider("Monte Carlo replicates", 5, 100, 25, key="health_reps")
        seed = st.number_input("Seed", value=42, step=1, key="health_seed")
        scenario_name = st.selectbox(
            "Scenario",
            ["baseline", "layoff_10pct", "aggressive_hiring", "wfh_policy_win", "rto_mandate"],
            key="health_scenario",
        )
        run = st.button("Run simulation", type="primary", key="health_run")

    if not run:
        st.info("Configure a scenario in the sidebar and click **Run simulation**.")
        return

    with st.spinner("Generating org..."):
        gen = WorkforceGenerator(GeneratorConfig(headcount=int(headcount), seed=int(seed)))
        org = gen.generate()
        dept_ids = [d.id for d in org.departments]

    scenario = _build_org_health_scenario(scenario_name, dept_ids)

    col1, col2, col3 = st.columns(3)
    col1.metric("Starting headcount", org.headcount())
    col2.metric("Teams", len(org.teams))
    col3.metric("Scenario events", len(scenario.events))

    with st.spinner(f"Running {replicates} Monte Carlo replicates..."):
        result = MonteCarloRunner(
            scenario=scenario,
            generator_config=gen.config,
            replicates=int(replicates),
            ticks=int(ticks),
            base_seed=int(seed) + 1000,
        ).run()

    st.subheader("Metric bands")
    left, right = st.columns(2)
    left.plotly_chart(_fan_chart(result.bands, "active_headcount", "Active headcount"),
                      use_container_width=True)
    right.plotly_chart(_fan_chart(result.bands, "mean_engagement", "Mean engagement"),
                       use_container_width=True)
    left.plotly_chart(_fan_chart(result.bands, "mean_productivity", "Mean productivity"),
                     use_container_width=True)
    right.plotly_chart(_fan_chart(result.bands, "mean_turnover_risk", "Mean turnover risk"),
                      use_container_width=True)

    st.subheader("Single-run trajectory")
    single = OrganizationModel(
        organization=org.model_copy(deep=True), seed=int(seed), scenario=scenario,
    ).run(int(ticks))
    st.dataframe(single, height=280)


# ---- entry point ------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="Digital Workforce Twin", layout="wide")
    st.title("Digital Workforce Twin")

    # A sidebar radio (not st.tabs) so each view's controls render on their
    # own — st.tabs executes every tab body on every rerun, which would
    # stack both views' sidebar widgets together since st.sidebar isn't
    # scoped per-tab.
    page = st.sidebar.radio("View", ["At-Risk Employees", "Org Health"])
    st.sidebar.divider()

    if page == "At-Risk Employees":
        _render_at_risk_tab()
    else:
        _render_org_health_tab()


if __name__ == "__main__":
    main()
