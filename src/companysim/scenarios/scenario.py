"""A Scenario is just an ordered bundle of events.

Two scenarios with the same events (in any order) applied to the same seed
must produce identical results — that's what makes MC replicates comparable.
Events are keyed by ``at_tick`` at run time by :class:`OrganizationModel`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from companysim.scenarios.events import Event


@dataclass
class Scenario:
    name: str
    events: list[Event] = field(default_factory=list)
    description: str = ""

    def events_at(self, tick: int) -> list[Event]:
        return [e for e in self.events if e.at_tick == tick]

    def horizon(self) -> int:
        return max((e.at_tick for e in self.events), default=0)

    def summary(self) -> dict[int, list[str]]:
        by_tick: dict[int, list[str]] = defaultdict(list)
        for e in self.events:
            by_tick[e.at_tick].append(type(e).__name__)
        return dict(sorted(by_tick.items()))


BASELINE: Scenario = Scenario(
    name="baseline",
    description="No interventions — pure organic drift.",
)
