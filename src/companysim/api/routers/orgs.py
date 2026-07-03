from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import DepartmentRecord, EmployeeRecord, OrgRecord, TeamRecord
from companysim.api.schemas import OrgCreate, OrgSummary
from companysim.api.seed import create_org

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _to_summary(db: Session, org: OrgRecord) -> OrgSummary:
    headcount = db.query(EmployeeRecord).filter_by(org_id=org.id).count()
    dept_count = db.query(DepartmentRecord).filter_by(org_id=org.id).count()
    team_count = db.query(TeamRecord).filter_by(org_id=org.id).count()
    return OrgSummary(
        id=org.id, name=org.name, seed=org.seed,
        headcount=headcount, department_count=dept_count, team_count=team_count,
    )


@router.get("", response_model=list[OrgSummary])
def list_orgs(db: Session = Depends(get_db)):
    orgs = db.query(OrgRecord).order_by(OrgRecord.id.desc()).all()
    return [_to_summary(db, o) for o in orgs]


@router.post("", response_model=OrgSummary, status_code=201)
def create_new_org(body: OrgCreate, db: Session = Depends(get_db)):
    if body.headcount < 2:
        raise HTTPException(400, "headcount must be at least 2")
    org = create_org(db, name=body.name, headcount=body.headcount, seed=body.seed)
    return _to_summary(db, org)


@router.get("/{org_id}", response_model=OrgSummary)
def get_org(org_id: int, db: Session = Depends(get_db)):
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    return _to_summary(db, org)


@router.delete("/{org_id}", status_code=204)
def delete_org(org_id: int, db: Session = Depends(get_db)):
    org = db.get(OrgRecord, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    db.delete(org)
    db.commit()
