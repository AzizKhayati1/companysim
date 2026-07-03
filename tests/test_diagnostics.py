import numpy as np
import pandas as pd
import pytest

from companysim.ml.diagnostics import diagnose, detect_problems, explain, recommend


def _flat_history(ticks: int = 10) -> pd.DataFrame:
    return pd.DataFrame({
        "tick": range(ticks),
        "burnout_rate": [0.05] * ticks,
        "mean_engagement": [0.6] * ticks,
        "mean_turnover_risk": [0.3] * ticks,
        "quits_this_tick": [1] * ticks,
        "active_headcount": [200 - i for i in range(ticks)],
    })


def _spiky_history() -> pd.DataFrame:
    return pd.DataFrame({
        "tick": range(10),
        "burnout_rate": [0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.20, 0.19, 0.17, 0.16],
        "mean_engagement": [0.6, 0.6, 0.59, 0.55, 0.5, 0.45, 0.44, 0.45, 0.46, 0.47],
        "mean_turnover_risk": [0.3, 0.31, 0.33, 0.38, 0.44, 0.5, 0.52, 0.51, 0.5, 0.49],
        "quits_this_tick": [1, 1, 0, 1, 2, 5, 1, 0, 1, 1],
        "active_headcount": [200, 199, 199, 198, 196, 191, 190, 190, 189, 188],
    })


def _skewed_driver_frame(bad_department: str = "Engineering") -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for dept in ["Engineering", "Sales", "Design"]:
        for i in range(30):
            bad = dept == bad_department
            rows.append({
                "employee_id": f"{dept}_{i}",
                "department_id": dept,
                "team_id": f"{dept}_team_{i % 3}",
                "workload_perceived": rng.normal(0.75 if bad else 0.45, 0.05),
                "manager_support_score": rng.normal(0.35 if bad else 0.6, 0.05),
                "financial_security_score": rng.normal(0.5, 0.05),
            })
    return pd.DataFrame(rows)


def test_detect_problems_stays_silent_on_flat_history():
    problems = detect_problems(_flat_history())
    assert problems == []


def test_detect_problems_fires_on_each_threshold():
    problems = detect_problems(_spiky_history())
    metrics = {p.metric for p in problems}
    assert metrics == {"burnout_rate", "mean_engagement", "mean_turnover_risk", "quits_this_tick"}
    for p in problems:
        assert 0.0 <= p.severity <= 1.0
        assert p.tick >= 0


def test_diagnose_ranks_the_injected_bad_department_first():
    problems = detect_problems(_spiky_history())
    frame = _skewed_driver_frame(bad_department="Engineering")
    diagnosis = diagnose(problems[0], frame)

    assert len(diagnosis.primary_drivers) > 0
    top = diagnosis.primary_drivers[0]
    assert top.feature == "workload_perceived"
    assert "Engineering" in top.segment_id
    assert top.deviation > 0  # workload is higher-is-bad, so positive deviation


def test_diagnose_with_no_numeric_columns_returns_empty():
    problems = detect_problems(_spiky_history())
    frame = pd.DataFrame({"employee_id": ["a", "b"], "department_id": ["X", "Y"]})
    diagnosis = diagnose(problems[0], frame)
    assert diagnosis.primary_drivers == []


@pytest.mark.parametrize("bad_department,expected_event", [
    ("Engineering", "workload_relief"),   # workload is the injected driver
])
def test_recommend_maps_driver_to_expected_event_type(bad_department, expected_event):
    problems = detect_problems(_spiky_history())
    frame = _skewed_driver_frame(bad_department=bad_department)
    diagnosis = diagnose(problems[0], frame)
    rec = recommend(diagnosis, frame)
    assert rec.event_type == expected_event
    assert len(rec.target_employee_ids) > 0
    assert all(eid.startswith(bad_department) for eid in rec.target_employee_ids)


def test_recommend_manager_support_maps_to_coaching():
    rng = np.random.default_rng(1)
    rows = []
    for dept in ["Engineering", "Sales"]:
        for i in range(30):
            bad = dept == "Sales"
            rows.append({
                "employee_id": f"{dept}_{i}",
                "department_id": dept,
                "team_id": f"{dept}_team_{i % 2}",
                "manager_support_score": rng.normal(0.30 if bad else 0.65, 0.05),
            })
    frame = pd.DataFrame(rows)
    problems = detect_problems(_spiky_history())
    diagnosis = diagnose(problems[0], frame)
    rec = recommend(diagnosis, frame)
    assert rec.event_type == "manager_coaching"


def test_recommend_with_no_drivers_falls_back_to_default():
    from companysim.ml.diagnostics import Diagnosis
    problems = detect_problems(_spiky_history())
    diagnosis = Diagnosis(problem=problems[0], primary_drivers=[])
    rec = recommend(diagnosis, pd.DataFrame())
    assert rec.event_type == "policy_change"
    assert rec.target_employee_ids == []


def test_explain_produces_nonempty_readable_string():
    problems = detect_problems(_spiky_history())
    frame = _skewed_driver_frame()
    diagnosis = diagnose(problems[0], frame)
    rec = recommend(diagnosis, frame)
    text = explain(problems[0], diagnosis, rec)
    assert isinstance(text, str)
    assert len(text) > 50
    assert "Recommended" in text
