"""Tests for the "ask your org" chatbot.

Direct tool-closure tests (no Groq involved — the real logic to verify
is the DB queries/filters, not the model's behavior), plus a handful of
router-level tests mocking the ``groq.Groq`` boundary, same structure as
``test_llm_exit_notes.py``.
"""
from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from companysim.api import db_models  # noqa: F401  (register models on Base)
from companysim.api.database import Base, get_db
from companysim.api.main import app
from companysim.api.org_chat import build_tools, is_chat_enabled

pytest.importorskip(
    "groq",
    reason="groq (the optional 'llm' extra) is not installed — "
    "these tests exercise the mocked-out Groq boundary and need the "
    "package importable to patch it, even though no real network calls happen.",
)


def _fake_groq_client(content: str | None = None, error: Exception | None = None):
    """A fake ``groq.Groq``-shaped class whose single-turn
    ``chat.completions.create(...)`` either raises ``error`` or returns a
    plain-text final answer with no tool calls."""
    def _client_factory(api_key):
        def create(**kwargs):
            if error is not None:
                raise error
            message = types.SimpleNamespace(content=content, tool_calls=None)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    return _client_factory


def _fake_groq_tool_call_then_final(tool_name: str, tool_args: dict | None, final_content: str):
    """A fake Groq client that first requests a tool call, then — once
    :func:`org_chat.ask_org`'s loop feeds back the executed tool's real
    result — returns a final text answer. Mirrors the real two-round-trip
    shape the manual tool-calling loop handles."""
    call_count = {"n": 0}

    def _client_factory(api_key):
        def create(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                tool_call = types.SimpleNamespace(
                    id="call_1",
                    function=types.SimpleNamespace(name=tool_name, arguments=json.dumps(tool_args)),
                )
                message = types.SimpleNamespace(content=None, tool_calls=[tool_call])
            else:
                message = types.SimpleNamespace(content=final_content, tool_calls=None)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    return _client_factory


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("COMPANYSIM_LLM_CHAT", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Pin the provider: these fixtures stub the Groq SDK, so a machine with
    # COMPANYSIM_LLM_PROVIDER=bedrock exported would otherwise route them
    # down the Bedrock branch and fail for a reason unrelated to the test.
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "groq")


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


def _tool(db, org_id, name):
    calls: list[str] = []
    tools = build_tools(db, org_id, calls)
    fn = next(t for t in tools if t.__name__ == name)
    return fn, calls


def test_is_chat_enabled_false_by_default():
    assert is_chat_enabled() is False


def test_is_chat_enabled_requires_flag_and_key(monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    assert is_chat_enabled() is False
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    assert is_chat_enabled() is True


def test_get_org_overview_reports_headcount_and_departments(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 30}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_org_overview")
    overview = json.loads(fn())

    assert overview["org_name"] == "Acme"
    assert overview["headcount"] == 60
    assert {d["name"] for d in overview["departments"]} == {d["name"] for d in depts}
    assert sum(d["headcount"] for d in overview["departments"]) == 60


def test_get_top_at_risk_employees_respects_department_filter(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 31}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_top_at_risk_employees")
    result = json.loads(fn(top_k=5, department_name="eng"))

    assert len(result["employees"]) > 0
    assert len(result["employees"]) <= 5
    for emp in result["employees"]:
        assert emp["department"] == "Engineering"


def test_get_top_at_risk_employees_ranked_descending(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 32}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_top_at_risk_employees")
    result = json.loads(fn(top_k=10))

    probs = [e["turnover_probability"] for e in result["employees"]]
    assert probs == sorted(probs, reverse=True)


def test_get_department_wellbeing_summary_covers_every_department(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 33}).json()
    depts = client.get(f"/orgs/{org['id']}/departments").json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_department_wellbeing_summary")
    result = json.loads(fn())

    assert {d["department"] for d in result["departments"]} == {d["name"] for d in depts}
    for d in result["departments"]:
        assert "burnout_exhaustion" in d
        assert "turnover_probability" in d


def test_get_employee_risk_drivers_unique_match(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 34}).json()
    employees = client.get(f"/orgs/{org['id']}/employees").json()
    target = employees[0]

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_employee_risk_drivers")
    result = json.loads(fn(employee_name=target["full_name"]))

    assert result["employee_name"] == target["full_name"]
    assert "top_drivers" in result


def test_get_employee_risk_drivers_no_match(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 35}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_employee_risk_drivers")
    result = json.loads(fn(employee_name="Zzznomatch"))

    assert "error" in result


def test_get_employee_risk_drivers_ambiguous_match(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 60, "seed": 36}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_employee_risk_drivers")
    # "a" is common enough to match multiple full names in a 60-person org.
    result = json.loads(fn(employee_name="a"))

    assert "error" in result
    assert "multiple employees match" in result["error"].lower()


def test_get_risk_trend_summary_orders_runs_oldest_first(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 15, "seed": 37}).json()
    for seed in (50, 51, 52):
        resp = client.post(
            f"/orgs/{org['id']}/simulate", json={"ticks": 3, "replicates": 1, "seed": seed},
        )
        assert resp.status_code == 200

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "get_risk_trend_summary")
    result = json.loads(fn())

    timestamps = [r["computed_at"] for r in result["runs"]]
    assert timestamps == sorted(timestamps)
    assert len(result["runs"]) == 3


