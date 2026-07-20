# companysim — Digital Workforce Twin

An agent-based simulation platform for one decision-support question: **who
is at risk of leaving, and which intervention most reduces that risk, with
what confidence?**

The project started broader — agent-based modeling, synthetic data, ML,
Monte Carlo, MLOps, all at once, tied to no single deliverable. That made
the ML layer circular: it predicted `turnover_risk` from features that
*generated* `turnover_risk` in the first place (see
[`ml/registry.py`](src/companysim/ml/registry.py) module docstring). It's
now anchored on retention risk specifically, which makes every other piece
serve a concrete purpose:

- **Agent-based simulation** — employees carry Big Five personality,
  burnout/stress/mood, and team-climate feedback (see
  [`data/human_factors.py`](src/companysim/data/human_factors.py) for the
  organizational-psychology frameworks behind it); a discrete-time scheduler
  evolves the whole org week by week.
- **Synthetic data generation** — a rich HR dataset (comp, demographics,
  performance history, pulse-survey history) paired 1:1 with the simulation's
  day-0 agent state, so "features from the dataset" and "labels from
  forward-simulating that dataset" describe the same population.
- **Turnover model** — trained on *real simulated exit events*
  ([`ml/turnover_labels.py`](src/companysim/ml/turnover_labels.py)), not a
  hand-set score, using only features an HRIS/pulse-survey platform would
  actually have
  ([`ml/turnover_features.py`](src/companysim/ml/turnover_features.py)
  explicitly excludes the internal latents that would leak the label).
- **Targeted interventions** — retention bonus, workload relief, manager
  coaching, individually addressable
  ([`scenarios/events.py`](src/companysim/scenarios/events.py)) — and a
  what-if workflow ([`intervene.py`](src/companysim/intervene.py)) that
  measures the effect *within the targeted cohort* (company-wide totals are
  the wrong denominator for a targeted program — see that module's
  docstring), with a Monte Carlo uncertainty band and a cost estimate.
- **MLOps** — `scripts/train_turnover_model.py` retrains, evaluates against
  a fixed held-out cohort, and only promotes to production if the candidate
  doesn't regress AUC beyond a tolerance. Every decision is logged to
  `models/turnover_promotion_log.jsonl`.

## Status

Working end-to-end, verified in the browser via the Streamlit dashboard:

- Rich synthetic HR dataset generation at 3 sizes (500 / 5,000 / 25,000
  employees), 9 tables including human-factors and pulse-survey history
- Agent-based simulation with burnout/engagement/turnover dynamics, a
  scenario DSL (company-wide and individually-targeted events), and a
  Monte Carlo runner
- A turnover classifier trained on real simulated exit events (realistic
  AUC ~0.6–0.7 — high enough to be useful, not so high it implies leakage)
- A what-if workflow: rank at-risk employees, target an intervention, see
  the predicted retention lift and its cost with uncertainty bands
- An MLOps promotion gate with a fixed evaluation benchmark and an audit log
- A two-view dashboard: **At-Risk Employees** (headline) and **Org Health**
  (company-wide scenario fan charts)

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -e ".[dev,ml,viz,api]"

# Basic sim demo
python scripts/demo.py

# Generate the rich synthetic datasets (small/medium/large)
python scripts/build_datasets.py

# Build a turnover-labeled cohort and inspect it
python scripts/build_turnover_cohort.py --headcount 3000 --replicates 5

# Train + gate the turnover model (writes models/turnover_production.joblib)
python scripts/train_turnover_model.py

# Dashboard
streamlit run src/companysim/dashboard/app.py

pytest
```

### Webapp/API database migrations

The webapp's SQLite DB (`data/app.db`) is schema-versioned with Alembic —
`api/database.py::init_db()` runs `alembic upgrade head` automatically on
every server startup, so a fresh clone gets the full schema and an
existing DB just picks up anything new. When you change a model in
`api/db_models.py`, generate the matching migration and commit it
alongside the model change:

```bash
alembic revision --autogenerate -m "describe the change"
# review the generated script in migrations/versions/ before committing
```

## Layout

```
src/companysim/
  data/          # synthetic data generation, schemas, human-factors framework
  agents/        # EmployeeAgent, TeamAgent
  model/         # OrganizationModel — the top-level simulation
  scenarios/     # Scenario DSL — company-wide and individually-targeted events
  mc/            # Monte Carlo runner (percentile bands over replicates)
  ml/            # turnover labels/features/training + model registry
  intervene.py   # what-if workflow — rank at-risk, compare interventions
  dashboard/     # Streamlit app
  cli.py
scripts/         # runnable entry points (demo, dataset build, cohort build, train)
tests/
```
