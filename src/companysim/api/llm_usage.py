"""Persist and aggregate LLM token usage.

The DB-coupled half of ``companysim.llm.usage``: that module collects
:class:`~companysim.llm.usage.LlmCall` objects with no idea where they go,
this one writes them and answers the questions the counter asks —
all-time, today, this week, and the last few individual requests.

Mirrors ``exit_note_records.py``'s persist-and-query-in-one-module shape
for the same reason: the queries are small and have exactly one consumer.

**Time windows are UTC**, matching ``created_at``'s default. "Today" is
therefore the UTC day, not the viewer's local one — stated here rather
than silently differing from what a user in UTC+9 expects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from companysim.api.db_models import LlmUsageRecord
from companysim.llm.usage import LlmCall

RECENT_LIMIT = 10


def record_llm_calls(
    db: Session, calls: list[LlmCall], *, org_id: int | None = None,
) -> int:
    """Persist a router's collected calls. Returns how many rows were
    written — 0 when the feature was disabled or the call failed before
    reaching the provider, which is a real and expected outcome, not an
    error.
    """
    if not calls:
        return 0
    db.add_all([
        LlmUsageRecord(
            org_id=org_id, feature=c.feature, model=c.model,
            prompt_tokens=c.prompt_tokens, completion_tokens=c.completion_tokens,
            total_tokens=c.total_tokens,
        )
        for c in calls
    ])
    db.commit()
    return len(calls)


def _totals_since(db: Session, since: datetime | None) -> dict[str, int]:
    q = db.query(
        func.count(LlmUsageRecord.id).label("requests"),
        func.coalesce(func.sum(LlmUsageRecord.prompt_tokens), 0).label("prompt"),
        func.coalesce(func.sum(LlmUsageRecord.completion_tokens), 0).label("completion"),
        func.coalesce(func.sum(LlmUsageRecord.total_tokens), 0).label("total"),
    )
    if since is not None:
        q = q.filter(LlmUsageRecord.created_at >= since)
    row = q.one()
    return {
        "requests": int(row.requests or 0),
        "prompt_tokens": int(row.prompt or 0),
        "completion_tokens": int(row.completion or 0),
        "total_tokens": int(row.total or 0),
    }


def usage_summary(db: Session) -> dict[str, Any]:
    """All-time / today / last 7 days, a per-feature split, and the most
    recent individual requests.

    "Week" is a rolling 7×24h window rather than a calendar week — for a
    usage counter, "how much have I spent recently" is the question being
    asked, and a calendar week would reset to near-zero every Monday.
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    by_feature = [
        {
            "feature": r.feature,
            "requests": int(r.requests or 0),
            "total_tokens": int(r.total or 0),
        }
        for r in db.query(
            LlmUsageRecord.feature,
            func.count(LlmUsageRecord.id).label("requests"),
            func.coalesce(func.sum(LlmUsageRecord.total_tokens), 0).label("total"),
        ).group_by(LlmUsageRecord.feature)
         .order_by(func.sum(LlmUsageRecord.total_tokens).desc())
         .all()
    ]

    recent = [
        {
            "id": r.id,
            "feature": r.feature,
            "model": r.model,
            "org_id": r.org_id,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "created_at": r.created_at.isoformat(),
        }
        for r in db.query(LlmUsageRecord)
                   .order_by(LlmUsageRecord.created_at.desc(), LlmUsageRecord.id.desc())
                   .limit(RECENT_LIMIT)
                   .all()
    ]

    return {
        "all_time": _totals_since(db, None),
        "today": _totals_since(db, day_start),
        "week": _totals_since(db, week_start),
        "by_feature": by_feature,
        "recent": recent,
    }
