"""Synthetic workforce data generation.

Produces a fully-formed :class:`Organization` — departments, teams, employees,
reporting lines, and per-employee latent behavioral traits — from a single
seed so runs are reproducible.

The distributions here are hand-tuned to look plausible, not calibrated
against any real dataset. That's fine for a v0: the whole point of building
on synthetic data is that we control the ground truth and can later
recalibrate against public labor-market benchmarks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from faker import Faker

from companysim.data.schemas import (
    Department,
    DepartmentName,
    Employee,
    Level,
    Organization,
    Team,
)

# Pyramid: roughly what an org chart looks like at each rung.
_LEVEL_WEIGHTS: dict[Level, float] = {
    "IC1": 0.14,
    "IC2": 0.22,
    "IC3": 0.20,
    "IC4": 0.12,
    "IC5": 0.06,
    "M1": 0.12,
    "M2": 0.08,
    "M3": 0.04,
    "VP": 0.015,
    "CXO": 0.005,
}

# Base salary midpoint per level, in local currency units.
_LEVEL_SALARY: dict[Level, float] = {
    "IC1": 60_000, "IC2": 85_000, "IC3": 115_000, "IC4": 145_000, "IC5": 180_000,
    "M1": 140_000, "M2": 180_000, "M3": 230_000, "VP": 320_000, "CXO": 480_000,
}

_DEPARTMENTS: list[DepartmentName] = [
    "Engineering", "Product", "Design", "Sales", "Marketing",
    "Customer Success", "Finance", "People", "Operations",
]

_ROLES_BY_DEPT: dict[DepartmentName, list[str]] = {
    "Engineering": ["Backend Engineer", "Frontend Engineer", "SRE", "ML Engineer", "QA Engineer"],
    "Product": ["Product Manager", "Product Analyst", "Technical PM"],
    "Design": ["Product Designer", "UX Researcher", "Design Systems"],
    "Sales": ["Account Executive", "SDR", "Sales Engineer"],
    "Marketing": ["Content Marketer", "Growth Marketer", "Brand Manager"],
    "Customer Success": ["CSM", "Support Engineer", "Onboarding Specialist"],
    "Finance": ["FP&A Analyst", "Accountant", "Controller"],
    "People": ["Recruiter", "HRBP", "People Ops"],
    "Operations": ["Business Operations", "Legal", "IT"],
}


@dataclass(frozen=True)
class GeneratorConfig:
    org_name: str = "Acme Corp"
    headcount: int = 200
    team_size_mean: int = 7
    team_size_std: float = 2.0
    seed: int = 42


class WorkforceGenerator:
    """Deterministic synthetic org generator.

    Same ``seed`` → same org, every time. That property is what lets Monte
    Carlo runs later vary *one* thing (policy, layoff %, hiring plan) while
    holding the starting population fixed.
    """

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self.config = config or GeneratorConfig()
        self._rng = np.random.default_rng(self.config.seed)
        self._faker = Faker()
        Faker.seed(self.config.seed)

    # ---- public API ----

    def generate(self) -> Organization:
        departments = self._build_departments()
        employees, teams = self._build_teams_and_employees(departments)
        self._assign_reporting_lines(employees, teams, departments)
        return Organization(
            name=self.config.org_name,
            departments=departments,
            teams=teams,
            employees=employees,
        )

    # ---- internals ----

    def _build_departments(self) -> list[Department]:
        return [
            Department(id=f"dept_{i:02d}", name=name)
            for i, name in enumerate(_DEPARTMENTS)
        ]

    def _build_teams_and_employees(
        self, departments: list[Department]
    ) -> tuple[list[Employee], list[Team]]:
        # Weight headcount toward Engineering / Sales, thinner in Finance / People.
        dept_weights = np.array([3.5, 1.2, 0.7, 2.0, 1.2, 1.2, 0.6, 0.6, 1.0])
        dept_weights /= dept_weights.sum()
        dept_headcount = self._rng.multinomial(self.config.headcount, dept_weights)

        employees: list[Employee] = []
        teams: list[Team] = []
        emp_counter = 0
        team_counter = 0

        for dept, hc in zip(departments, dept_headcount, strict=True):
            remaining = int(hc)
            while remaining > 0:
                size = max(
                    2,
                    int(self._rng.normal(self.config.team_size_mean, self.config.team_size_std)),
                )
                size = min(size, remaining)
                team_id = f"team_{team_counter:03d}"
                team_counter += 1
                team = Team(
                    id=team_id,
                    name=f"{dept.name} Team {team_counter}",
                    department_id=dept.id,
                )
                for _ in range(size):
                    emp = self._make_employee(emp_counter, dept, team)
                    employees.append(emp)
                    team.member_ids.append(emp.id)
                    emp_counter += 1
                teams.append(team)
                remaining -= size
        return employees, teams

    def _make_employee(self, idx: int, dept: Department, team: Team) -> Employee:
        return _build_employee(
            idx=idx, dept=dept, team=team,
            rng=self._rng, faker=self._faker, org_name=self.config.org_name,
            tenure_dist="exponential",
        )

    def _assign_reporting_lines(
        self,
        employees: list[Employee],
        teams: list[Team],
        departments: list[Department],
    ) -> None:
        by_id = {e.id: e for e in employees}

        # 1. Team manager = highest-level member in the team; falls back to
        #    picking a senior IC if no true manager landed there.
        for team in teams:
            members = [by_id[mid] for mid in team.member_ids]
            candidates = [m for m in members if m.level in ("M1", "M2", "M3")]
            manager = max(candidates, key=_seniority) if candidates else max(members, key=_seniority)
            team.manager_id = manager.id
            for m in members:
                if m.id != manager.id:
                    m.manager_id = manager.id

        # 2. Department head = most senior team manager in the department.
        for dept in departments:
            dept_managers = [
                by_id[t.manager_id]
                for t in teams
                if t.department_id == dept.id and t.manager_id is not None
            ]
            if not dept_managers:
                continue
            head = max(dept_managers, key=_seniority)
            dept.head_id = head.id
            # Team managers report to the dept head (except the head itself).
            for m in dept_managers:
                if m.id != head.id:
                    m.manager_id = head.id


_SENIORITY_ORDER: dict[Level, int] = {
    "IC1": 1, "IC2": 2, "IC3": 3, "IC4": 4, "IC5": 5,
    "M1": 6, "M2": 7, "M3": 8, "VP": 9, "CXO": 10,
}


def _seniority(emp: Employee) -> int:
    return _SENIORITY_ORDER[emp.level]


def _build_employee(
    *,
    idx: int,
    dept: Department,
    team: Team,
    rng: np.random.Generator,
    faker: Faker,
    org_name: str,
    tenure_dist: str = "exponential",
) -> Employee:
    """Shared employee-record builder used by both initial-org generation and
    mid-simulation hiring. ``tenure_dist='new_hire'`` clamps tenure to 0
    months, which is what a fresh hire should look like on day one.
    """
    level = rng.choice(list(_LEVEL_WEIGHTS), p=list(_LEVEL_WEIGHTS.values()))
    role = rng.choice(_ROLES_BY_DEPT[dept.name])
    name = faker.name()
    local = name.lower().replace(" ", ".").replace("'", "")
    salary_noise = rng.normal(1.0, 0.08)
    salary = max(30_000, float(_LEVEL_SALARY[level] * salary_noise))

    if tenure_dist == "new_hire":
        tenure = 0
    else:
        tenure = int(np.clip(rng.exponential(24), 0, 240))

    productivity = float(rng.beta(6, 3))
    collab_alpha = 7 if level.startswith("M") or level in ("VP", "CXO") else 5
    collaboration = float(rng.beta(collab_alpha, 3))
    engagement = float(rng.beta(5, 3)) * (0.85 if tenure < 6 else 1.0)
    engagement = float(np.clip(engagement, 0.0, 1.0))
    turnover = float(np.clip(
        0.8 - 0.6 * engagement + (0.15 if tenure < 12 else 0.0)
        + rng.normal(0, 0.05),
        0.0, 1.0,
    ))

    return Employee(
        id=f"emp_{idx:05d}",
        name=name,
        email=f"{local}@{org_name.lower().replace(' ', '')}.example",
        department_id=dept.id,
        team_id=team.id,
        level=level,
        role=str(role),
        tenure_months=tenure,
        salary=round(salary, 2),
        productivity=productivity,
        engagement=engagement,
        collaboration=collaboration,
        turnover_risk=turnover,
    )


# Module-level Faker instance for mid-sim hires — seeded once on first use.
# Uses a separate stream from the initial generator so hiring events don't
# perturb the baseline org.
_HIRE_FAKER: Faker | None = None


def _generate_new_hire(
    idx: int,
    dept: Department,
    team: Team,
    rng: np.random.Generator,
    org_name: str,
) -> Employee:
    global _HIRE_FAKER
    if _HIRE_FAKER is None:
        _HIRE_FAKER = Faker()
        Faker.seed(int(rng.integers(0, 2**31 - 1)))
    return _build_employee(
        idx=idx, dept=dept, team=team,
        rng=rng, faker=_HIRE_FAKER, org_name=org_name,
        tenure_dist="new_hire",
    )
