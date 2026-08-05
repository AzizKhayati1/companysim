"""companysim.ingest — real-document ingestion for the Digital Workforce Twin.

Turns uploaded HR documents (roster exports, performance reviews,
resignation letters) into *staged, human-reviewable* changes to a
persisted org — never direct writes. DB-agnostic by design, like ``ml/``:
everything here consumes and produces plain values; the webapp glue that
touches SQLAlchemy lives in ``api/ingest_records.py`` and
``api/routers/ingest.py``.
"""
