"""Document kinds + deterministic text extraction — the no-LLM front door.

Everything downstream of upload (rules parser today, LLM parser in a later
phase) consumes plain text, so this module's job is to get bytes to text
deterministically and refuse loudly on anything it can't handle — an
unsupported upload should fail at the door with a clear message, not
produce an empty extraction that looks like a parser bug later. Mirrors
``ml/exit_notes.py``'s stance of keeping the deterministic path free of
any API key or external service: .txt/.md/.csv are decoded directly and
.pdf goes through ``pypdf`` (the read-side counterpart of ``fpdf2``,
which is write-only), all offline.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath


class DocumentKind(StrEnum):
    ROSTER = "roster"
    PERFORMANCE_REVIEW = "performance_review"
    RESIGNATION_LETTER = "resignation_letter"
    PULSE_EXPORT = "pulse_export"
    # Hiring documents. Both describe someone who is *not yet* in the org
    # and both resolve to the same staged ``new_hire`` proposal a roster row
    # produces, so approval creates the employee through one code path
    # rather than three (see ``ingest.reconcile.NEW_HIRE_FIELD``).
    OFFER_LETTER = "offer_letter"
    CV = "cv"


_TEXT_SUFFIXES = {".txt", ".md", ".csv"}


def extract_text(filename: str, data: bytes) -> str:
    """Plain text from an uploaded file, or ``ValueError`` on a type we
    don't support — callers surface that message verbatim to the uploader.
    """
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        # utf-8-sig first: Excel's CSV export prepends a BOM that would
        # otherwise survive into the first header name and break matching.
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    if suffix == ".pdf":
        return _extract_pdf_text(data)
    raise ValueError(
        f"Unsupported document type '{suffix or filename}' — "
        "supported: .txt, .md, .csv, .pdf"
    )


def _extract_pdf_text(data: bytes) -> str:
    from io import BytesIO  # noqa: PLC0415

    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ValueError(
            "PDF support requires the 'pypdf' package (installed with the 'api' extra)."
        ) from exc

    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError(
            "No extractable text in PDF — scanned/image-only PDFs are not supported."
        )
    return text
