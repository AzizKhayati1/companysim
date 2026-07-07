"""Browse saved simulate/diagnose run history for an org.

Runs themselves are written by `routers/simulate.py` and
`routers/diagnose.py` via `run_history.save_run` — this router only reads
and deletes.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import RunRecord
from companysim.api.schemas import RunDetailOut, RunSummaryOut

router = APIRouter(prefix="/orgs/{org_id}/runs", tags=["runs"])


def _get_run_or_404(db: Session, org_id: int, run_id: int) -> RunRecord:
    run = db.query(RunRecord).filter_by(org_id=org_id, id=run_id).first()
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.get("", response_model=list[RunSummaryOut])
def list_runs(org_id: int, run_type: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(RunRecord).filter_by(org_id=org_id)
    if run_type is not None:
        query = query.filter_by(run_type=run_type)
    rows = query.order_by(RunRecord.id.desc()).limit(limit).all()
    return [
        RunSummaryOut(
            id=r.id, run_type=r.run_type, created_at=r.created_at.isoformat(), summary=r.summary,
        )
        for r in rows
    ]


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(org_id: int, run_id: int, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, org_id, run_id)
    return RunDetailOut(
        id=run.id, run_type=run.run_type, created_at=run.created_at.isoformat(), summary=run.summary,
        request=json.loads(run.request_json), response=json.loads(run.response_json),
    )


@router.delete("/{run_id}", status_code=204)
def delete_run(org_id: int, run_id: int, db: Session = Depends(get_db)):
    run = _get_run_or_404(db, org_id, run_id)
    db.delete(run)
    db.commit()
