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

It blends in a second real source too: cohorts derived from ingested
documents (``api.ingest_records.load_all_document_examples``). Those come
with a denominator requirement rather than as loose rows — see
``ingest.cohorts`` for why a pile of resignation letters is not a
training set — and orgs that can't produce a valid cohort simply
contribute nothing. Both sources are reported separately in the promotion
log via ``extra_example_counts``, so an AUC move can be attributed to a
source instead of merely observed.
"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.db_models import TurnoverTrainingExample
from companysim.api.ingest_records import load_all_document_examples
from companysim.api.schemas import (
    ModelQualityResponse,
    ModelStatusResponse,
    TrainModelRequest,
    TrainModelResponse,
)
from companysim.api.training_examples import load_collected_examples
from companysim.ml.gate import (
    get_production_feature_importances,
    get_production_status,
    load_promotion_log,
    run_training_gate,
)

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status", response_model=ModelStatusResponse)
def model_status(db: Session = Depends(get_db)):
    metadata = get_production_status()
    pending = db.query(TurnoverTrainingExample).count()
    _, n_document_examples = load_all_document_examples(db)
    return ModelStatusResponse(
        model_available=metadata is not None, metadata=metadata or {},
        pending_training_examples=pending,
        pending_document_examples=n_document_examples,
    )


@router.get("/quality", response_model=ModelQualityResponse)
def model_quality():
    return ModelQualityResponse(
        history=load_promotion_log(),
        feature_importances=get_production_feature_importances(),
    )


@router.post("/train", response_model=TrainModelResponse)
def train_model(req: TrainModelRequest, db: Session = Depends(get_db)):
    run_examples = load_collected_examples(db)
    document_examples, n_documents = load_all_document_examples(db)
    frames = [f for f in (run_examples, document_examples) if not f.empty]
    extra_examples = pd.concat(frames, ignore_index=True) if frames else run_examples
    counts = {"webapp_runs": len(run_examples), "documents": n_documents}

    result = run_training_gate(
        headcount=req.headcount, replicates=req.replicates, horizon=req.horizon,
        seed=req.seed, tolerance=req.tolerance, force_promote=req.force_promote,
        extra_examples=extra_examples, extra_example_counts=counts,
    )
    return TrainModelResponse(
        decision=result.decision,
        reason=result.reason,
        candidate_eval=result.candidate_eval,
        production_eval=result.production_eval,
        train_report=result.train_report,
        promoted_at=result.promoted_at,
        n_live_examples=result.n_live_examples,
        n_document_examples=result.n_document_examples,
        extra_example_counts=result.extra_example_counts,
    )
