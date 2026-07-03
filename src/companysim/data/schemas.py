"""Typed schemas for the synthetic organization.

These are the plain-data records the generator emits and the agents wrap.
Kept separate from the agent classes so we can serialize / snapshot state
without dragging simulation logic along.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3", "VP", "CXO"]
DepartmentName = Literal[
    "Engineering", "Product", "Design", "Sales", "Marketing",
    "Customer Success", "Finance", "People", "Operations",
]


class Department(BaseModel):
    id: str
    name: DepartmentName
    head_id: str | None = None


class Team(BaseModel):
    id: str
    name: str
    department_id: str
    manager_id: str | None = None
    member_ids: list[str] = Field(default_factory=list)


class Employee(BaseModel):
    id: str
    name: str
    email: str
    department_id: str
    team_id: str
    manager_id: str | None = None
    level: Level
    role: str
    tenure_months: int = Field(ge=0)
    salary: float = Field(gt=0)

    # Behavioral latent traits, on 0..1 scales. These drive the agent's
    # per-tick outcomes and are what the ML models will later try to predict
    # from observable features.
    productivity: float = Field(ge=0.0, le=1.0)
    engagement: float = Field(ge=0.0, le=1.0)
    collaboration: float = Field(ge=0.0, le=1.0)
    turnover_risk: float = Field(ge=0.0, le=1.0)


class Organization(BaseModel):
    name: str
    departments: list[Department]
    teams: list[Team]
    employees: list[Employee]

    def headcount(self) -> int:
        return len(self.employees)
