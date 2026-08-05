"""Tests for the per-note exit-note persistence feature:

- A Diagnose run whose forced reorg produces real quits records one
  ``ExitNoteRecord`` row per generated note, with per-note sentiment/theme
  and correct per-employee LLM attribution.
- No quits recorded during a run means zero rows.
- Deleting a run leaves note rows intact (lineage-only FK, same precedent
  as ``EmployeeRiskSnapshot.run_id`` — see ``db_models.ExitNoteRecord``).
- Deleting an org cascades and removes its note rows.
- ``GET /orgs/{id}/exit-notes/insights`` returns correctly shaped,
  correctly ordered aggregates, and an empty response for an org with no
  notes yet.
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import ExitNoteRecord
from companysim.api.exit_note_records import PendingNoteRecord, record_exit_notes
from companysim.api.main import app
from companysim.ml import llm_exit_notes


def _fake_groq_client(content: str | None = None, error: Exception | None = None):
    def _client_factory(api_key):
        def create(**kwargs):
            if error is not None:
                raise error
            message = types.SimpleNamespace(content=content, tool_calls=None)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)),
        )
    return _client_factory


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


@pytest.fixture(autouse=True)
def _clear_llm_flag(monkeypatch):
    monkeypatch.delenv(llm_exit_notes._FLAG_VAR, raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Pin the provider: these fixtures stub the Groq SDK, so a machine with
    # COMPANYSIM_LLM_PROVIDER=bedrock exported would otherwise route them
    # down the Bedrock branch and fail for a reason unrelated to the test.
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "groq")


def _forced_quit_request(dept_id: int) -> dict:
    """Same recipe as test_diagnose_export.py/test_llm_exit_notes.py — a
    reorg shock big enough to reliably force real quits in the diagnosed
    segment (headcount=300, delta=0.45), though quits are technically
    stochastic."""
    return {
        "ticks": 20, "replicates": 1, "seed": 11,
        "events": [{"type": "reorg", "at_tick": 1,
                    "params": {"department_id": dept_id, "delta": 0.45}}],
    }


def _make_org_and_first_dept(client) -> tuple[dict, int]:
    org = client.post("/orgs", json={"name": "Acme", "headcount": 300, "seed": 11}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()
    return org, depts[0]["id"]


def test_diagnose_with_forced_quits_records_one_row_per_note(client, db_session_factory):
    org, dept_id = _make_org_and_first_dept(client)
    resp = client.post(f"/orgs/{org['id']}/diagnose", json=_forced_quit_request(dept_id))
    assert resp.status_code == 200
    body = resp.json()

    total_notes = sum(
        r["notes_summary"]["n_notes"] for r in body["reports"] if r.get("notes_summary")
    )
    db = db_session_factory()
    rows = db.query(ExitNoteRecord).filter_by(org_id=org["id"]).all()
    assert len(rows) == total_notes
    if total_notes > 0:
        assert all(r.employee_id is not None for r in rows)
        assert all(-1.0 <= r.sentiment <= 1.0 for r in rows)
        assert all(r.is_backfilled is False for r in rows)


def test_no_quits_means_zero_note_rows(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 4}).json()
    resp = client.post(f"/orgs/{org['id']}/diagnose", json={"ticks": 8, "replicates": 1, "seed": 4})
    assert resp.status_code == 200

    db = db_session_factory()
    assert db.query(ExitNoteRecord).filter_by(org_id=org["id"]).count() == 0


def test_llm_attribution_is_per_employee_not_a_flat_count(client, monkeypatch, db_session_factory):
    """The whole point of the return-contract change in
    llm_exit_notes.generate_notes_for_employees_mixed: is_llm_generated
    must be set correctly per row, not just aggregated as a count."""
    monkeypatch.setenv(llm_exit_notes._FLAG_VAR, "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq",
        _fake_groq_client(content="The workload was unsustainable and I had to leave."),
    )
    pytest.importorskip("groq", reason="groq extra not installed")

    org, dept_id = _make_org_and_first_dept(client)
    resp = client.post(f"/orgs/{org['id']}/diagnose", json=_forced_quit_request(dept_id))
    assert resp.status_code == 200

    db = db_session_factory()
    rows = db.query(ExitNoteRecord).filter_by(org_id=org["id"]).all()
    if rows:
        # Every note came back from the (mocked) LLM successfully, so every
        # row should be flagged LLM-generated, and its text should match
        # the mocked response — not silently fallen back to the template.
        assert all(r.is_llm_generated for r in rows)
        assert all(r.text == "The workload was unsustainable and I had to leave." for r in rows)


def test_multi_theme_note_round_trips_through_comma_joined_column(db_session_factory):
    db = db_session_factory()
    record_exit_notes(db, org_id=1, run_id=1, records=[
        PendingNoteRecord(
            employee_id=42, text="burned out and unsupported",
            sentiment=-0.5, themes=["burnout", "manager_support"], is_llm_generated=False,
        ),
    ])
    row = db.query(ExitNoteRecord).filter_by(org_id=1).one()
    assert set(row.themes.split(",")) == {"burnout", "manager_support"}


def test_record_exit_notes_noop_on_empty_list(db_session_factory):
    db = db_session_factory()
    record_exit_notes(db, org_id=1, run_id=1, records=[])
    assert db.query(ExitNoteRecord).count() == 0


def test_deleting_run_leaves_exit_note_records_intact(client, db_session_factory):
    org, dept_id = _make_org_and_first_dept(client)
    resp = client.post(f"/orgs/{org['id']}/diagnose", json=_forced_quit_request(dept_id))
    assert resp.status_code == 200

    db = db_session_factory()
    n_before = db.query(ExitNoteRecord).filter_by(org_id=org["id"]).count()
    if n_before == 0:
        pytest.skip("stochastic scenario produced no quits this run — nothing to verify")

    runs = client.get(f"/orgs/{org['id']}/runs").json()
    run_id = runs[0]["id"]
    del_resp = client.delete(f"/orgs/{org['id']}/runs/{run_id}")
    assert del_resp.status_code == 204

    db2 = db_session_factory()
    assert db2.query(ExitNoteRecord).filter_by(org_id=org["id"]).count() == n_before


def test_deleting_org_cascades_exit_note_records(client, db_session_factory):
    org, dept_id = _make_org_and_first_dept(client)
    client.post(f"/orgs/{org['id']}/diagnose", json=_forced_quit_request(dept_id))

    del_resp = client.delete(f"/orgs/{org['id']}")
    assert del_resp.status_code == 204

    db = db_session_factory()
    assert db.query(ExitNoteRecord).filter_by(org_id=org["id"]).count() == 0


def test_insights_endpoint_empty_for_org_with_no_notes(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 1}).json()
    resp = client.get(f"/orgs/{org['id']}/exit-notes/insights")
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_notes_total"] == 0
    assert body["mean_sentiment_overall"] == 0.0
    assert body["theme_frequency"] == []
    assert body["sentiment_trend"] == []
    assert body["recent_quotes"] == []


def test_insights_endpoint_shape_and_ordering(client, db_session_factory):
    org, dept_id = _make_org_and_first_dept(client)
    for seed_offset in range(2):
        req = _forced_quit_request(dept_id)
        req["seed"] = 11 + seed_offset
        client.post(f"/orgs/{org['id']}/diagnose", json=req)

    db = db_session_factory()
    n_total = db.query(ExitNoteRecord).filter_by(org_id=org["id"]).count()
    if n_total == 0:
        pytest.skip("stochastic scenario produced no quits across either run")

    body = client.get(f"/orgs/{org['id']}/exit-notes/insights").json()
    assert body["n_notes_total"] == n_total

    counts = [t["count"] for t in body["theme_frequency"]]
    assert counts == sorted(counts, reverse=True)

    sentiment_run_ids = [p["run_id"] for p in body["sentiment_trend"]]
    assert sentiment_run_ids == sorted(sentiment_run_ids)
    for point in body["sentiment_trend"]:
        assert -1.0 <= point["mean_sentiment"] <= 1.0

    quote_times = [q["generated_at"] for q in body["recent_quotes"]]
    assert quote_times == sorted(quote_times, reverse=True)
    for q in body["recent_quotes"]:
        assert q["is_backfilled"] is False
        assert isinstance(q["themes"], list)
