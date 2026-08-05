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
from companysim.api.schemas import LlmUsageResponse

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/usage", response_model=LlmUsageResponse)
def get_llm_usage(db: Session = Depends(get_db)):
    return LlmUsageResponse(**usage_summary(db))
