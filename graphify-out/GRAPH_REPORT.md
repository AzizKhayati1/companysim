# Graph Report - .  (2026-07-14)

## Corpus Check
- Corpus is ~45,537 words - fits in a single context window. You may not need a graph.

## Summary
- 947 nodes · 1832 edges · 57 communities (47 shown, 10 thin omitted)
- Extraction: 77% EXTRACTED · 23% INFERRED · 0% AMBIGUOUS · INFERRED: 423 edges (avg confidence: 0.76)
- Token cost: 403,215 input · 0 output

## Community Hubs (Navigation)
- Database Models & Schemas
- Dataset Generation Pipeline
- Webapp Core Components
- Diagnosis PDF Export
- Turnover Model Training
- Diagnosis Threshold Rules
- Employee Agent Simulation
- API Converters & Risk Snapshots
- Frontend Dependencies
- Team Agent & Human Profile
- Scenario Event Types
- Streamlit Dashboard
- Exit Notes NLP
- Webapp TS Config (App)
- Tech Stack Concepts
- Webapp TS Config (Node)
- Monte Carlo Simulation
- Workforce Generator & Tests
- Scenario & Life Event Logic
- API Integration Tests
- Risk Snapshot Feature & Tests
- Training Example Collection & Tests
- Human Factors Generation
- Intervention Events & Tests
- Diagnose Export Tests
- Diagnosis Report Building
- Webapp Lint Config
- Run History Tests
- Psychology Research Instruments
- Core Module Docs
- Webapp Framework Concepts
- Documented Bug Fixes
- MLOps Live Learning
- Organization Model Tests
- Unused Icon Sprite
- Model API Tests
- ML Circularity Bug & Registry
- CLI Demo Script
- Webapp Architecture Concept
- Webapp TS Config Root
- Package Init
- Package Root
- Favicon Asset
- Hero Graphic Asset
- React Logo Asset
- Vite Logo Asset

## God Nodes (most connected - your core abstractions)
1. `OrganizationModel` - 65 edges
2. `Digital Workforce Twin — Project Overview` - 63 edges
3. `Scenario` - 40 edges
4. `DatasetBuilder` - 30 edges
5. `WorkforceGenerator` - 30 edges
6. `GeneratorConfig` - 28 edges
7. `build_diagnosis_report()` - 26 edges
8. `DatasetConfig` - 26 edges
9. `TurnoverModelBundle` - 23 edges
10. `build_event()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Quit-counting bug fix` --references--> `EmployeeAgent`  [EXTRACTED]
  docs/project_overview.md → src/companysim/agents/employee.py
- `At-risk scoring schema gap adapter` --references--> `build_scoring_frame()`  [EXTRACTED]
  docs/project_overview.md → src/companysim/api/scoring_frame.py
- `routers/simulate.py module` --shares_data_with--> `collect_training_examples()`  [EXTRACTED]
  docs/project_overview.md → src/companysim/api/training_examples.py
- `Project Overview (PDF export)` --semantically_similar_to--> `Digital Workforce Twin — Project Overview`  [INFERRED] [semantically similar]
  docs/project_overview.pdf → docs/project_overview.md
- `Digital Workforce Twin — Project Overview` --references--> `EmployeeAgent`  [EXTRACTED]
  docs/project_overview.md → src/companysim/agents/employee.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **detect_problems() four threshold checks** — docs_diagnosis_thresholds_detect_problems_checks, docs_diagnosis_thresholds_burnout_rate_check, docs_diagnosis_thresholds_engagement_drop_check, docs_diagnosis_thresholds_turnover_risk_rise_check, docs_diagnosis_thresholds_quit_spike_check [EXTRACTED 1.00]
- **Honesty fixes made during the retention-risk reframe (project_overview.md §5)** — docs_project_overview_two_populations_divergence_fix, docs_project_overview_quit_counting_bug_fix, docs_project_overview_weak_signal_calibration, docs_project_overview_targeted_cohort_denominator, docs_project_overview_locale_formatting_bug_fix, docs_project_overview_layoff_vs_quit_fix [EXTRACTED 1.00]
- **Root-cause diagnosis pipeline: detect, diagnose, recommend, explain** — src_companysim_ml_diagnostics_detect_problems, src_companysim_ml_diagnostics_diagnose, src_companysim_ml_diagnostics_recommend, src_companysim_ml_diagnostics_explain [EXTRACTED 1.00]

## Communities (57 total, 10 thin omitted)

### Community 0 - "Database Models & Schemas"
Cohesion: 0.06
Nodes (63): DeclarativeBase, DepartmentIn, EmployeeIn, EmployeeOut, FastAPI, OrgSummary, Base, get_db() (+55 more)

