"""Optional real-LLM "ask your org" chatbot — behind a flag.

The second LLM integration in this codebase (after
``ml/llm_exit_notes.py``), and the same opt-in shape: off by default,
needs both ``COMPANYSIM_LLM_CHAT=1`` and a credentialed provider to do
anything. Unlike exit notes there's no template fallback — a chat feature
has nothing sensible to degrade to, so a disabled flag or a failed call
surfaces as a plain, honest message instead of a broken page.

The model never invents numbers: it answers only by calling the read-only
tool functions below. Tool calling here is manual, not automatic like the
Gemini SDK this originally used — there's no built-in introspection or
call-execution loop, so this module builds the JSON tool schema from each
function's signature/docstring itself (:func:`_tool_schema`) and runs the
call → execute → feed-result-back loop itself (:func:`ask_org`). The
transcript is kept in OpenAI shape throughout;
``companysim.llm.provider`` translates it for Bedrock, so this loop is
provider-independent.

Every tool is grounded in the exact same DB queries and scoring/diagnosis
logic the rest of the app already uses and already tests
(``scoring_frame.score_current_employees``, ``scoring_frame.build_driver_frame``,
``ml.diagnostics.explain_employee``) — this module adds a natural-language
front end over them, not a new source of truth. One tool,
``run_intervention_scenario``, isn't read-only in the "just queries the DB"
sense — it runs a real forward simulation via ``intervene.compare_intervention``,
the same engine behind the What-if Planner's compare-intervention endpoint
(``routers/at_risk.py``) — but it never *writes* anything back to the org,
so the org itself is never mutated by a chat question.
"""
from __future__ import annotations

import inspect
import json
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, get_args, get_origin

from sqlalchemy.orm import Session

from companysim.api.converters import emp_str_id, org_to_pydantic, team_str_id
from companysim.api.db_models import DepartmentRecord, EmployeeRecord, OrgRecord
from companysim.api.scoring_frame import (
    build_driver_frame,
    load_production_bundle,
    risk_trend_rows,
    score_current_employees,
)
from companysim.intervene import compare_intervention as run_compare_intervention
from companysim.llm import provider
from companysim.llm.usage import FEATURE_CHAT, record_completion
from companysim.ml.diagnostics import explain_employee
from companysim.scenarios.events import ManagerCoaching, RetentionBonus, WorkloadRelief
from companysim.scenarios.scenario import Scenario

_FLAG_VAR = "COMPANYSIM_LLM_CHAT"
_MAX_TOOL_ITERATIONS = 6

_SYSTEM_INSTRUCTION = (
    "You are an HR analytics assistant answering questions about one specific "
    "organization using only the tool functions provided. Always call a tool to "
    "get real data before answering a factual question — never invent numbers, "
    "names, or trends. Use run_intervention_scenario only for genuine 'what if we "
    "did X' or 'how much would Y help' questions, since it runs a real simulation; "
    "use the other, faster tools for anything purely informational. If no "
    "available tool can answer the question, say so plainly instead of guessing. "
    "Keep answers concise (2-5 sentences) and cite concrete figures from the tool "
    "results."
)


def is_chat_enabled() -> bool:
    """True only when the flag is on and the active provider has both its
    SDK and its credentials — see :func:`companysim.llm.provider.is_enabled`.
    """
    return provider.is_enabled(_FLAG_VAR)


@dataclass
class ChatResult:
    reply: str
    tools_used: list[str] = field(default_factory=list)


def _department_name_map(db: Session, org_id: int) -> dict[int, str]:
    return {
        d.id: d.name
        for d in db.query(DepartmentRecord).filter(DepartmentRecord.org_id == org_id).all()
    }


