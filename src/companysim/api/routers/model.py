"""Model training — the webapp surface over ``ml.gate``'s MLOps pipeline.

Not org-scoped: the turnover model is trained on its own freshly-generated
synthetic cohort (same design as ``scripts/train_turnover_model.py``), not
on any specific user-edited org — it's meant to generalize, and training
needs many forward-simulation replicates to get real exit-event labels,
which would be expensive to run against an arbitrary large edited org.

It does, however, blend in every labeled example collected from real
``/simulate``/``/diagnose`` runs across all orgs
(``api.training_examples.load_collected_examples``) — that's the
"constantly learn from the different simulations we do" part: the more the
app gets used, the more real signal every retrain incorporates, still
gated by the same promotion check as pure-synthetic training.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import TurnoverTrainingExample
from companysim.api.schemas import (
    ModelStatusResponse,
    TrainModelRequest,
    TrainModelResponse,
)
from companysim.api.training_examples import load_collected_examples
from companysim.ml.gate import get_production_status, run_training_gate

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status", response_model=ModelStatusResponse)
def model_status(db: Session = Depends(get_db)):
    metadata = get_production_status()
    pending = db.query(TurnoverTrainingExample).count()
    return ModelStatusResponse(
        model_available=metadata is not None, metadata=metadata or {},
        pending_training_examples=pending,
    )


@router.post("/train", response_model=TrainModelResponse)
def train_model(req: TrainModelRequest, db: Session = Depends(get_db)):
    extra_examples = load_collected_examples(db)
    result = run_training_gate(
        headcount=req.headcount, replicates=req.replicates, horizon=req.horizon,
        seed=req.seed, tolerance=req.tolerance, force_promote=req.force_promote,
        extra_examples=extra_examples,
    )
    return TrainModelResponse(
        decision=result.decision,
        reason=result.reason,
        candidate_eval=result.candidate_eval,
        production_eval=result.production_eval,
        train_report=result.train_report,
        promoted_at=result.promoted_at,
        n_live_examples=result.n_live_examples,
    )
