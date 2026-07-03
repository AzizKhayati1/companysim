"""Top-level simulation.

Wires a generated :class:`Organization` into agent wrappers and runs a
discrete-time loop. Each ``step()`` first applies any scenario events due
this tick, recomputes team climates, then advances every employee. Metrics
collected per tick get flattened into a DataFrame at the end.

The scheduler is deliberately simple — random activation over agents. When
we move to Mesa the interface stays; only this file changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from companysim.agents.employee import EmployeeAgent, TickOutcome
from companysim.agents.team import TeamAgent
from companysim.data.human_factors import HumanProfile
from companysim.data.schemas import Organization
from companysim.scenarios.scenario import BASELINE, Scenario


@dataclass
class SimulationSnapshot:
    tick: int
    active_headcount: int
    quits_this_tick: int
    hires_this_tick: int
    mean_productivity: float
    mean_engagement: float
    mean_collaboration: float
    mean_turnover_risk: float
    # Human-factor aggregates — the sim's operational read on company
    # wellbeing. High burnout / low mood are the early warning signals
    # policymakers care about before productivity and turnover move.
    mean_burnout: float
    mean_stress: float
    mean_sleep_quality: float
    mean_mood: float
    mean_psychological_safety: float
    burnout_rate: float  # fraction of workforce with burnout_exhaustion >= 0.7


@dataclass
class OrganizationModel:
    organization: Organization
    seed: int = 0
    scenario: Scenario = field(default_factory=lambda: BASELINE)
    # Optional day-0 wellbeing snapshot (the ``human_factors`` table from
    # DatasetBuilder/generate_human_factors). When provided, each agent's
    # HumanProfile is built from its matching row instead of sampled
    # independently — this is what makes a dataset export and a forward
    # simulation of "the same" org describe one coherent population rather
    # than two unrelated synthetic populations that happen to share ids.
    human_factors: pd.DataFrame | None = None

    _rng: np.random.Generator = field(init=False)
    _employees: dict[str, EmployeeAgent] = field(init=False, default_factory=dict)
    _teams: dict[str, TeamAgent] = field(init=False, default_factory=dict)
    _tick: int = field(init=False, default=0)
    _snapshots: list[SimulationSnapshot] = field(init=False, default_factory=list)
    _outcomes: list[TickOutcome] = field(init=False, default_factory=list)
    _next_emp_index: int = field(init=False, default=0)
    _new_hires_this_tick: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        hf_by_id = (
            self.human_factors.set_index("employee_id")
            if self.human_factors is not None else None
        )
        # Each employee gets its own sub-RNG so a change in one team can't
        # ripple through the noise stream of another — critical for Monte
        # Carlo reproducibility later.
        for emp in self.organization.employees:
            sub_rng = np.random.default_rng(self._rng.integers(0, 2**32 - 1))
            profile = (
                HumanProfile.from_row(hf_by_id.loc[emp.id])
                if hf_by_id is not None else None
            )
            self._employees[emp.id] = EmployeeAgent(
                record=emp, _rng=sub_rng, profile=profile,
            )

        for team in self.organization.teams:
            members = [self._employees[mid] for mid in team.member_ids]
            self._teams[team.id] = TeamAgent(record=team, members=members)

        self._next_emp_index = len(self.organization.employees)

    # ---- lifecycle ----

    @property
    def tick(self) -> int:
        return self._tick

    @property
    def employees(self) -> dict[str, EmployeeAgent]:
        return self._employees

    @property
    def teams(self) -> dict[str, TeamAgent]:
        return self._teams

    @property
    def rng(self) -> np.random.Generator:
        return self._rng

    def step(self) -> SimulationSnapshot:
        # 0. Fire scenario events for this tick — mutations happen first
        #    so their effects show up in this tick's snapshot.
        self._new_hires_this_tick = 0
        for event in self.scenario.events_at(self._tick):
            event.apply(self)

        # 1. Recompute team climates using post-event, pre-step state.
        for team in self._teams.values():
            team.compute_climate()

        # 2. Random activation over employees to avoid systematic ordering bias.
        emp_order = list(self._employees.values())
        self._rng.shuffle(emp_order)

        quits = 0
        prods, engs, colls, risks = [], [], [], []
        burnouts, stresses, sleeps, moods, safeties = [], [], [], [], []
        for agent in emp_order:
            was_active = agent.active
            team = self._teams[agent.record.team_id]
            outcome = agent.step(team.climate, team.psychological_safety)
            self._outcomes.append(outcome)
            # EmployeeAgent.step() reports quit=True on every call once
            # inactive (not just the tick it happened) — only count the
            # active-to-inactive transition as "this tick"'s quit.
            if was_active and not agent.active:
                quits += 1
            if agent.active:
                prods.append(outcome.productivity)
                engs.append(outcome.engagement)
                colls.append(outcome.collaboration)
                risks.append(outcome.turnover_risk)
                burnouts.append(outcome.burnout)
                stresses.append(outcome.stress)
                sleeps.append(outcome.sleep_quality)
                moods.append(outcome.mood)
                if agent.profile is not None:
                    safeties.append(agent.profile.psychological_safety)

        active = sum(1 for a in self._employees.values() if a.active)
        burnout_arr = np.array(burnouts) if burnouts else np.array([0.0])
        snap = SimulationSnapshot(
            tick=self._tick,
            active_headcount=active,
            quits_this_tick=quits,
            hires_this_tick=self._new_hires_this_tick,
            mean_productivity=float(np.mean(prods)) if prods else 0.0,
            mean_engagement=float(np.mean(engs)) if engs else 0.0,
            mean_collaboration=float(np.mean(colls)) if colls else 0.0,
            mean_turnover_risk=float(np.mean(risks)) if risks else 0.0,
            mean_burnout=float(np.mean(burnouts)) if burnouts else 0.0,
            mean_stress=float(np.mean(stresses)) if stresses else 0.0,
            mean_sleep_quality=float(np.mean(sleeps)) if sleeps else 0.0,
            mean_mood=float(np.mean(moods)) if moods else 0.0,
            mean_psychological_safety=float(np.mean(safeties)) if safeties else 0.0,
            burnout_rate=float((burnout_arr >= 0.7).mean()),
        )
        self._snapshots.append(snap)
        self._tick += 1
        return snap

    def run(self, ticks: int) -> pd.DataFrame:
        for _ in range(ticks):
            self.step()
        return self.history()

    # ---- mutations (called by scenario events) ----

    def add_employees(self, count: int, department_id: str) -> list[EmployeeAgent]:
        """Add ``count`` fresh hires into ``department_id``.

        Placement rule: fill the smallest active team in the department;
        spin up a new team only if every team already has 10+ members.
        Kept internal to the model to reuse its RNG stream.
        """
        # Local import to avoid a data → scenarios → model → data cycle.
        from companysim.data.generators import _generate_new_hire  # noqa: PLC0415

        added: list[EmployeeAgent] = []
        dept_teams = [t for t in self._teams.values() if t.record.department_id == department_id]
        if not dept_teams:
            raise ValueError(f"Unknown department: {department_id}")

        dept = next(d for d in self.organization.departments if d.id == department_id)

        for _ in range(count):
            # Pick the smallest active team; if all are large, create a new one.
            dept_teams.sort(key=lambda t: t.active_headcount())
            target_team = dept_teams[0]
            if target_team.active_headcount() >= 10:
                new_team_id = f"team_new_{self._tick:03d}_{len(self._teams):04d}"
                from companysim.data.schemas import Team  # noqa: PLC0415
                team_rec = Team(
                    id=new_team_id,
                    name=f"{dept.name} New Team ({self._tick})",
                    department_id=department_id,
                )
                self.organization.teams.append(team_rec)
                target_team = TeamAgent(record=team_rec)
                self._teams[new_team_id] = target_team
                dept_teams.append(target_team)

            record = _generate_new_hire(
                idx=self._next_emp_index,
                dept=dept,
                team=target_team.record,
                rng=self._rng,
                org_name=self.organization.name,
            )
            self._next_emp_index += 1
            self.organization.employees.append(record)
            target_team.record.member_ids.append(record.id)

            sub_rng = np.random.default_rng(self._rng.integers(0, 2**32 - 1))
            agent = EmployeeAgent(record=record, _rng=sub_rng)
            self._employees[record.id] = agent
            target_team.members.append(agent)
            added.append(agent)
            self._new_hires_this_tick += 1
        return added

    # ---- accessors ----

    def history(self) -> pd.DataFrame:
        return pd.DataFrame([s.__dict__ for s in self._snapshots])

    def employee_frame(self) -> pd.DataFrame:
        rows = []
        for a in self._employees.values():
            r = a.record
            p = a.profile
            rows.append({
                "id": r.id,
                "team_id": r.team_id,
                "department_id": r.department_id,
                "level": r.level,
                "role": r.role,
                "tenure_months": r.tenure_months,
                "salary": r.salary,
                "active": a.active,
                "productivity": a.productivity,
                "engagement": a.engagement,
                "collaboration": a.collaboration,
                "turnover_risk": a.turnover_risk,
                "burnout": p.burnout if p else 0.0,
                "stress": p.stress if p else 0.0,
                "sleep_quality": p.sleep_quality if p else 0.0,
                "mood": p.mood if p else 0.0,
                "psychological_safety": p.psychological_safety if p else 0.0,
                "workload": p.baseline_workload if p else 0.0,
                "meaning": p.meaning if p else 0.0,
            })
        return pd.DataFrame(rows)
