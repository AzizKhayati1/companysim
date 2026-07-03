"""Convert persisted DB state into the objects the simulation engine
already consumes — the read-side mirror of
`companysim.data.datasets.to_organization`, just sourced from SQLAlchemy
rows instead of DataFrames.

String ids handed to the pydantic schema are derived from DB integer PKs
(`f"emp_{id}"` etc.) so foreign keys stay consistent without needing a
second id system.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from companysim.api.db_models import (
    WELLBEING_COLUMNS,
    DepartmentRecord,
    EmployeeRecord,
    TeamRecord,
)
from companysim.data.schemas import Department, Employee, Organization, Team


def dept_str_id(db_id: int) -> str:
    return f"dept_{db_id}"


def team_str_id(db_id: int) -> str:
    return f"team_{db_id}"


def emp_str_id(db_id: int) -> str:
    return f"emp_{db_id}"


def org_to_pydantic(db: Session, org_id: int) -> tuple[Organization, pd.DataFrame]:
    departments = db.query(DepartmentRecord).filter_by(org_id=org_id).all()
    teams = db.query(TeamRecord).filter_by(org_id=org_id).all()
    employees = db.query(EmployeeRecord).filter_by(org_id=org_id).all()

    if not employees:
        raise ValueError(f"Org {org_id} has no employees — nothing to simulate")

    dept_objs = [
        Department(
            id=dept_str_id(d.id), name=d.name,
            head_id=emp_str_id(d.head_employee_id) if d.head_employee_id else None,
        )
        for d in departments
    ]

    team_member_ids: dict[int, list[str]] = {t.id: [] for t in teams}
    for e in employees:
        team_member_ids.setdefault(e.team_id, []).append(emp_str_id(e.id))

    team_objs = [
        Team(
            id=team_str_id(t.id), name=t.name, department_id=dept_str_id(t.department_id),
            manager_id=emp_str_id(t.manager_employee_id) if t.manager_employee_id else None,
            member_ids=team_member_ids.get(t.id, []),
        )
        for t in teams
    ]

    emp_objs: list[Employee] = []
    wellbeing_rows: list[dict] = []
    for e in employees:
        emp_objs.append(Employee(
            id=emp_str_id(e.id), name=e.full_name, email=e.email,
            department_id=dept_str_id(e.department_id), team_id=team_str_id(e.team_id),
            manager_id=emp_str_id(e.manager_id) if e.manager_id else None,
            level=e.level, role=e.role, tenure_months=e.tenure_months,
            salary=e.base_salary, productivity=e.productivity, engagement=e.engagement,
            collaboration=e.collaboration, turnover_risk=e.turnover_risk,
        ))
        w = e.wellbeing
        row = {"employee_id": emp_str_id(e.id)}
        for col in WELLBEING_COLUMNS:
            row[col] = getattr(w, col)
        wellbeing_rows.append(row)

    org = Organization(name="org", departments=dept_objs, teams=team_objs, employees=emp_objs)
    human_factors_df = pd.DataFrame(wellbeing_rows)
    return org, human_factors_df
