from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import EmployeeRecord, OrgRecord, TeamRecord
from companysim.api.schemas import TeamIn, TeamOut

router = APIRouter(prefix="/orgs/{org_id}/teams", tags=["teams"])


def _get_org_or_404(db: Session, org_id: int) -> OrgRecord:
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    return org


def _get_team_or_404(db: Session, org_id: int, team_id: int) -> TeamRecord:
    team = db.query(TeamRecord).filter_by(org_id=org_id, id=team_id).first()
    if team is None:
        raise HTTPException(404, "team not found")
    return team


def _to_out(db: Session, team: TeamRecord) -> TeamOut:
    member_count = db.query(EmployeeRecord).filter_by(team_id=team.id).count()
    return TeamOut(
        id=team.id, name=team.name, department_id=team.department_id,
        manager_employee_id=team.manager_employee_id, member_count=member_count,
    )


@router.get("", response_model=list[TeamOut])
def list_teams(org_id: int, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    teams = db.query(TeamRecord).filter_by(org_id=org_id).all()
    return [_to_out(db, t) for t in teams]


@router.post("", response_model=TeamOut, status_code=201)
def create_team(org_id: int, body: TeamIn, db: Session = Depends(get_db)):
    _get_org_or_404(db, org_id)
    if not body.name or body.department_id is None:
        raise HTTPException(400, "name and department_id are required")
    team = TeamRecord(org_id=org_id, name=body.name, department_id=body.department_id)
    db.add(team)
    db.commit()
    db.refresh(team)
    return _to_out(db, team)


@router.patch("/{team_id}", response_model=TeamOut)
def update_team(org_id: int, team_id: int, body: TeamIn, db: Session = Depends(get_db)):
    team = _get_team_or_404(db, org_id, team_id)
    if body.name is not None:
        team.name = body.name
    if body.department_id is not None:
        team.department_id = body.department_id
    if body.manager_employee_id is not None:
        team.manager_employee_id = body.manager_employee_id
    db.commit()
    db.refresh(team)
    return _to_out(db, team)


@router.delete("/{team_id}", status_code=204)
def delete_team(org_id: int, team_id: int, db: Session = Depends(get_db)):
    team = _get_team_or_404(db, org_id, team_id)
    if db.query(EmployeeRecord).filter_by(team_id=team_id).count() > 0:
        raise HTTPException(400, "team still has employees — move or delete them first")
    db.delete(team)
    db.commit()
