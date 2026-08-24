"""Document kinds + text extraction — the front door.

Everything downstream of upload (the rules parser, the LLM parser)
consumes plain text, so this module's job is to get bytes to text and
refuse loudly on anything it can't handle — an unsupported upload should
fail at the door with a clear message, not produce an empty extraction
that looks like a parser bug later.

Two of the three routes need no service at all: .txt/.md/.csv are decoded
directly, and .pdf goes through ``pypdf`` (the read-side counterpart of
``fpdf2``, which is write-only), both offline. Photographs and scans need
``ingest/ocr.py``, and are the only route that can cost money.

Callers get the text *and how it was obtained*
(:func:`extract_text_with_source`), because a transcription is a reading
of a page rather than a copy of it: it can misread a digit in a salary in
a way a decoded CSV cannot, and the review UI lowers confidence
accordingly. Losing that distinction at the door would make it
unrecoverable later.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath

from companysim.ingest import ocr


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


#: How ``raw_text`` was obtained. Stored on the document row.
SOURCE_NATIVE = "native"


def ocr_source(provider: str) -> str:
    return f"ocr:{provider}"


def is_ocr_source(text_source: str | None) -> bool:
    return bool(text_source) and str(text_source).startswith("ocr")


_TEXT_SUFFIXES = {".txt", ".md", ".csv"}

# Below this, a PDF's text layer is treated as absent rather than sparse.
# A scanned page often carries a few characters of junk from a stamp or a
# fax header, so "any text at all" is the wrong test — it would skip OCR
# on exactly the pages that need it.
_MIN_PDF_TEXT_CHARS = 40


def extract_text(filename: str, data: bytes) -> str:
    """Plain text, or ``ValueError`` on a type we can't handle."""
    return extract_text_with_source(filename, data)[0]


def extract_text_with_source(filename: str, data: bytes) -> tuple[str, str]:
    """``(text, source)`` where source is ``native`` or ``ocr:<backend>``."""
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()

    if suffix in _TEXT_SUFFIXES:
        # utf-8-sig first: Excel's CSV export prepends a BOM that would
        # otherwise survive into the first header name and break matching.
        try:
            return data.decode("utf-8-sig"), SOURCE_NATIVE
        except UnicodeDecodeError:
            return data.decode("latin-1"), SOURCE_NATIVE

    if ocr.suffix_is_image(suffix):
        return ocr.image_to_text(data, suffix), ocr_source(ocr.active_provider())

    if suffix == ".pdf":
        return _extract_pdf(data)

    supported = ", ".join([".txt", ".md", ".csv", ".pdf", *sorted(ocr.IMAGE_SUFFIXES)])
    raise ValueError(
        f"Unsupported document type '{suffix or filename}' — supported: {supported}"
    )


def _extract_pdf(data: bytes) -> tuple[str, str]:
    """A PDF's text layer, falling back to OCR of its page images.

    The fallback matters more than it looks: a PDF produced by a scanner or
    a phone's document mode is a picture in a PDF wrapper and carries no
    text layer at all. Before OCR existed that was a dead end, and it is
    one of the commonest ways paper actually arrives — so the same file
    that used to be refused now goes through the image path instead.
    """
    from io import BytesIO  # noqa: PLC0415

    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ValueError(
            "PDF support requires the 'pypdf' package (installed with the 'api' extra)."
        ) from exc

    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if len(text) >= _MIN_PDF_TEXT_CHARS:
        return text, SOURCE_NATIVE

    if not ocr.is_available():
        raise ValueError(
            "This PDF has no extractable text layer, so it is a scan or a "
            f"photograph. Reading it needs OCR, which is unavailable: {ocr.ocr_problem()}"
        )

    pages: list[str] = []
    for n, page in enumerate(reader.pages, 1):
        for image in page.images:
            suffix = PurePosixPath(image.name or "page.png").suffix or ".png"
            try:
                pages.append(ocr.image_to_text(image.data, suffix))
            except ValueError:
                # One unreadable page must not discard the rest — a blank
                # separator sheet in the middle of a scan is common.
                continue
        if not pages and n == len(reader.pages):
            break

    joined = "\n".join(p for p in pages if p).strip()
    if not joined:
        raise ValueError(
            "This PDF has no text layer and no page image could be transcribed. "
            "If it is a scan, try exporting the pages as PNG or JPEG and "
            "uploading those instead."
        )
    return joined, ocr_source(ocr.active_provider())
