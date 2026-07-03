"""Scenario events — declarative mutations of the running simulation.

Each event knows the tick at which it fires and how to mutate the model.
Keeping the events as data (rather than callbacks) means a scenario is
serializable, comparable, and — importantly for the MLOps side later —
loggable as an experiment parameter.

An event's ``apply`` is called *before* the corresponding ``step()``, so a
layoff at tick 5 affects productivity metrics reported for tick 5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from companysim.model.organization import OrganizationModel


class Event(Protocol):
    at_tick: int

    def apply(self, model: "OrganizationModel") -> None: ...


@dataclass(frozen=True)
class Layoff:
    """Deactivate a fraction of active employees, optionally scoped to a dept."""

    at_tick: int
    fraction: float
    department: str | None = None

    def apply(self, model: "OrganizationModel") -> None:
        pool = [
            a for a in model.employees.values()
            if a.active and (self.department is None or a.record.department_id == self.department)
        ]
        n = int(round(len(pool) * self.fraction))
        if n == 0:
            return
        rng = model.rng
        # Bias toward higher turnover_risk — regretted attrition happens
        # in real layoffs too, but the ones already halfway out the door
        # go first.
        weights = np.array([0.5 + a.turnover_risk for a in pool])
        weights /= weights.sum()
        picks = rng.choice(len(pool), size=n, replace=False, p=weights)
        for i in picks:
            pool[int(i)].active = False


@dataclass(frozen=True)
class Hire:
    """Add ``count`` new employees into a specific department."""

    at_tick: int
    count: int
    department: str
    # New hires start with lower tenure and slightly damped engagement —
    # gives us the "onboarding drag" the sim should exhibit.

    def apply(self, model: "OrganizationModel") -> None:
        model.add_employees(count=self.count, department_id=self.department)


@dataclass(frozen=True)
class Promotion:
    """Promote ``count`` employees at or above a minimum level."""

    at_tick: int
    count: int
    from_level: str  # promote FROM this level (moves up one rung)

    def apply(self, model: "OrganizationModel") -> None:
        from companysim.data.generators import _SENIORITY_ORDER  # noqa: PLC0415

        candidates = [
            a for a in model.employees.values()
            if a.active and a.record.level == self.from_level
        ]
        if not candidates:
            return
        # Highest performers first — proxy for merit.
        candidates.sort(key=lambda a: a.productivity, reverse=True)
        promotions = candidates[: self.count]
        # Find the next level up.
        by_rank = sorted(_SENIORITY_ORDER.items(), key=lambda kv: kv[1])
        levels = [k for k, _ in by_rank]
        try:
            next_level = levels[levels.index(self.from_level) + 1]
        except (ValueError, IndexError):
            return
        for a in promotions:
            a.record.level = next_level  # type: ignore[assignment]
            # Small engagement bump on promotion; wears off through drift.
            a.engagement = min(1.0, a.engagement + 0.08)


@dataclass(frozen=True)
class RetentionBonus:
    """One-time retention bonus targeted at specific employees.

    Unlike :class:`PolicyChange`, this is individually targeted — the
    natural lever for "here are our 20 highest-risk employees, what if we
    paid them to stay?" Bumps financial security (the bonus itself, a
    permanent shift — no decay mechanism moves it back down) and gives a
    small, decaying mood/engagement lift, mirroring the bump
    :class:`Promotion` already gives.

    Also gives a direct, one-time reduction to the employee's tracked
    ``turnover_risk`` — a bonus conversation is a direct signal ("we want
    you to stay") with an immediate effect on quit intent, not just an
    indirect one mediated by financial stress. Without this, the bonus's
    only lasting channel is financial_security's small (0.05) coefficient
    in the stress formula, several attenuating layers removed from
    turnover_risk — too weak to show up against a targeted cohort's
    baseline exit rate over a realistic horizon.
    """

    at_tick: int
    employee_ids: tuple[str, ...]
    amount_pct: float = 0.10  # bonus size as a fraction of current financial_security headroom

    def apply(self, model: "OrganizationModel") -> None:
        for eid in self.employee_ids:
            a = model.employees.get(eid)
            if a is None or not a.active or a.profile is None:
                continue
            p = a.profile
            p.financial_security = float(np.clip(
                p.financial_security + self.amount_pct * (1.0 - p.financial_security), 0.0, 1.0,
            ))
            a.engagement = float(np.clip(a.engagement + 0.06, 0.0, 1.0))
            p.mood = float(np.clip(p.mood + 0.05, 0.0, 1.0))
            a.turnover_risk = float(np.clip(a.turnover_risk - 0.5 * self.amount_pct, 0.0, 1.0))


@dataclass(frozen=True)
class WorkloadRelief:
    """Reduce baseline workload for specific employees (redistribute work,
    hire backup, cut scope) — the direct lever against burnout build-up.
    """

    at_tick: int
    employee_ids: tuple[str, ...]
    delta: float = 0.15

    def apply(self, model: "OrganizationModel") -> None:
        for eid in self.employee_ids:
            a = model.employees.get(eid)
            if a is None or not a.active or a.profile is None:
                continue
            a.profile.baseline_workload = float(np.clip(
                a.profile.baseline_workload - self.delta, 0.0, 1.0,
            ))


@dataclass(frozen=True)
class ManagerCoaching:
    """Raise manager support / psychological safety for a whole team —
    the lever when the diagnosis is "this team's manager needs help," not
    any single employee.
    """

    at_tick: int
    team_id: str
    delta: float = 0.15

    def apply(self, model: "OrganizationModel") -> None:
        team = model.teams.get(self.team_id)
        if team is None:
            return
        for a in team.members:
            if not a.active or a.profile is None:
                continue
            a.profile.manager_support = float(np.clip(
                a.profile.manager_support + self.delta, 0.0, 1.0,
            ))
            a.profile.psychological_safety = float(np.clip(
                a.profile.psychological_safety + self.delta, 0.0, 1.0,
            ))


@dataclass(frozen=True)
class PolicyChange:
    """Coarse policy lever — shifts every active employee's engagement by ``delta``.

    Positive delta models a well-received policy (e.g., WFH flexibility);
    negative models a poorly-received one (e.g., forced RTO). Effect is
    persistent — the drift term keeps pulling toward baseline but the
    shifted state is what gets reported next tick.
    """

    at_tick: int
    delta: float
    department: str | None = None

    def apply(self, model: "OrganizationModel") -> None:
        for a in model.employees.values():
            if not a.active:
                continue
            if self.department and a.record.department_id != self.department:
                continue
            a.engagement = float(np.clip(a.engagement + self.delta, 0.0, 1.0))


# ---- Global / org-wide levers -----------------------------------------------


@dataclass(frozen=True)
class BudgetCut:
    """Reduce financial security org-wide or for one department — the
    inverse of :class:`RetentionBonus`. Models a comp freeze, reduced
    bonus pool, or benefits rollback rather than a headcount action.
    """

    at_tick: int
    severity: float  # 0..1, fraction of current financial_security headroom removed
    department: str | None = None

    def apply(self, model: "OrganizationModel") -> None:
        for a in model.employees.values():
            if not a.active or a.profile is None:
                continue
            if self.department and a.record.department_id != self.department:
                continue
            p = a.profile
            p.financial_security = float(np.clip(
                p.financial_security - self.severity * p.financial_security, 0.0, 1.0,
            ))
            p.mood = float(np.clip(p.mood - 0.05, 0.0, 1.0))


@dataclass(frozen=True)
class Reorg:
    """Restructuring uncertainty — dents psychological safety and sense of
    meaning org-wide or for one department, without changing anyone's
    actual role. The disruption itself is the mechanism, distinct from
    :class:`Layoff`/:class:`Transfer` which change who's where.
    """

    at_tick: int
    department: str | None = None
    delta: float = 0.15

    def apply(self, model: "OrganizationModel") -> None:
        for a in model.employees.values():
            if not a.active or a.profile is None:
                continue
            if self.department and a.record.department_id != self.department:
                continue
            p = a.profile
            p.psychological_safety = float(np.clip(p.psychological_safety - self.delta, 0.0, 1.0))
            p.meaning = float(np.clip(p.meaning - self.delta, 0.0, 1.0))


# ---- Employee-targeted levers ------------------------------------------------


@dataclass(frozen=True)
class Termination:
    """Deactivate specific employees outright — a deliberate, named exit
    (performance-based, role elimination, ...), as opposed to
    :class:`Layoff`'s weighted-random selection over a pool.
    """

    at_tick: int
    employee_ids: tuple[str, ...]

    def apply(self, model: "OrganizationModel") -> None:
        for eid in self.employee_ids:
            a = model.employees.get(eid)
            if a is not None:
                a.active = False


@dataclass(frozen=True)
class Transfer:
    """Move employees to a different team mid-run — internal mobility.
    Updates team membership on both sides plus a small, temporary
    psychological-safety dip (new-team adjustment period).
    """

    at_tick: int
    employee_ids: tuple[str, ...]
    new_team_id: str
    adjustment_dip: float = 0.08

    def apply(self, model: "OrganizationModel") -> None:
        new_team = model.teams.get(self.new_team_id)
        if new_team is None:
            return
        for eid in self.employee_ids:
            a = model.employees.get(eid)
            if a is None or not a.active:
                continue
            old_team = model.teams.get(a.record.team_id)
            if old_team is not None and a in old_team.members:
                old_team.members.remove(a)
            a.record.team_id = self.new_team_id
            new_team.members.append(a)
            if a.profile is not None:
                a.profile.psychological_safety = float(np.clip(
                    a.profile.psychological_safety - self.adjustment_dip, 0.0, 1.0,
                ))


# ---- Outside-of-work levers --------------------------------------------------

# Per-type deltas for LifeEvent — small, individually justified nudges, not
# re-derivations of the ACE/attachment framework in human_factors.py, just
# the same idea (adverse or positive life events shift wellbeing) made into
# something that can fire mid-simulation. caregiving_onset is the one
# genuinely persistent state change (caregiving_load doesn't decay on its
# own); the rest are one-time nudges the existing step() persistence/decay
# dynamics carry forward naturally, same as RetentionBonus's mood bump.
_LIFE_EVENT_EFFECTS: dict[str, dict[str, float]] = {
    "bereavement": {"mood": -0.20, "stress": +0.15, "sleep_quality": -0.15},
    "birth_or_adoption": {"mood": +0.10, "sleep_quality": -0.20, "stress": +0.05},
    "moved_house": {"stress": +0.10, "mood": -0.05},
    "divorce_or_separation": {
        "mood": -0.15, "stress": +0.20, "sleep_quality": -0.10, "financial_security": -0.10,
    },
    "serious_illness": {
        "mood": -0.15, "stress": +0.20, "sleep_quality": -0.15, "physical_health": -0.15,
    },
    "caregiving_onset": {"caregiving_load": +0.25, "stress": +0.10, "mood": -0.05},
    "financial_shock": {"financial_security": -0.20, "stress": +0.20, "mood": -0.10},
}


@dataclass(frozen=True)
class LifeEvent:
    """Something happens outside work — the direct lever for the
    human-factors framework's life-context modeling (see
    ``data/human_factors.py``'s ``LIFE_EVENT_TYPES``), made into something
    a scenario can actually trigger rather than only a static generation-time
    attribute.
    """

    at_tick: int
    employee_ids: tuple[str, ...]
    event_type: str  # one of _LIFE_EVENT_EFFECTS keys

    def apply(self, model: "OrganizationModel") -> None:
        effects = _LIFE_EVENT_EFFECTS.get(self.event_type)
        if effects is None:
            return
        for eid in self.employee_ids:
            a = model.employees.get(eid)
            if a is None or not a.active or a.profile is None:
                continue
            p = a.profile
            for field, delta in effects.items():
                current = getattr(p, field)
                setattr(p, field, float(np.clip(current + delta, 0.0, 1.0)))