### Community 1 - "Dataset Generation Pipeline"
Cohesion: 0.06
Nodes (52): main(), Path, Generate three sized synthetic datasets and print their paths.  Writes to ``data, main(), Materialize a turnover-labeled cohort to disk (features + real exit labels).  St, api/converters.py module, build_and_save(), DatasetBuilder (+44 more)

### Community 2 - "Webapp Core Components"
Cohesion: 0.07
Nodes (50): react, api, App(), DiagnosisResults(), Props, FanChart(), FanChartProps, METRICS (+42 more)

### Community 3 - "Diagnosis PDF Export"
Cohesion: 0.06
Nodes (56): DiagnosisReportOut, FPDF, NotesSummaryOut, _add_problem_block(), _DiagnosisPDF, DiagnoseResponse, Render a ``DiagnoseResponse`` into a shareable PDF via fpdf2.  Pure-Python PDF g, fpdf2's built-in fonts are Latin-1 only; swap common smart-quote/dash     unicod (+48 more)

### Community 4 - "Turnover Model Training"
Cohesion: 0.07
Nodes (46): main(), Train the behavioral bundle and persist it to models/behavioral.joblib., main(), CLI wrapper around companysim.ml.gate.run_training_gate.  Train the turnover cla, load_production_bundle(), Load the trained production model, or ``None`` if it doesn't exist     or fails, _append_log(), _decide() (+38 more)

### Community 5 - "Diagnosis Threshold Rules"
Cohesion: 0.10
Nodes (43): Burnout-rate direct-crossing check, Threshold calibration rationale, DEFAULT_THRESHOLDS, detect_problems() four threshold checks, Diagnosis Thresholds doc, Engagement-drop rolling-peak check, ProblemFlag, Quit-spike ratio check (with noise floor) (+35 more)

