"""Tests for the (non-org-scoped) model training endpoints.

The turnover model itself is trained on a synthetic cohort, not any
specific org's data — but ``/model/status`` and ``/model/train`` now also
read ``turnover_training_examples`` (labeled examples collected from real
simulate/diagnose runs across all orgs), so these use the same isolated
in-memory DB fixture as the org-scoped test files.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_model_status_shape(client):
    resp = client.get("/model/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "model_available" in body
    assert isinstance(body["metadata"], dict)
    assert body["pending_training_examples"] == 0


def test_train_model_small_cohort_returns_decision(client):
    resp = client.post("/model/train", json={
        "headcount": 600, "replicates": 2, "horizon": 8, "seed": 4242,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] in {"PROMOTE", "BLOCK"}
    assert "auc" in body["candidate_eval"]
    assert 0.0 <= body["candidate_eval"]["auc"] <= 1.0
    assert body["train_report"]["n_train"] > 0
    assert body["n_live_examples"] == 0


def test_train_model_force_promote_always_promotes(client):
    resp = client.post("/model/train", json={
        "headcount": 600, "replicates": 2, "horizon": 8, "seed": 4243,
        "force_promote": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "PROMOTE"
    assert body["promoted_at"] is not None

    # Status should now reflect this run's seed.
    status = client.get("/model/status").json()
    assert status["model_available"] is True
    assert status["metadata"]["training_seed"] == 4243
