"""Build a :class:`Scenario` from the API's wire-format event list.

Shared by ``routers/simulate.py`` and ``routers/diagnose.py`` — both need
to turn a client's plain-integer-id event list into the engine's
string-id :class:`~companysim.scenarios.events.Event` objects the same way.
"""
from __future__ import annotations

from fastapi import HTTPException

from companysim.api.converters import dept_str_id, emp_str_id, team_str_id
from companysim.api.schemas import ScenarioEventIn
from companysim.scenarios.events import (
    BudgetCut,
    Event,
    Hire,
    Layoff,
    LifeEvent,
    ManagerCoaching,
    PolicyChange,
    Promotion,
    Reorg,
    RetentionBonus,
    Termination,
    Transfer,
    WorkloadRelief,
)
from companysim.scenarios.scenario import Scenario


def build_event(e: ScenarioEventIn) -> Event:
    p = e.params
    try:
        if e.type == "layoff":
            dept = p.get("department_id")
            return Layoff(at_tick=e.at_tick, fraction=p["fraction"],
                          department=dept_str_id(dept) if dept is not None else None)
        if e.type == "hire":
            return Hire(at_tick=e.at_tick, count=p["count"], department=dept_str_id(p["department_id"]))
        if e.type == "promotion":
            return Promotion(at_tick=e.at_tick, count=p["count"], from_level=p["from_level"])
        if e.type == "policy_change":
            dept = p.get("department_id")
            return PolicyChange(at_tick=e.at_tick, delta=p["delta"],
                                department=dept_str_id(dept) if dept is not None else None)
        if e.type == "retention_bonus":
            return RetentionBonus(
                at_tick=e.at_tick,
                employee_ids=tuple(emp_str_id(i) for i in p["employee_ids"]),
                amount_pct=p.get("amount_pct", 0.10),
            )
        if e.type == "workload_relief":
            return WorkloadRelief(
                at_tick=e.at_tick,
                employee_ids=tuple(emp_str_id(i) for i in p["employee_ids"]),
                delta=p.get("delta", 0.15),
            )
        if e.type == "manager_coaching":
            return ManagerCoaching(at_tick=e.at_tick, team_id=team_str_id(p["team_id"]),
                                    delta=p.get("delta", 0.15))
        if e.type == "budget_cut":
            dept = p.get("department_id")
            return BudgetCut(at_tick=e.at_tick, severity=p["severity"],
                             department=dept_str_id(dept) if dept is not None else None)
        if e.type == "reorg":
            dept = p.get("department_id")
            return Reorg(at_tick=e.at_tick, delta=p.get("delta", 0.15),
                        department=dept_str_id(dept) if dept is not None else None)
        if e.type == "termination":
            return Termination(at_tick=e.at_tick, employee_ids=tuple(emp_str_id(i) for i in p["employee_ids"]))
        if e.type == "transfer":
            return Transfer(
                at_tick=e.at_tick,
                employee_ids=tuple(emp_str_id(i) for i in p["employee_ids"]),
                new_team_id=team_str_id(p["new_team_id"]),
                adjustment_dip=p.get("adjustment_dip", 0.08),
            )
        if e.type == "life_event":
            return LifeEvent(
                at_tick=e.at_tick,
                employee_ids=tuple(emp_str_id(i) for i in p["employee_ids"]),
                event_type=p["event_type"],
            )
    except KeyError as exc:
        raise HTTPException(400, f"missing param {exc} for event type '{e.type}'") from exc
    raise HTTPException(400, f"unknown event type '{e.type}'")


def build_scenario(events: list[ScenarioEventIn], name: str = "api_scenario") -> Scenario:
    return Scenario(name=name, events=[build_event(e) for e in events])