def build_tools(db: Session, org_id: int, calls_made: list[str]) -> list[Callable[..., str]]:
    """Five read-only tool functions scoped to ``org_id`` via closure —
    each function's tool schema is built from its plain parameter types
    and docstring (see :func:`_tool_schema`), so only primitives are
    exposed as parameters (no ``db``/``org_id``/DataFrame). Each appends
    its own name to ``calls_made`` when invoked, so the caller can report
    which tools a given answer actually drew on.
    """
    dept_names = _department_name_map(db, org_id)

    def get_org_overview() -> str:
        """Returns the organization's name, total headcount, and a list of
        departments with their headcounts. Call this first for broad
        "tell me about this org" or "how many people work here" questions.
        Takes no parameters.
        """
        calls_made.append("get_org_overview")
        org = db.get(OrgRecord, org_id)
        employees = db.query(EmployeeRecord).filter(EmployeeRecord.org_id == org_id).all()
        dept_counts: dict[str, int] = {}
        for e in employees:
            name = dept_names.get(e.department_id, str(e.department_id))
            dept_counts[name] = dept_counts.get(name, 0) + 1
        return json.dumps({
            "org_name": org.name if org else None,
            "headcount": len(employees),
            "departments": [{"name": n, "headcount": c} for n, c in sorted(dept_counts.items())],
        })

    def get_top_at_risk_employees(top_k: int = 5, department_name: str | None = None) -> str:
        """Returns the employees with the highest predicted turnover risk,
        ranked highest-risk first. top_k: how many employees to return
        (default 5). department_name: optional, a case-insensitive
        substring to filter to one department (e.g. "eng" matches
        "Engineering") — omit to search the whole org. Use this for
        "who is at risk", "top N at-risk in <department>" questions.
        """
        calls_made.append("get_top_at_risk_employees")
        scored, model_used = score_current_employees(db, org_id)
        if scored.empty:
            return json.dumps({"employees": [], "model_available": model_used})
        scored = scored.copy()
        scored["department_name"] = scored["department_id"].astype(int).map(dept_names)
        if department_name:
            needle = department_name.strip().lower()
            scored = scored[scored["department_name"].str.lower().str.contains(needle, na=False)]
        ranked = scored.sort_values("turnover_probability", ascending=False).head(top_k)
        return json.dumps({
            "model_available": model_used,
            "employees": [
                {
                    "name": row["full_name"],
                    "department": row["department_name"],
                    "risk_tier": row["risk_tier"],
                    "turnover_probability": round(float(row["turnover_probability"]), 3),
                }
                for _, row in ranked.iterrows()
            ],
        })

    def get_department_wellbeing_summary() -> str:
        """Returns, for every department, the mean of each wellbeing driver
        (workload, burnout, stress, manager support, psychological safety,
        financial security, mood, sleep quality, meaning at work, life
        satisfaction — all on a 0-1 scale, higher is not always better;
        e.g. higher workload/burnout/stress is bad, higher manager support
        is good) plus mean predicted turnover risk. Use this for "which
        team has the worst burnout / is struggling most / has low morale"
        questions. Takes no parameters.
        """
        calls_made.append("get_department_wellbeing_summary")
        driver_frame = build_driver_frame(db, org_id)
        if driver_frame.empty:
            return json.dumps({"departments": []})
        scored, _ = score_current_employees(db, org_id)
        risk_by_emp = dict(zip(scored["employee_id"], scored["turnover_probability"], strict=False))
        driver_frame = driver_frame.copy()
        driver_frame["turnover_probability"] = driver_frame["employee_id"].map(risk_by_emp)
        grouped = driver_frame.groupby("department_id").mean(numeric_only=True)
        out = []
        for dept_id, row in grouped.iterrows():
            summary = {"department": dept_names.get(int(dept_id), str(dept_id))}
            for col in row.index:
                if col == "employee_id":
                    continue
                summary[col] = round(float(row[col]), 3)
            out.append(summary)
        out.sort(key=lambda d: d.get("turnover_probability", 0.0), reverse=True)
        return json.dumps({"departments": out})

    def get_employee_risk_drivers(employee_name: str) -> str:
        """Returns why one specific employee is flagged at-risk: their
        top wellbeing drivers ranked by how much they deviate from the
        org average in the direction that raises risk. employee_name: a
        case-insensitive substring match against the employee's full name
        (e.g. "sarah" matches "Sarah Connor"). If zero or multiple
        employees match, returns a message describing the ambiguity
        instead of guessing which one was meant.
        """
        calls_made.append("get_employee_risk_drivers")
        needle = employee_name.strip().lower()
        matches = [
            e for e in db.query(EmployeeRecord).filter(EmployeeRecord.org_id == org_id).all()
            if needle in e.full_name.lower()
        ]
        if not matches:
            return json.dumps({"error": f"No employee matching '{employee_name}' found in this org."})
        if len(matches) > 1:
            names = [m.full_name for m in matches[:10]]
            return json.dumps({
                "error": f"Multiple employees match '{employee_name}': {', '.join(names)}. "
                         "Ask again with a more specific name.",
            })
        emp = matches[0]
        driver_frame = build_driver_frame(db, org_id)
        bundle = load_production_bundle()
        contributions = explain_employee(emp.id, driver_frame, turnover_bundle=bundle)
        return json.dumps({
            "employee_name": emp.full_name,
            "department": dept_names.get(emp.department_id, str(emp.department_id)),
            "top_drivers": [
                {
                    "feature": c.feature,
                    "employee_value": round(c.segment_mean, 3),
                    "org_average": round(c.org_mean, 3),
                }
                for c in contributions
            ] if contributions else [],
            "note": "empty top_drivers means no driver is meaningfully elevated for this person"
                    if not contributions else None,
        })

    def get_risk_trend_summary() -> str:
        """Returns the organization's mean predicted turnover risk for
        every past Simulate/Diagnose run, oldest first — use this for
        "is risk going up or down over time" questions. Takes no
        parameters.
        """
        calls_made.append("get_risk_trend_summary")
        rows = risk_trend_rows(db, org_id)
        return json.dumps({
            "runs": [
                {"computed_at": r["computed_at"], "mean_risk": round(r["mean_risk"], 3)}
                for r in rows
            ],
        })

    def run_intervention_scenario(
        intervention_type: Literal["retention_bonus", "workload_relief", "manager_coaching"],
        top_k: int = 10,
        department_name: str | None = None,
    ) -> str:
        """Runs a real forward simulation comparing "do nothing" against
        one retention intervention targeted at the org's current top-K
        at-risk employees, and returns the predicted number of quits
        avoided and its estimated cost. intervention_type must be exactly
        one of "retention_bonus" (a one-time cash bonus), "workload_relief"
        (reduces workload), or "manager_coaching" (coaches the managers of
        affected teams — has no direct cost). top_k: how many of the
        highest-risk targeted employees to include (default 10).
        department_name: optional case-insensitive substring to restrict
        targeting to one department (e.g. "eng" for Engineering) — omit to
        target org-wide. This runs an actual multi-replicate simulation
        and can take several seconds, so only call it when the user
        explicitly asks a "what if we did X" / "how much would Y help"
        question — use get_top_at_risk_employees or
        get_department_wellbeing_summary instead for purely informational
        questions.
        """
        calls_made.append("run_intervention_scenario")
        if intervention_type not in {"retention_bonus", "workload_relief", "manager_coaching"}:
            return json.dumps({
                "error": f"Unknown intervention_type '{intervention_type}'. Must be one of: "
                         "retention_bonus, workload_relief, manager_coaching.",
            })

        scored, model_used = score_current_employees(db, org_id)
        if scored.empty:
            return json.dumps({"error": "This org has no employees to target."})
        scored = scored.copy()
        scored["department_name"] = scored["department_id"].astype(int).map(dept_names)
        if department_name:
            needle = department_name.strip().lower()
            scored = scored[scored["department_name"].str.lower().str.contains(needle, na=False)]
        if scored.empty:
            return json.dumps({"error": f"No employees found matching department '{department_name}'."})

        ranked = scored.sort_values("turnover_probability", ascending=False).head(top_k)
        top_ids = ranked["employee_id"].astype(int).tolist()
        target_str_ids = tuple(emp_str_id(i) for i in top_ids)

        if intervention_type == "retention_bonus":
            scenario = Scenario(name="chat_bonus", events=[
                RetentionBonus(at_tick=1, employee_ids=target_str_ids, amount_pct=0.15),
            ])
        elif intervention_type == "workload_relief":
            scenario = Scenario(name="chat_workload", events=[
                WorkloadRelief(at_tick=1, employee_ids=target_str_ids, delta=0.20),
            ])
        else:
            team_ids = {
                e.team_id for e in db.query(EmployeeRecord)
                .filter(EmployeeRecord.org_id == org_id, EmployeeRecord.id.in_(top_ids)).all()
            }
            scenario = Scenario(name="chat_coaching", events=[
                ManagerCoaching(at_tick=1, team_id=team_str_id(tid), delta=0.20)
                for tid in team_ids
            ])

        org, hf_df = org_to_pydantic(db, org_id)
        result = run_compare_intervention(
            org, hf_df, scenario,
            target_employee_ids=target_str_ids,
            # Fewer replicates than the What-if Planner's REST endpoint
            # default (15) — this runs inline in a chat turn, not behind a
            # dedicated loading state, so it trades some precision for
            # staying responsive.
            replicates=5, horizon_ticks=12, base_seed=4242,
        )
        return json.dumps({
            "intervention_type": intervention_type,
            "target_employee_count": len(top_ids),
            "department_filter": department_name,
            "model_available": model_used,
            "quits_avoided_p50": round(result.target_quits_avoided_p50, 2),
            "quits_avoided_p05": round(result.target_quits_avoided_p05, 2),
            "quits_avoided_p95": round(result.target_quits_avoided_p95, 2),
            "estimated_cost": round(result.estimated_cost, 2),
        })

    return [
        get_org_overview,
        get_top_at_risk_employees,
        get_department_wellbeing_summary,
        get_employee_risk_drivers,
        get_risk_trend_summary,
        run_intervention_scenario,
    ]


