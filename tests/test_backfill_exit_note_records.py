"""Tests for scripts/backfill_exit_note_records.py — recovering
ExitNoteRecord rows from historical diagnose runs' saved response_json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base
from companysim.api.db_models import ExitNoteRecord, OrgRecord, RunRecord
from companysim.ml.exit_notes import analyze_note
from scripts.backfill_exit_note_records import backfill_exit_notes


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()


def _diagnose_response_json(*, sample_quotes: list[str], n_notes: int, n_llm_generated: int) -> str:
    return json.dumps({
        "model_available": True,
        "problems_detected": 1,
        "reports": [{
            "problem": {"tick": 5, "metric": "quits_this_tick", "description": "x", "severity": 0.5},
            "drivers": [],
            "recommendation": {
                "event_type": "manager_coaching", "rationale": "x",
                "target_department": None, "target_team": None,
                "target_employee_ids": [], "suggested_params": {},
            },
            "explanation": "x",
            "notes_summary": {
                "n_notes": n_notes, "mean_sentiment": -0.2,
                "top_themes": ["burnout"], "sample_quotes": sample_quotes,
                "n_llm_generated": n_llm_generated,
            },
        }],
    })


def _make_org_and_run(db, *, sample_quotes, n_notes, n_llm_generated) -> RunRecord:
    org = OrgRecord(name="Acme", seed=1, created_at=datetime.now(timezone.utc))
    db.add(org)
    db.flush()
    run = RunRecord(
        org_id=org.id, run_type="diagnose", created_at=datetime.now(timezone.utc),
        summary="1 problem(s) detected", request_json="{}",
        response_json=_diagnose_response_json(
            sample_quotes=sample_quotes, n_notes=n_notes, n_llm_generated=n_llm_generated,
        ),
    )
    db.add(run)
    db.commit()
    return run


def test_recovers_sample_quotes_as_backfilled_rows(db_session):
    quotes = ["I was burned out and unsupported.", "The workload was unsustainable."]
    _make_org_and_run(db_session, sample_quotes=quotes, n_notes=2, n_llm_generated=0)

    stats = backfill_exit_notes(db_session)
    assert stats == {"runs_processed": 1, "rows_inserted": 2}

    rows = db_session.query(ExitNoteRecord).order_by(ExitNoteRecord.id).all()
    assert len(rows) == 2
    assert {r.text for r in rows} == set(quotes)
    assert all(r.employee_id is None for r in rows)
    assert all(r.is_backfilled is True for r in rows)


def test_recovered_sentiment_and_themes_match_direct_analysis(db_session):
    text = "I was burned out and unsupported by my manager."
    _make_org_and_run(db_session, sample_quotes=[text], n_notes=1, n_llm_generated=0)

    backfill_exit_notes(db_session)

    row = db_session.query(ExitNoteRecord).one()
    expected_sentiment, expected_themes = analyze_note(text)
    assert row.sentiment == expected_sentiment
    assert set(row.themes.split(",")) == set(expected_themes)


def test_is_llm_generated_true_only_when_every_note_in_report_was_llm(db_session):
    # n_llm_generated == n_notes -> provably every note was LLM-written.
    _make_org_and_run(
        db_session, sample_quotes=["Left due to workload."], n_notes=1, n_llm_generated=1,
    )
    backfill_exit_notes(db_session)
    row = db_session.query(ExitNoteRecord).one()
    assert row.is_llm_generated is True


def test_is_llm_generated_false_when_ambiguous_mix(db_session):
    # n_llm_generated (1) < n_notes (3) -> can't tell which of the 2
    # sampled quotes were LLM vs. template, so the safe default is False.
    _make_org_and_run(
        db_session,
        sample_quotes=["Left due to workload.", "Left due to burnout."],
        n_notes=3, n_llm_generated=1,
    )
    backfill_exit_notes(db_session)
    rows = db_session.query(ExitNoteRecord).all()
    assert all(r.is_llm_generated is False for r in rows)


def test_no_sample_quotes_produces_no_rows(db_session):
    _make_org_and_run(db_session, sample_quotes=[], n_notes=0, n_llm_generated=0)
    stats = backfill_exit_notes(db_session)
    assert stats == {"runs_processed": 0, "rows_inserted": 0}
    assert db_session.query(ExitNoteRecord).count() == 0


def test_rerunning_is_idempotent(db_session):
    _make_org_and_run(
        db_session, sample_quotes=["Left due to workload."], n_notes=1, n_llm_generated=0,
    )
    first = backfill_exit_notes(db_session)
    assert first["rows_inserted"] == 1

    second = backfill_exit_notes(db_session)
    assert second == {"runs_processed": 0, "rows_inserted": 0}
    assert db_session.query(ExitNoteRecord).count() == 1


def test_only_backfills_runs_not_already_backfilled(db_session):
    """A run that already has a real-time (is_backfilled=False) row from
    the live recording path should still be eligible for backfill of its
    OWN historical sample quotes — the idempotency guard keys off
    is_backfilled=True rows specifically, not "any row for this run"."""
    run = _make_org_and_run(
        db_session, sample_quotes=["Left due to workload."], n_notes=1, n_llm_generated=0,
    )
    db_session.add(ExitNoteRecord(
        org_id=run.org_id, run_id=run.id, employee_id=7, text="real-time note",
        sentiment=0.0, themes="", is_llm_generated=False, is_backfilled=False,
    ))
    db_session.commit()

    stats = backfill_exit_notes(db_session)
    assert stats == {"runs_processed": 1, "rows_inserted": 1}
    assert db_session.query(ExitNoteRecord).filter_by(run_id=run.id).count() == 2
