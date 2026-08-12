"""Clear stale "LLM not configured" reasons off source documents

Revision ID: a1c4f77e21b3
Revises: 5b8975d34068
Create Date: 2026-08-05

Data-only. ``source_documents.extraction_error`` was written when Extract
last ran, so a document that failed because the *server* was unconfigured
kept that sentence forever — including after the configuration was fixed,
and including across a provider switch. Users saw "needs a GROQ_API_KEY" on
a working Bedrock deployment with no way to tell the reason was historical.

``routers/ingest.py`` no longer records that class of failure onto the row
at all (it leaves the document ``pending`` and lets the live status banner
report configuration state). This migration retires the rows written before
that change, so the fix reaches existing databases rather than only new
uploads.

Matched narrowly, by the two sentences the app itself produced, so a
genuine per-document refusal — an unreadable file, a letter naming nobody,
a review with no rating — is never cleared. Those are judgements about the
document and remain correct.

Nothing is lost that re-running Extract would not reproduce.
"""
from __future__ import annotations

from alembic import op

revision = "a1c4f77e21b3"
down_revision = "5b8975d34068"
branch_labels = None
depends_on = None

# The two shapes the app shipped. The first is the original fixed checklist;
# the second is the provider-aware message that replaced it and was still
# frozen onto the row.
_STALE_PATTERNS = (
    "%extra installed%",
    "Free-text extraction is not configured%",
)


def upgrade() -> None:
    for pattern in _STALE_PATTERNS:
        op.execute(
            "UPDATE source_documents "
            "SET extraction_status = 'pending', extraction_error = NULL "
            "WHERE extraction_status = 'needs_review' "
            f"AND extraction_error LIKE '{pattern}'"
        )


def downgrade() -> None:
    """No-op.

    The original text is not recoverable, and re-inventing it would restore
    a message that was wrong when it was written. A document left ``pending``
    is accurate under either schema: nothing was ever extracted from it.
    """
