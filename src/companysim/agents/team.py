"""Team agent.

Aggregates members' state into two team-level signals fed back to each
agent next tick:

- ``climate`` — engagement + collaboration mix, drives peer effects.
- ``psychological_safety`` — Edmondson's team trust construct, moderates
  how much manager support and meaning translate into engagement gains.

A demoralized team drags its members down; a healthy one lifts them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from companysim.agents.employee import EmployeeAgent
from companysim.data.schemas import Team


@dataclass
class TeamAgent:
    record: Team
    members: list[EmployeeAgent] = field(default_factory=list)
    climate: float = 0.5
    psychological_safety: float = 0.6

    def compute_climate(self) -> float:
        active = [m for m in self.members if m.active]
        if not active:
            self.climate = 0.0
            self.psychological_safety = 0.0
            return 0.0
        engagement = sum(m.engagement for m in active) / len(active)
        collaboration = sum(m.collaboration for m in active) / len(active)
        self.climate = 0.6 * engagement + 0.4 * collaboration
        # Team psych safety = average of member perceptions; if any member
        # has no profile, default to 0.6.
        safeties = [
            m.profile.psychological_safety if m.profile else 0.6 for m in active
        ]
        self.psychological_safety = sum(safeties) / len(safeties)
        return self.climate

    def active_headcount(self) -> int:
        return sum(1 for m in self.members if m.active)

    def mean_burnout(self) -> float:
        active = [m for m in self.members if m.active]
        if not active:
            return 0.0
        return sum(m.burnout for m in active) / len(active)
