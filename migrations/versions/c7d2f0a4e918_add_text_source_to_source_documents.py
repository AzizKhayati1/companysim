"""Record how a document's text was obtained

Revision ID: c7d2f0a4e918
Revises: a1c4f77e21b3
Create Date: 2026-08-18

Adds ``source_documents.text_source``: ``native`` for text decoded from
the file, ``ocr:<backend>`` for text transcribed from a photograph or a
scan.

The distinction has to be stored rather than inferred. Filename suffix
almost works — a ``.jpg`` was obviously transcribed — but a scanned PDF
carries a ``.pdf`` suffix and no text layer, so its text also comes from
OCR and nothing in the filename says so. Getting that wrong would present
a value read off a photograph with the same confidence as one decoded
from a CSV cell.

Existing rows are ``native``, which is correct: every document uploaded
before this revision went through a decoder, not an OCR backend.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7d2f0a4e918"
down_revision = "a1c4f77e21b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default is required, not cosmetic: SQLite cannot add a NOT
    # NULL column to a populated table without one.
    op.add_column(
        "source_documents",
        sa.Column("text_source", sa.String(), nullable=False, server_default="native"),
    )


def downgrade() -> None:
    with op.batch_alter_table("source_documents") as batch:
        batch.drop_column("text_source")
