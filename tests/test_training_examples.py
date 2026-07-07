"""Tests for the "learn from real webapp runs" MLOps pass:

- ``OrganizationModel.organic_quit_ids`` correctly excludes event-forced
  deactivation (Layoff/Termination) from organic quits.
- ``/simulate`` and ``/diagnose`` collect labeled training examples, gated
  by a minimum horizon and never mislabeling an event-removed employee as
  a voluntary quit.
- ``ml.gate.run_training_gate`` blends collected examples into training.
- ``/model/status``/``/model/train`` surface the collected-example count.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import TurnoverTrainingExample
from companysim.api.main import app
from companysim.data.datasets import DatasetBuilder, DatasetConfig, to_organization
from companysim.ml.gate import run_training_gate
from companysim.ml.turnover_features import FEATURE_COLUMNS
from companysim.model.organization import OrganizationModel
from companysim.scenarios.events import Termination
from companysim.scenarios.scenario import Scenario


# ---- engine-level: organic_quit_ids ----------------------------------

def _rich_org(headcount: int = 150, seed: int = 61):
    cfg = DatasetConfig(name="mlops", headcount=headcount, seed=seed)
    tables = DatasetBuilder(cfg).build()
    return to_organization(tables, org_name=cfg.org_name), tables


def test_organic_quit_ids_excludes_termination_target():
    org, tables = _rich_org(headcount=300, seed=91)
    target = org.employees[0].id
    scenario = Scenario(name="term", events=[Termination(at_tick=1, employee_ids=(target,))])
    model = OrganizationModel(org, seed=91, human_factors=tables["human_factors"], scenario=scenario)
    model.run(12)

    assert model.employees[target].active is False
    assert target not in model.organic_quit_ids
    # A 300-person org over 12 weeks should produce at least one real
    # organic quit distinct from the terminated employee.
    assert len(model.organic_quit_ids) > 0
    for eid in model.organic_quit_ids:
        assert model.employees[eid].active is False
        assert eid != target


# ---- API-level: collection wiring ------------------------------------

@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_simulate_with_sufficient_ticks_collects_one_example_per_employee(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 1}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 6, "replicates": 1, "seed": 1})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(TurnoverTrainingExample).filter_by(org_id=org["id"]).all()
    assert len(rows) == 40
    assert all(r.horizon_ticks == 6 for r in rows)


def test_simulate_with_short_ticks_collects_nothing(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 30, "seed": 2}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 5, "replicates": 1, "seed": 2})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(TurnoverTrainingExample).filter_by(org_id=org["id"]).all()
    assert rows == []


def test_monte_carlo_simulate_collects_nothing(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 30, "seed": 3}).json()
    resp = client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 8, "replicates": 5, "seed": 3})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(TurnoverTrainingExample).filter_by(org_id=org["id"]).all()
    assert rows == []


def test_termination_event_never_labeled_as_organic_quit(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 4}).json()
    emps = client.get(f"/orgs/{org['id']}/employees").json()
    target_id = emps[0]["id"]

    resp = client.post(f"/orgs/{org['id']}/simulate", json={
        "ticks": 10, "replicates": 1, "seed": 4,
        "events": [{"type": "termination", "at_tick": 1, "params": {"employee_ids": [target_id]}}],
    })
    assert resp.status_code == 200

    db = db_session_factory()
    target_row = (
        db.query(TurnoverTrainingExample)
        .filter_by(org_id=org["id"], employee_id=target_id)
        .one()
    )
    assert target_row.quit_within_horizon is False


def test_diagnose_also_collects_examples(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 30, "seed": 5}).json()
    resp = client.post(f"/orgs/{org['id']}/diagnose", json={"ticks": 8, "replicates": 1, "seed": 5})
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(TurnoverTrainingExample).filter_by(org_id=org["id"]).all()
    assert len(rows) == 30


# ---- gate blending ------------------------------------------------------

def test_gate_blends_extra_examples_into_training():
    extra = pd.DataFrame([
        {**{col: 0 for col in FEATURE_COLUMNS}, "quit_within_horizon": i % 2 == 0}
        for i in range(20)
    ])
    # Give the categorical columns valid string values (0 would be an odd
    # but technically-legal category for OneHotEncoder; use real ones).
    extra["level"] = "IC2"
    extra["department_id"] = "999"
    extra["role"] = "engineer"

    result = run_training_gate(headcount=300, replicates=1, horizon=6, seed=12345, extra_examples=extra)

    assert result.n_live_examples == 20
    assert result.train_report["n_train"] + result.train_report["n_test"] >= 300 + 20


def test_gate_with_no_extra_examples_reports_zero():
    result = run_training_gate(headcount=300, replicates=1, horizon=6, seed=12346, extra_examples=None)
    assert result.n_live_examples == 0


# ---- surfaced via /model/* ----------------------------------------------

def test_model_status_reflects_collected_example_count(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 25, "seed": 6}).json()
    client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 7, "replicates": 1, "seed": 6})

    status = client.get("/model/status").json()
    assert status["pending_training_examples"] == 25


def test_train_model_reports_n_live_examples_matching_seeded_count(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 25, "seed": 7}).json()
    client.post(f"/orgs/{org['id']}/simulate", json={"ticks": 7, "replicates": 1, "seed": 7})

    resp = client.post("/model/train", json={
        "headcount": 300, "replicates": 1, "horizon": 6, "seed": 8888,
    })
    assert resp.status_code == 200
    assert resp.json()["n_live_examples"] == 25
