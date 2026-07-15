"""SQLite persistence for the webapp — a live, editable org store.

Distinct from the CSV/Parquet exports in ``data/generated/``: those are
one-shot offline datasets, this is mutable state the API reads and writes
on every request, so an edited company survives across sessions.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = Path("data") / "app.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Bring the DB schema up to date via Alembic migrations.

    Runs on every app startup (see ``main.py``'s lifespan) — a no-op if
    already at head, or applies pending migrations on a fresh/stale DB.
    Replaces a bare ``Base.metadata.create_all()``, which had no schema
    versioning and let the DB silently drift out of sync with the ORM
    models (see migrations/README and pyproject.toml's alembic dependency).
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