def _json_schema_for_annotation(annotation: object) -> dict[str, object]:
    """Maps a plain Python type annotation to a JSON-schema fragment —
    only what :func:`build_tools`'s parameters actually use
    (str/int/Literal/Optional), not a general-purpose type mapper."""
    origin = get_origin(annotation)
    if origin is Literal:
        return {"type": "string", "enum": list(get_args(annotation))}
    if origin is typing.Union or (origin is not None and origin.__name__ == "UnionType"):
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        return _json_schema_for_annotation(non_none[0]) if non_none else {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    return {"type": "string"}


def _tool_schema(fn: Callable[..., str]) -> dict[str, object]:
    """Builds an OpenAI/Groq-style ``{"type": "function", ...}`` tool
    schema from a plain function's signature and docstring — the piece of
    plumbing that replaces what the Gemini SDK's automatic function
    calling used to do via introspection. The whole docstring becomes the
    tool's description, same convention :func:`build_tools`'s docstrings
    were already written for.
    """
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    properties: dict[str, object] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        properties[name] = _json_schema_for_annotation(hints.get(name, str))
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": inspect.getdoc(fn) or "",
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def ask_org(db: Session, org_id: int, message: str, history: list[dict[str, str]]) -> ChatResult:
    """Answers ``message`` about ``org_id`` using Groq's chat-completions
    API with manual tool calling over :func:`build_tools`. ``history`` is
    a list of ``{"role": "user"|"assistant", "content": str}`` dicts (the
    wire shape of ``ChatMessageIn``) — Groq's API already uses "assistant"
    for the model's own turns, so no role translation is needed here
    (unlike the Gemini version this replaced).

    Loops up to :data:`_MAX_TOOL_ITERATIONS` times: call the model, and if
    it requests tool calls, execute them locally and feed the results back
    as ``role="tool"`` messages, repeating until it returns plain text.

    Raises on any failure (missing/invalid response, network/API error, or
    exceeding the iteration budget without a final answer) — there's no
    non-LLM fallback for a free-form question, so the caller (the chat
    router) is responsible for turning an exception into a friendly
    "temporarily unavailable" reply rather than a 500.
    """
    calls_made: list[str] = []
    tool_fns = build_tools(db, org_id, calls_made)
    tool_map = {fn.__name__: fn for fn in tool_fns}
    tool_schemas = [_tool_schema(fn) for fn in tool_fns]

    messages: list[dict[str, object]] = [{"role": "system", "content": _SYSTEM_INSTRUCTION}]
    for turn in history:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": message})

    for _ in range(_MAX_TOOL_ITERATIONS):
        response = provider.complete(messages, tools=tool_schemas)
        # One record per iteration, not per question: a tool-calling answer
        # makes several round trips and every one of them is billed.
        record_completion(response, feature=FEATURE_CHAT)

        if not response.tool_calls:
            reply = (response.text or "").strip()
            if not reply:
                raise ValueError("The model returned no text")
            return ChatResult(reply=reply, tools_used=calls_made)

        # Re-serialized into the OpenAI shape rather than kept as objects:
        # that shape is this loop's transcript format, and the provider
        # layer translates it for Bedrock on the way back out.
        messages.append({
            "role": "assistant",
            "content": response.text,
            "tool_calls": [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ],
        })
        for tc in response.tool_calls:
            fn = tool_map.get(tc.name)
            if fn is None:
                result = json.dumps({"error": f"Unknown tool '{tc.name}'"})
            else:
                try:
                    result = fn(**tc.arguments)
                except Exception as exc:
                    result = json.dumps({"error": str(exc)})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    raise ValueError("Exceeded max tool-call iterations without a final answer")
