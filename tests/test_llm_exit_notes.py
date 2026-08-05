"""Tests for the optional Groq-backed exit-note generator.

All tests here mock the ``groq.Groq`` client boundary — no real network
calls, no API key required, deterministic and free to run in CI. That's
deliberate: the checked-in test suite (and CI) never depends on live LLM
access, matching this project's existing "fully deterministic, no API
keys needed" testing philosophy (see ``ml/exit_notes.py``'s module
docstring) even though the feature itself is a real, live integration.
"""
from __future__ import annotations

import types

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.main import app
from companysim.ml import llm_exit_notes

pytest.importorskip(
    "groq",
    reason="groq (the optional 'llm' extra) is not installed — "
    "these tests exercise the mocked-out Groq boundary and need the "
    "package importable to patch it, even though no real network calls happen.",
)


def _fake_groq_client(content: str | None = None, error: Exception | None = None):
    """Builds a fake ``groq.Groq``-shaped class whose
    ``chat.completions.create(...)`` either raises ``error`` or returns a
    response with ``choices[0].message.content == content``."""
    def _client_factory(api_key):
        def create(**kwargs):
            if error is not None:
                raise error
            message = types.SimpleNamespace(content=content, tool_calls=None)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    return _client_factory


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv(llm_exit_notes._FLAG_VAR, raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


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


def test_disabled_by_default(monkeypatch):
    assert llm_exit_notes.is_llm_enabled() is False


def test_flag_alone_is_not_enough(monkeypatch):
    monkeypatch.setenv(llm_exit_notes._FLAG_VAR, "1")
    assert llm_exit_notes.is_llm_enabled() is False


def test_key_alone_is_not_enough(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    assert llm_exit_notes.is_llm_enabled() is False


def test_flag_and_key_together_enable_it(monkeypatch):
    monkeypatch.setenv(llm_exit_notes._FLAG_VAR, "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    assert llm_exit_notes.is_llm_enabled() is True


def test_neutral_profile_produces_no_prompt():
    assert llm_exit_notes._build_prompt({"workload_perceived": 0.5, "mood": 0.5}) is None


def test_bad_profile_prompt_mentions_the_worst_driver():
    prompt = llm_exit_notes._build_prompt({"workload_perceived": 0.95, "mood": 0.5})
    assert prompt is not None
    assert "workload" in prompt.lower()


def test_generate_note_via_llm_returns_none_on_api_failure(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr("groq.Groq", _fake_groq_client(error=RuntimeError("simulated API failure")))
    note = llm_exit_notes.generate_note_via_llm({"workload_perceived": 0.95, "mood": 0.5})
    assert note is None


def test_generate_note_via_llm_returns_text_on_success(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq", _fake_groq_client(content="  I left because of the relentless workload.  "),
    )
    note = llm_exit_notes.generate_note_via_llm({"workload_perceived": 0.95, "mood": 0.5})
    assert note == "I left because of the relentless workload."


def test_generate_note_via_llm_returns_none_for_neutral_profile(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # No mocked client needed — a neutral profile short-circuits before any API call.
    note = llm_exit_notes.generate_note_via_llm({"workload_perceived": 0.5, "mood": 0.5})
    assert note is None


def test_mixed_generator_falls_back_to_template_on_failure(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr("groq.Groq", _fake_groq_client(error=RuntimeError("simulated API failure")))

    driver_frame = pd.DataFrame([
        {"employee_id": 1, "workload_perceived": 0.95, "manager_support_score": 0.15},
    ])
    notes, llm_employee_ids = llm_exit_notes.generate_notes_for_employees_mixed(
        driver_frame, [1], np.random.default_rng(1),
    )
    assert llm_employee_ids == set()
    assert 1 in notes
    assert len(notes[1]) > 0


def test_mixed_generator_counts_successful_llm_notes(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq", _fake_groq_client(content="The workload was unsustainable and I had to leave."),
    )

    driver_frame = pd.DataFrame([
        {"employee_id": 1, "workload_perceived": 0.95, "manager_support_score": 0.15},
        {"employee_id": 2, "workload_perceived": 0.5, "manager_support_score": 0.5},
    ])
    notes, llm_employee_ids = llm_exit_notes.generate_notes_for_employees_mixed(
        driver_frame, [1, 2], np.random.default_rng(1),
    )
    # Employee 2 is neutral (no bad drivers), so it always falls back to the template
    # generator regardless of the LLM path — only employee 1 should count as LLM-written.
    assert llm_employee_ids == {1}
    assert notes[1] == "The workload was unsustainable and I had to leave."


def test_diagnose_endpoint_uses_llm_notes_when_enabled(client, monkeypatch):
    """End-to-end: with the flag+key set and the Groq client mocked, a
    /diagnose run whose forced reorg produces real quits should report
    n_llm_generated > 0 in notes_summary — same graceful "quits are
    stochastic" caveat as test_diagnose_notes_summary_shape_is_always_valid
    in test_diagnose_export.py (usually non-zero, not guaranteed).
    """
    monkeypatch.setenv(llm_exit_notes._FLAG_VAR, "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq", _fake_groq_client(content="I left because the workload became unmanageable."),
    )

    org = client.post("/orgs", json={"name": "Acme", "headcount": 300, "seed": 11}).json()
    dept_id = client.get(f"/orgs/{org['id']}/departments").json()[0]["id"]
    resp = client.post(f"/orgs/{org['id']}/diagnose", json={
        "ticks": 20, "replicates": 1, "seed": 11,
        "events": [{"type": "reorg", "at_tick": 1, "params": {"department_id": dept_id, "delta": 0.45}}],
    })
    assert resp.status_code == 200
    body = resp.json()

    any_notes = [
        r["notes_summary"] for r in body["reports"]
        if r.get("notes_summary") is not None and r["notes_summary"]["n_notes"] > 0
    ]
    if any_notes:
        assert any_notes[0]["n_llm_generated"] > 0
        assert any_notes[0]["n_llm_generated"] <= any_notes[0]["n_notes"]
