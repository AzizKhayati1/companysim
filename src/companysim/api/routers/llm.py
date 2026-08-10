"""LLM token usage — the read side of ``api/llm_usage.py``.

Not org-scoped: a token bill is per-server, and the three features that
spend tokens have different scopes (chat and ingest are org-scoped, exit
notes belong to a run). Aggregating per-org would answer a question nobody
asked while making the total — the number you actually get charged for —
harder to see.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from companysim.api.database import get_db
from companysim.api.llm_usage import usage_summary
from companysim.api.schemas import LlmStatusResponse, LlmUsageResponse
from companysim.llm import provider

router = APIRouter(prefix="/llm", tags=["llm"])

_FEATURE_FLAGS = {
    "ingest": "COMPANYSIM_LLM_INGEST",
    "exit_notes": "COMPANYSIM_LLM_EXIT_NOTES",
    "chat": "COMPANYSIM_LLM_CHAT",
}


@router.get("/usage", response_model=LlmUsageResponse)
def get_llm_usage(db: Session = Depends(get_db)):
    return LlmUsageResponse(**usage_summary(db))


@router.get("/status", response_model=LlmStatusResponse)
def get_llm_status():
    """What this process resolved at request time.

    Deliberately not cached and not read from ``.env``: the whole point is
    to report the environment *this server* is running with, which is the
    one thing an outside observer cannot otherwise see. A ``.env`` edited
    after launch will differ from what this returns, and that difference is
    the answer rather than a bug.
    """
    return LlmStatusResponse(
        provider=provider.active_provider(),
        model=provider.model_id(),
        provider_ready=provider.provider_ready(),
        provider_problem=provider.provider_problem(),
        features={
            name: provider.is_enabled(var) for name, var in _FEATURE_FLAGS.items()
        },
    )
