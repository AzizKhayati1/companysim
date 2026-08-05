"""Tests for LLM token accounting.

Two halves, matching the module split:

- ``companysim.llm.usage`` — the DB-agnostic sink. Recording outside a
  ``collect()`` block must be a silent no-op (that's what keeps the CLI and
  the offline pipeline free of it), nesting must not leak, and a response
  with no ``usage`` block must record zeros rather than raise.
- ``companysim.api.llm_usage`` + the endpoint — persistence and the
  total/today/week aggregates.

Plus the property that motivated the whole design: a **failed** LLM call
still burned tokens and must still be billed.
"""
from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.db_models import LlmUsageRecord
from companysim.api.llm_usage import record_llm_calls, usage_summary
from companysim.api.main import app
from companysim.ingest import llm_parser
from companysim.llm.usage import (
    FEATURE_CHAT,
    FEATURE_INGEST,
    LlmCall,
    collect,
    record,
    record_response,
)


def _usage_response(prompt=100, completion=40, total=140, content='{"ok": true}'):
    message = types.SimpleNamespace(content=content, tool_calls=None)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=message)],
        usage=types.SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
        ),
    )


def _fake_groq(response=None, error: Exception | None = None):
    def _factory(api_key):
        def create(**kwargs):
            if error is not None:
                raise error
            return response
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)),
        )
    return _factory


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
def _clear_flags(monkeypatch):
    monkeypatch.delenv(llm_parser._FLAG_VAR, raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


# ---- the sink -----------------------------------------------------------


def test_recording_outside_a_collect_block_is_a_noop():
    """What keeps ml/ and ingest/ usable with no webapp around them."""
    record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=10))  # must not raise


def test_collect_captures_calls_made_inside_it():
    with collect() as calls:
        record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=10))
        record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=5))
    assert [c.total_tokens for c in calls] == [10, 5]


def test_collect_does_not_leak_after_the_block():
    with collect() as first:
        record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=1))
    record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=99))
    assert len(first) == 1


def test_nested_collect_blocks_do_not_double_count():
    with collect() as outer:
        record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=1))
        with collect() as inner:
            record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=2))
        record(LlmCall(feature=FEATURE_CHAT, model="m", total_tokens=3))
    assert [c.total_tokens for c in inner] == [2]
    assert [c.total_tokens for c in outer] == [1, 3]


def test_record_response_reads_the_usage_block():
    with collect() as calls:
        record_response(_usage_response(120, 30, 150), feature=FEATURE_INGEST, model="llama")
    assert (calls[0].prompt_tokens, calls[0].completion_tokens, calls[0].total_tokens) == (120, 30, 150)
    assert calls[0].feature == FEATURE_INGEST


def test_record_response_tolerates_a_response_with_no_usage():
    """A token counter must never be why a working feature breaks."""
    bare = types.SimpleNamespace(choices=[])
    with collect() as calls:
        record_response(bare, feature=FEATURE_CHAT, model="llama")
    assert calls[0].total_tokens == 0
    assert calls[0].feature == FEATURE_CHAT  # the call still happened


# ---- persistence + aggregates ------------------------------------------


def test_record_llm_calls_is_a_noop_on_an_empty_list(db_session_factory):
    db = db_session_factory()
    assert record_llm_calls(db, []) == 0
    assert db.query(LlmUsageRecord).count() == 0


def test_usage_summary_splits_today_week_and_all_time(db_session_factory):
    db = db_session_factory()
    now = datetime.now(timezone.utc)
    db.add_all([
        LlmUsageRecord(feature=FEATURE_CHAT, model="m", prompt_tokens=10,
                       completion_tokens=5, total_tokens=15, created_at=now),
        LlmUsageRecord(feature=FEATURE_INGEST, model="m", prompt_tokens=20,
                       completion_tokens=10, total_tokens=30,
                       created_at=now - timedelta(days=3)),
        LlmUsageRecord(feature=FEATURE_INGEST, model="m", prompt_tokens=40,
                       completion_tokens=20, total_tokens=60,
                       created_at=now - timedelta(days=30)),
    ])
    db.commit()

    s = usage_summary(db)
    assert s["all_time"]["total_tokens"] == 105
    assert s["all_time"]["requests"] == 3
    assert s["today"]["total_tokens"] == 15
    assert s["week"]["total_tokens"] == 45      # today + 3 days ago, not the 30-day-old row
    assert s["all_time"]["prompt_tokens"] == 70
    # Descending by tokens: ingest (90) before chat (15).
    assert [f["feature"] for f in s["by_feature"]] == [FEATURE_INGEST, FEATURE_CHAT]


