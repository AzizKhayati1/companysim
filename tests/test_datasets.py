from pathlib import Path

from companysim.data.datasets import DatasetBuilder, DatasetConfig, build_and_save


def test_small_build_row_counts_and_fks():
    cfg = DatasetConfig(name="tiny", headcount=250, seed=17)
    tables = DatasetBuilder(cfg).build()

    assert len(tables["employees"]) == 250
    assert len(tables["departments"]) == 9
    assert set(tables["teams"]["department_id"]) <= set(tables["departments"]["department_id"])
    assert set(tables["employees"]["department_id"]) <= set(tables["departments"]["department_id"])
    assert set(tables["employees"]["team_id"]) <= set(tables["teams"]["team_id"])
    # Every non-null manager id resolves to an employee.
    emp_ids = set(tables["employees"]["employee_id"])
    non_null = tables["employees"]["manager_employee_id"].dropna()
    assert set(non_null) <= emp_ids


def test_compensation_bounds_reasonable():
    cfg = DatasetConfig(name="tiny", headcount=300, seed=19)
    tables = DatasetBuilder(cfg).build()
    emps = tables["employees"]
    assert (emps["base_salary"] >= 30_000).all()
    assert (emps["base_salary"] <= 1_500_000).all()
    assert (emps["total_comp"] >= emps["base_salary"]).all()
    assert (emps["age"].between(22, 66)).all()


def test_reporting_chain_has_no_cycles():
    cfg = DatasetConfig(name="tiny", headcount=400, seed=21)
    tables = DatasetBuilder(cfg).build()
    mgr = dict(zip(tables["employees"]["employee_id"],
                    tables["employees"]["manager_employee_id"]))
    for emp in mgr:
        seen: set[str] = set()
        cur = emp
        while mgr.get(cur):
            assert cur not in seen, f"cycle at {cur}"
            seen.add(cur)
            cur = mgr[cur]


def test_save_writes_all_tables_in_both_formats(tmp_path: Path):
    cfg = DatasetConfig(name="tiny", headcount=150, seed=23)
    bundle = build_and_save(cfg, tmp_path)
    # Nine tables now: 7 core + human_factors + wellness_snapshots.
    assert len(bundle.all_paths()) == 9
    for p in bundle.all_paths():
        assert p.exists()
        assert p.with_suffix(".parquet").exists()
    assert (bundle.directory / "manifest.json").exists()


def test_human_factors_table_shape_and_columns():
    cfg = DatasetConfig(name="tiny", headcount=200, seed=31)
    tables = DatasetBuilder(cfg).build()
    hf = tables["human_factors"]
    assert len(hf) == 200
    # Coverage of the framework groups.
    for col in ("openness", "conscientiousness", "extraversion",
                "agreeableness", "neuroticism"):
        assert col in hf.columns and hf[col].between(0, 1).all()
    for col in ("burnout_exhaustion", "burnout_cynicism", "burnout_efficacy",
                "anxiety_symptom_score", "depression_symptom_score",
                "life_satisfaction"):
        assert col in hf.columns and hf[col].between(0, 1).all()
    for col in ("ace_score",):
        assert col in hf.columns and hf[col].between(0, 10).all()
    for col in ("attachment_style", "recent_life_event",
                "mental_health_engagement", "education_level"):
        assert col in hf.columns
    # First-gen professional stored as 0/1.
    assert set(hf["first_gen_professional"].unique()) <= {0, 1}


def test_wellness_snapshots_are_longitudinal():
    cfg = DatasetConfig(name="tiny", headcount=100, seed=37,
                          wellness_pulse_weeks=6)
    tables = DatasetBuilder(cfg).build()
    ws = tables["wellness_snapshots"]
    # Six weeks × 100 employees × ~75% response rate ≈ ~450 rows.
    assert 300 < len(ws) < 700
    for col in ("mood", "stress_level", "sleep_quality",
                "energy_level", "burnout_exhaustion"):
        assert ws[col].between(0, 1).all()
    assert ws["snapshot_date"].nunique() == 6