### Community 6 - "Employee Agent Simulation"
Cohesion: 0.08
Nodes (25): Faker, _clamp(), EmployeeAgent, Employee agent.  Wraps an :class:`Employee` record and a :class:`HumanProfile` a, Advance the agent one tick.          ``team_climate`` — 0..1 signal of peer enga, _build_employee(), _generate_new_hire(), Synthetic workforce data generation.  Produces a fully-formed :class:`Organizati (+17 more)

### Community 7 - "API Converters & Risk Snapshots"
Cohesion: 0.07
Nodes (37): CompareInterventionRequest, ScenarioEventIn, dept_str_id(), emp_str_id(), org_to_pydantic(), DataFrame, Session, Convert persisted DB state into the objects the simulation engine already consum (+29 more)

### Community 8 - "Frontend Dependencies"
Cohesion: 0.06
Nodes (35): oxlint, react, react-dom, react-router-dom, recharts, @tanstack/react-query, @types/node, @types/react (+27 more)

### Community 9 - "Team Agent & Human Profile"
Cohesion: 0.08
Nodes (17): Everything an employee produced in a single tick., TickOutcome, Team agent.  Aggregates members' state into two team-level signals fed back to e, TeamAgent, HumanProfile, Any, Compact per-agent record consumed by :class:`EmployeeAgent.step`., Build a profile from a row of the ``human_factors`` table.          This is what (+9 more)

### Community 10 - "Scenario Event Types"
Cohesion: 0.09
Nodes (20): Protocol, Event, Hire, Layoff, PolicyChange, Promotion, Scenario events — declarative mutations of the running simulation.  Each event k, Coarse policy lever — shifts every active employee's engagement by ``delta``. (+12 more)

### Community 11 - "Streamlit Dashboard"
Cohesion: 0.12
Nodes (23): Figure, _build_org_health_scenario(), _build_rich_org(), _fan_chart(), _get_turnover_bundle(), main(), DataFrame, Streamlit dashboard — retention risk & intervention simulator.  Run with:      s (+15 more)

### Community 12 - "Exit Notes NLP"
Cohesion: 0.14
Nodes (24): analyze_notes(), augment_explanation_with_notes(), generate_note(), generate_notes_for_employees(), _match_themes(), NotesAnalysis, Any, DataFrame (+16 more)

### Community 13 - "Webapp TS Config (App)"
Cohesion: 0.08
Nodes (23): DOM, src, vite/client, compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx (+15 more)

### Community 14 - "Tech Stack Concepts"
Cohesion: 0.10
Nodes (22): Faker, FastAPI, MLflow (optional), NumPy / Pandas, Pydantic, pytest + FastAPI TestClient (httpx2), Python 3.13, React Router (+14 more)

### Community 15 - "Webapp TS Config (Node)"
Cohesion: 0.10
Nodes (19): node, vite.config.ts, compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection (+11 more)

### Community 16 - "Monte Carlo Simulation"
Cohesion: 0.14
Nodes (13): Compare a baseline against a 10% layoff and an RTO mandate.  Prints tick-by-tick, run(), compute_percentile_bands(), MonteCarloResult, MonteCarloRunner, DataFrame, Monte Carlo runner — sweeps stochastic uncertainty across a scenario.  For each, p05/p50/p95 per tick across replicates, for any (tick, replicate,     metric...) (+5 more)

### Community 17 - "Workforce Generator & Tests"
Cohesion: 0.20
Nodes (16): _run_demo(), GeneratorConfig, Deterministic synthetic org generator.      Same ``seed`` → same org, every time, WorkforceGenerator, No cycles, everyone but the top eventually reaches a dept head., test_every_employee_has_a_team_and_department(), test_generator_is_deterministic(), test_headcount_matches_config() (+8 more)

### Community 18 - "Scenario & Life Event Logic"
Cohesion: 0.18
Nodes (14): BudgetCut, LifeEvent, Reduce financial security org-wide or for one department — the     inverse of :c, Something happens outside work — the direct lever for the     human-factors fram, A Scenario is just an ordered bundle of events.  Two scenarios with the same eve, Scenario, _rich_org(), test_budget_cut_department_scoping() (+6 more)

### Community 20 - "Risk Snapshot Feature & Tests"
Cohesion: 0.18
Nodes (13): EmployeeRiskSnapshot, The production model's predicted turnover risk for one employee, at     the mome, db_session_factory(), Tests for the per-employee risk-history snapshot feature:  - Every Simulate run, No trained model on disk in the test environment by default (or if     there is, Differs from TurnoverTrainingExample, which skips Monte Carlo runs —     a risk, No minimum-horizon gate — unlike training examples, a 1-tick run     still snaps, test_at_risk_endpoint_works_without_production_model() (+5 more)

### Community 21 - "Training Example Collection & Tests"
Cohesion: 0.24
Nodes (10): A labeled example collected from a real webapp simulate/diagnose run.      Featu, TurnoverTrainingExample, db_session_factory(), Tests for the "learn from real webapp runs" MLOps pass:  - ``OrganizationModel.o, test_diagnose_also_collects_examples(), test_gate_with_no_extra_examples_reports_zero(), test_monte_carlo_simulate_collects_nothing(), test_simulate_with_short_ticks_collects_nothing() (+2 more)

### Community 22 - "Human Factors Generation"
Cohesion: 0.26
Nodes (13): _age_caregiving_bump(), autonomy_seed(), _beta(), generate_human_factors(), HumanFactorsBundle, DataFrame, ndarray, Human factors — psychological, wellbeing, and life-context modeling.  Draws on e (+5 more)

### Community 23 - "Intervention Events & Tests"
Cohesion: 0.24
Nodes (9): ManagerCoaching, Reduce baseline workload for specific employees (redistribute work,     hire bac, Raise manager support / psychological safety for a whole team —     the lever wh, WorkloadRelief, _rich_org(), test_manager_coaching_lifts_team_support_and_psych_safety(), test_retention_bonus_reduces_targeted_turnover_risk(), test_unknown_team_id_is_a_no_op() (+1 more)

### Community 24 - "Diagnose Export Tests"
Cohesion: 0.29
Nodes (7): _forced_quit_request(), _make_org_and_first_dept(), Tests for the notes-augmented diagnosis explanation and PDF export.  Same isolat, A reorg shock big enough to force real quits in the diagnosed     segment within, test_diagnose_export_returns_pdf(), test_diagnose_export_same_seed_is_deterministic(), test_diagnose_notes_summary_shape_is_always_valid()

### Community 25 - "Diagnosis Report Building"
Cohesion: 0.22
Nodes (8): fpdf2, Exit-notes NLP layer, build_diagnosis_report(), routers/diagnose.py module, api/scenario_builder.py module, collect_training_examples(), Session, Collect labeled turnover-model training examples from real webapp runs.  Every `

### Community 26 - "Webapp Lint Config"
Cohesion: 0.22
Nodes (8): oxc, typescript, warn, plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 28 - "Psychology Research Instruments"
Cohesion: 0.25
Nodes (8): CDC-Kaiser Adverse Childhood Experiences (ACE) study, Attachment style (Hazan & Shaver), Big Five personality model (Costa & McCrae 1992), Human-factors framework, Job Demand-Control-Support model (Karasek), Maslach Burnout Inventory (exhaustion/cynicism/efficacy), Psychological safety (Edmondson 1999), Pulse-survey design (CultureAmp/Peakon-style continuous listening)

### Community 29 - "Core Module Docs"
Cohesion: 0.25
Nodes (8): Scenario DSL / event library, companysim README, scripts/train_turnover_model.py, data/human_factors.py module, FEATURE_COLUMNS, ml/turnover_features.py module, ml/turnover_labels.py module, scenarios/events.py module