def test_usage_summary_is_zero_on_an_empty_table(db_session_factory):
    s = usage_summary(db_session_factory())
    assert s["all_time"] == {
        "requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    }
    assert s["by_feature"] == []
    assert s["recent"] == []


def test_recent_is_newest_first_and_capped(db_session_factory):
    from companysim.api.llm_usage import RECENT_LIMIT

    db = db_session_factory()
    now = datetime.now(timezone.utc)
    db.add_all([
        LlmUsageRecord(feature=FEATURE_CHAT, model="m", total_tokens=i,
                       created_at=now - timedelta(minutes=i))
        for i in range(RECENT_LIMIT + 5)
    ])
    db.commit()

    recent = usage_summary(db)["recent"]
    assert len(recent) == RECENT_LIMIT
    assert [r["total_tokens"] for r in recent] == list(range(RECENT_LIMIT))


def test_usage_endpoint_shape(client):
    body = client.get("/llm/usage").json()
    assert set(body) == {"all_time", "today", "week", "by_feature", "recent"}
    assert body["all_time"]["total_tokens"] == 0


# ---- end-to-end through a real feature ---------------------------------


def _make_org(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 7}).json()
    return org, client.get(f"/orgs/{org['id']}/employees").json()[0]


def _enable(monkeypatch):
    pytest.importorskip("groq", reason="groq extra not installed")
    monkeypatch.setenv(llm_parser._FLAG_VAR, "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")


def test_document_extraction_records_its_tokens(client, monkeypatch, db_session_factory):
    _enable(monkeypatch)
    org, employee = _make_org(client)
    monkeypatch.setattr("groq.Groq", _fake_groq(_usage_response(
        prompt=310, completion=45, total=355,
        content=json.dumps({
            "employee_email": employee["email"],
            "review_period_end": "2025-12-31", "rating": 4.0, "summary_text": "",
        }),
    )))
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("r.txt", b"a review", "text/plain")},
        data={"kind": "performance_review"},
    ).json()
    client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    db = db_session_factory()
    row = db.query(LlmUsageRecord).one()
    assert (row.feature, row.total_tokens, row.org_id) == (FEATURE_INGEST, 355, org["id"])

    body = client.get("/llm/usage").json()
    assert body["all_time"]["total_tokens"] == 355
    assert body["today"]["total_tokens"] == 355


def test_a_failed_extraction_still_bills_its_tokens(client, monkeypatch, db_session_factory):
    """The property the whole design exists for: a call that returned
    unusable JSON still cost money. Billing only successes under-reports
    exactly when the number matters."""
    _enable(monkeypatch)
    org, _ = _make_org(client)
    monkeypatch.setattr("groq.Groq", _fake_groq(_usage_response(
        prompt=200, completion=12, total=212, content="not json at all",
    )))
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("r.txt", b"a review", "text/plain")},
        data={"kind": "performance_review"},
    ).json()
    resp = client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract").json()

    assert resp["document"]["extraction_status"] == "needs_review"  # extraction failed
    db = db_session_factory()
    assert db.query(LlmUsageRecord).one().total_tokens == 212       # tokens still billed


def test_disabled_feature_records_nothing(client, db_session_factory):
    org, _ = _make_org(client)
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("r.txt", b"a review", "text/plain")},
        data={"kind": "performance_review"},
    ).json()
    client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    db = db_session_factory()
    assert db.query(LlmUsageRecord).count() == 0


def test_roster_extraction_records_nothing(client, db_session_factory):
    """The deterministic path makes no requests, so it must cost nothing."""
    org, employee = _make_org(client)
    csv_bytes = f"email,level\n{employee['email']},M3\n".encode()
    doc = client.post(
        f"/orgs/{org['id']}/documents",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        data={"kind": "roster"},
    ).json()
    client.post(f"/orgs/{org['id']}/documents/{doc['id']}/extract")

    db = db_session_factory()
    assert db.query(LlmUsageRecord).count() == 0