def test_run_intervention_scenario_retention_bonus_returns_valid_result(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 60}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "run_intervention_scenario")
    result = json.loads(fn(intervention_type="retention_bonus", top_k=5))

    assert result["intervention_type"] == "retention_bonus"
    assert result["target_employee_count"] == 5
    assert "quits_avoided_p50" in result
    assert "estimated_cost" in result


def test_run_intervention_scenario_respects_department_filter(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 61}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "run_intervention_scenario")
    result = json.loads(fn(intervention_type="workload_relief", top_k=5, department_name="eng"))

    assert result["department_filter"] == "eng"
    assert result["target_employee_count"] <= 5


def test_run_intervention_scenario_manager_coaching(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 62}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "run_intervention_scenario")
    result = json.loads(fn(intervention_type="manager_coaching", top_k=8))

    assert result["intervention_type"] == "manager_coaching"
    assert "quits_avoided_p50" in result


def test_run_intervention_scenario_unknown_type_returns_error(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 20, "seed": 63}).json()

    db = db_session_factory()
    fn, _ = _tool(db, org["id"], "run_intervention_scenario")
    result = json.loads(fn(intervention_type="not_a_real_type", top_k=5))

    assert "error" in result


def test_calls_made_tracks_which_tool_ran(client, db_session_factory):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 38}).json()

    db = db_session_factory()
    fn, calls = _tool(db, org["id"], "get_org_overview")
    fn()

    assert calls == ["get_org_overview"]


def test_chat_endpoint_disabled_by_default(client):
    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 39}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_available"] is False
    assert body["tools_used"] == []


def test_chat_endpoint_missing_org_is_404(client):
    resp = client.post("/orgs/999999/chat", json={"message": "hello"})
    assert resp.status_code == 404


def test_chat_endpoint_with_mocked_groq(client, monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq", _fake_groq_client(content="Engineering has the highest average burnout at 0.7."),
    )

    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 40}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={
        "message": "which team has the worst burnout?",
        "history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello! ask me about this org."},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_available"] is True
    assert body["reply"] == "Engineering has the highest average burnout at 0.7."


def test_chat_endpoint_gracefully_handles_groq_failure(client, monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr("groq.Groq", _fake_groq_client(error=RuntimeError("simulated API failure")))

    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 41}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_available"] is True
    assert "temporarily unavailable" in body["reply"].lower()


def test_chat_endpoint_empty_reply_is_treated_as_failure(client, monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr("groq.Groq", _fake_groq_client(content=""))

    org = client.post("/orgs", json={"name": "Acme", "headcount": 10, "seed": 42}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert "temporarily unavailable" in body["reply"].lower()


def test_ask_org_executes_real_tool_call_from_mocked_groq_response(client, monkeypatch):
    """Unlike the Gemini SDK this replaced, Groq's tool calling doesn't
    execute functions for us — org_chat.ask_org's manual loop does. This
    verifies that loop actually dispatches to a real tool (not a fake),
    parses the JSON arguments, and feeds the real result back correctly.
    """
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq",
        _fake_groq_tool_call_then_final(
            "get_org_overview", {}, "This org has 15 employees across several departments.",
        ),
    )

    org = client.post("/orgs", json={"name": "Acme", "headcount": 15, "seed": 70}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={"message": "tell me about this org"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_available"] is True
    assert body["reply"] == "This org has 15 employees across several departments."
    assert body["tools_used"] == ["get_org_overview"]


def test_ask_org_handles_null_arguments_for_a_parameterless_tool(client, monkeypatch):
    """Regression test: against a real Groq key, a parameterless tool
    call sometimes comes back with arguments=="null" (the JSON literal,
    not "{}"), which json.loads()'s to Python None — fn(**None) used to
    crash the whole exchange. tool_args=None here reproduces that exact
    "null" wire format via json.dumps(None)."""
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq",
        _fake_groq_tool_call_then_final(
            "get_org_overview", None, "This org has 15 employees.",
        ),
    )

    org = client.post("/orgs", json={"name": "Acme", "headcount": 15, "seed": 72}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={"message": "tell me about this org"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_available"] is True
    assert body["reply"] == "This org has 15 employees."
    assert body["tools_used"] == ["get_org_overview"]


def test_ask_org_passes_tool_call_arguments_through_correctly(client, monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_CHAT", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(
        "groq.Groq",
        _fake_groq_tool_call_then_final(
            "get_top_at_risk_employees", {"top_k": 2, "department_name": "eng"},
            "The two most at-risk people in Engineering are listed above.",
        ),
    )

    org = client.post("/orgs", json={"name": "Acme", "headcount": 40, "seed": 71}).json()
    resp = client.post(f"/orgs/{org['id']}/chat", json={"message": "top 2 at risk in engineering"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tools_used"] == ["get_top_at_risk_employees"]
    assert body["reply"] == "The two most at-risk people in Engineering are listed above."