### Community 30 - "Webapp Framework Concepts"
Cohesion: 0.38
Nodes (7): Oxlint (oxlint-tsgolint, type-aware rules), React Compiler (not enabled in this template), React 19 + TypeScript (Vite), @vitejs/plugin-react (uses Oxc), @vitejs/plugin-react-swc (uses SWC), webapp index.html entry point, webapp README (Vite + React + TS template)

### Community 31 - "Documented Bug Fixes"
Cohesion: 0.29
Nodes (7): Digital Workforce Twin platform, Layoff-vs-voluntary-quit conflation fix, Locale formatting bug fix (webapp), Quit-counting bug fix, Two-populations divergence fix, Weak predictive signal diagnosis and calibration, OrganizationModel.organic_quit_ids

### Community 32 - "MLOps Live Learning"
Cohesion: 0.43
Nodes (7): MLOps live-learning loop, MLOps promotion gate, routers/model.py module, load_collected_examples(), DataFrame, All collected examples, reshaped to ``FEATURE_COLUMNS`` + label —     ready to c, ml/gate.py module (MLOps promotion gate)

### Community 33 - "Organization Model Tests"
Cohesion: 0.48
Nodes (6): _model(), Nobody joins mid-sim yet, so active headcount only falls., test_headcount_is_non_increasing_over_time(), test_run_is_reproducible(), test_run_returns_history_of_expected_length(), test_step_produces_snapshot()

### Community 34 - "Unused Icon Sprite"
Cohesion: 0.29
Nodes (7): Bluesky Icon Symbol, Discord Icon Symbol, Documentation Icon Symbol, GitHub Icon Symbol, Social (Generic Community) Icon Symbol, icons.svg (Social/Utility Icon Sprite), X (Twitter) Icon Symbol

### Community 36 - "ML Circularity Bug & Registry"
Cohesion: 0.40
Nodes (5): joblib, At-risk scoring schema gap adapter, ML circularity bug (predicting turnover_risk from its own generating features), Retention-risk decision-support question, ml/registry.py module

### Community 37 - "CLI Demo Script"
Cohesion: 0.40
Nodes (3): Runnable demo — same as `companysim demo` but importable standalone., main(), Command-line entry point.  Usage:      companysim demo --headcount 200 --ticks 3

### Community 38 - "Webapp Architecture Concept"
Cohesion: 0.50
Nodes (4): Streamlit + Plotly, Webapp architecture (thin adapters over one simulation engine), routers/simulate.py module, dashboard/app.py (Streamlit dashboard)

## Knowledge Gaps
- **109 isolated node(s):** `companysim`, `$schema`, `typescript`, `oxc`, `react/rules-of-hooks` (+104 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Digital Workforce Twin — Project Overview` connect `Tech Stack Concepts` to `MLOps Live Learning`, `Dataset Generation Pipeline`, `Webapp Core Components`, `ML Circularity Bug & Registry`, `Diagnosis Threshold Rules`, `Webapp Architecture Concept`, `Employee Agent Simulation`, `API Converters & Risk Snapshots`, `Team Agent & Human Profile`, `Streamlit Dashboard`, `Monte Carlo Simulation`, `Diagnosis Report Building`, `Core Module Docs`, `Webapp Framework Concepts`, `Documented Bug Fixes`?**
  _High betweenness centrality (0.234) - this node is a cross-community bridge._
- **Why does `OrganizationModel` connect `Team Agent & Human Profile` to `Dataset Generation Pipeline`, `Organization Model Tests`, `Diagnosis PDF Export`, `Webapp Architecture Concept`, `API Converters & Risk Snapshots`, `Employee Agent Simulation`, `Scenario Event Types`, `Streamlit Dashboard`, `Tech Stack Concepts`, `Monte Carlo Simulation`, `Workforce Generator & Tests`, `Scenario & Life Event Logic`, `Intervention Events & Tests`, `Diagnosis Report Building`?**
  _High betweenness centrality (0.224) - this node is a cross-community bridge._
- **Why does `build_diagnosis_report()` connect `Diagnosis PDF Export` to `Turnover Model Training`, `Diagnosis Threshold Rules`, `API Converters & Risk Snapshots`, `Team Agent & Human Profile`, `Exit Notes NLP`, `Diagnosis Report Building`?**
  _High betweenness centrality (0.130) - this node is a cross-community bridge._
- **Are the 45 inferred relationships involving `OrganizationModel` (e.g. with `simulate()` and `_run_demo()`) actually correct?**
  _`OrganizationModel` has 45 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `Scenario` (e.g. with `compare_intervention_endpoint()` and `InterventionComparison`) actually correct?**
  _`Scenario` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `DatasetBuilder` (e.g. with `create_org()` and `_build_rich_org()`) actually correct?**
  _`DatasetBuilder` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `WorkforceGenerator` (e.g. with `_run_demo()` and `_render_org_health_tab()`) actually correct?**
  _`WorkforceGenerator` has 22 INFERRED edges - model-reasoned connections that need verification._