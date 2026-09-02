"""Optical character recognition — photographed and scanned paper.

The pipeline already turns bytes into text for every format it accepts
(``ingest/documents.py``), and everything downstream consumes that text.
So paper is not a new pipeline: it is a new way of producing the same
string. A photograph of a resignation letter becomes the same
``raw_text`` a typed one would have produced, and goes through the same
extraction, the same staging table and the same human review.

That is why OCR lives here rather than beside the LLM parser. It is a
*decoder*, on a level with ``utf-8-sig`` and ``pypdf``; putting it
anywhere else would create a second route into the database.

**Where it runs matters for cost.** ``raw_text`` is persisted on the
document row at upload, so a page is transcribed exactly once however many
times it is later re-extracted. Running OCR at extraction time instead
would re-bill every retry.

Four backends, chosen at runtime:

``groq``
    A vision model through Groq's OpenAI-compatible chat API, reusing the
    same key and model extraction already uses. Same trade as Bedrock —
    it reads for meaning rather than glyph by glyph, so it copes with
    skew and handwriting and must be told to transcribe rather than
    summarise.

``bedrock``
    A vision model through the Converse API. Reuses the credentials,
    region and model already configured for extraction, so on a Bedrock
    deployment it needs no extra setup and no extra IAM permission. Best
    on skewed, messy or handwritten pages, because it reads for meaning
    rather than glyph by glyph — which is also why it must be instructed
    to transcribe rather than summarise.

``textract``
    Purpose-built AWS OCR. Cheaper per page and stronger on dense
    machine-printed text, but needs its own ``textract:*`` permission.

``tesseract``
    Local, offline, free. No credentials and no per-page cost, so it is
    the right choice for a bulk archive and the only one usable with no
    network. Needs the Tesseract *binary*, not merely the Python package —
    a distinction that otherwise surfaces as a confusing runtime error, so
    it is checked for explicitly.
"""
from __future__ import annotations

import os

from companysim.llm.usage import FEATURE_OCR, LlmCall, record

PROVIDER_GROQ = "groq"
PROVIDER_BEDROCK = "bedrock"
PROVIDER_TEXTRACT = "textract"
PROVIDER_TESSERACT = "tesseract"
PROVIDER_OFF = "off"

_PROVIDER_VAR = "COMPANYSIM_OCR_PROVIDER"

# Converse accepts these four formats; anything else has to go to Textract
# or Tesseract. Kept separate from the broader set below so an error can
# say which backend would have handled the file.
_BEDROCK_FORMATS = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg",
                    "gif": "gif", "webp": "webp"}

# Groq takes a data: URI, so the payload is the base64 expansion of the
# file — about 4/3 of its size. Its own limit is on the encoded form.
_GROQ_FORMATS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "gif": "image/gif", "webp": "image/webp"}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"}

# Both AWS paths reject oversized payloads server-side with a generic
# error; failing here instead names the actual problem.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Returned verbatim by the vision model when a page carries no legible
# text. A sentinel rather than an empty reply, because an empty reply is
# also what a failed call produces and the two need different messages.
NO_TEXT_SENTINEL = "NO_TEXT_FOUND"

_TRANSCRIBE_PROMPT = (
    "Transcribe every piece of text visible in this image, exactly as written.\n"
    "\n"
    "Rules:\n"
    "- Reproduce the text verbatim. Do not summarise, translate, correct "
    "spelling, or reformat.\n"
    "- Preserve line breaks and reading order. Keep tabular data as aligned rows.\n"
    "- Include headers, footers, dates, signatures and handwritten annotations.\n"
    "- Add no commentary, headings or explanation of your own.\n"
    "- If a word is genuinely illegible, write [illegible] rather than guessing.\n"
    "- If the image contains no legible text at all, reply with exactly "
    + NO_TEXT_SENTINEL + ".\n"
    "\n"
    "Return only the transcription."
)


def suffix_is_image(suffix: str) -> bool:
    return suffix.lower() in IMAGE_SUFFIXES


def _has(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def _groq_ready() -> bool:
    return bool(os.environ.get("GROQ_API_KEY")) and _has("groq")


def _aws_ready() -> bool:
    if not _has("boto3"):
        return False
    if not (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")):
        return False
    try:
        import boto3  # noqa: PLC0415

        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def _tesseract_ready() -> bool:
    """Both the wrapper and the binary.

    pytesseract imports cleanly with no Tesseract installed and only fails
    at call time, so checking the import alone would report an unusable
    backend as available.
    """
    if not (_has("pytesseract") and _has("PIL")):
        return False
    try:
        import pytesseract  # noqa: PLC0415

        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def active_provider() -> str:
    """Which backend will transcribe a page.

    Unset auto-selects whichever service is already configured for
    extraction — Groq or AWS — because a deployment doing extraction
    already holds those credentials, and asking someone to set up a second
    service for the same document would be friction with nothing behind
    it. Falls back to a local Tesseract when one is installed.

    Groq is checked first only because it is the extraction default; an
    AWS-only deployment reaches Bedrock on the next line.
    """
    value = os.environ.get(_PROVIDER_VAR, "").strip().lower()
    if value in {PROVIDER_GROQ, PROVIDER_BEDROCK, PROVIDER_TEXTRACT,
                 PROVIDER_TESSERACT, PROVIDER_OFF}:
        return value
    if _groq_ready():
        return PROVIDER_GROQ
    if _aws_ready():
        return PROVIDER_BEDROCK
    if _tesseract_ready():
        return PROVIDER_TESSERACT
    return PROVIDER_OFF


def ocr_problem() -> str | None:
    """``None`` when a page could be transcribed right now, else one
    specific sentence naming the backend it is talking about. This text
    reaches the uploader verbatim."""
    provider = active_provider()
    if provider == PROVIDER_OFF:
        return (
            "No OCR backend is available, so images cannot be read. Set a "
            "GROQ_API_KEY, or configure AWS credentials and a region for the "
            "Bedrock or Textract backend, or install Tesseract (the binary, "
            "plus `pip install pytesseract pillow`) for offline OCR."
        )
    if provider == PROVIDER_GROQ:
        if not _has("groq"):
            return ("OCR provider is 'groq' but the groq package is not "
                    'installed — run: pip install -e ".[llm]"')
        if not os.environ.get("GROQ_API_KEY"):
            return "OCR provider is 'groq' but GROQ_API_KEY is not set."
        return None
    if provider in {PROVIDER_BEDROCK, PROVIDER_TEXTRACT}:
        if not _has("boto3"):
            return f"OCR provider is '{provider}' but boto3 is not installed."
        if not (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")):
            return (f"OCR provider is '{provider}' but no AWS region is set — "
                    "set AWS_DEFAULT_REGION (e.g. eu-west-2).")
        if not _aws_ready():
            return f"OCR provider is '{provider}' but boto3 resolved no credentials."
        return None
    if not _tesseract_ready():
        return (
            "OCR provider is 'tesseract' but it is not usable. This needs the "
            "Tesseract binary on PATH as well as `pip install pytesseract "
            "pillow` — installing only the Python package is the usual cause."
        )
    return None


def is_available() -> bool:
    return ocr_problem() is None


def image_to_text(data: bytes, suffix: str) -> str:
    """Transcribe one image, or raise ``ValueError`` explaining why not.

    Raises rather than returning ``None`` because the caller is
    ``extract_text``, whose contract is already "text, or a ValueError the
    uploader reads". An unreadable page must not become an empty document:
    that would arrive at review as a successful upload containing nothing,
    which is precisely the failure this pipeline works hardest to avoid
    everywhere else.
    """
    problem = ocr_problem()
    if problem:
        raise ValueError(problem)
    if not data:
        raise ValueError("Empty image file — nothing to transcribe.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image is {len(data) / 1e6:.1f} MB; the limit is "
            f"{MAX_IMAGE_BYTES / 1e6:.0f} MB. Re-save it at a lower resolution — "
            "OCR gains nothing above roughly 300 dpi."
        )

    provider = active_provider()
    fmt = suffix.lower().lstrip(".")
    if provider == PROVIDER_GROQ:
        text = _groq_ocr(data, fmt)
    elif provider == PROVIDER_BEDROCK:
        text = _bedrock_ocr(data, fmt)
    elif provider == PROVIDER_TEXTRACT:
        text = _textract_ocr(data)
    else:
        text = _tesseract_ocr(data)

    text = (text or "").strip()
    if not text or text == NO_TEXT_SENTINEL:
        raise ValueError(
            "No legible text found in the image. Check that the page is in "
            "focus, the right way up, and fills the frame."
        )
    return text


def _groq_ocr(data: bytes, fmt: str) -> str:
    """Transcribe through Groq's vision path.

    The image travels as a base64 data: URI in an ``image_url`` content
    block — the OpenAI-compatible shape — rather than as raw bytes the way
    Converse takes it. That difference is why this is a backend of its own
    and not a branch inside the Bedrock one.
    """
    import base64  # noqa: PLC0415
    import os as _os  # noqa: PLC0415

    from groq import Groq  # noqa: PLC0415

    from companysim.llm import provider as llm_provider  # noqa: PLC0415

    mime = _GROQ_FORMATS.get(fmt)
    if mime is None:
        raise ValueError(
            f"The Groq backend cannot read '.{fmt}' images (it accepts "
            f"{', '.join(sorted(set(_GROQ_FORMATS)))}). Convert the file to "
            "PNG or JPEG, or install Tesseract for offline OCR."
        )

    model = llm_provider.model_id()
    encoded = base64.b64encode(data).decode()
    client = Groq(api_key=_os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        # Transcription is a reading task: the most likely reading of each
        # glyph every time, never a fluent-sounding invention.
        temperature=0.0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _TRANSCRIBE_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ],
        }],
    )

    usage = getattr(response, "usage", None)
    record(LlmCall(
        feature=FEATURE_OCR,
        model=model,
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    ))
    return response.choices[0].message.content or ""


def _bedrock_ocr(data: bytes, fmt: str) -> str:
    from companysim.llm import provider as llm_provider  # noqa: PLC0415

    converse_fmt = _BEDROCK_FORMATS.get(fmt)
    if converse_fmt is None:
        raise ValueError(
            f"The Bedrock backend cannot read '.{fmt}' images (it accepts "
            f"{', '.join(sorted(set(_BEDROCK_FORMATS)))}). Convert the file to "
            "PNG or JPEG, or set COMPANYSIM_OCR_PROVIDER=textract."
        )

    model = llm_provider.model_id()
    response = llm_provider.bedrock_client().converse(
        modelId=model,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": converse_fmt, "source": {"bytes": data}}},
                {"text": _TRANSCRIBE_PROMPT},
            ],
        }],
        # Transcription is a reading task: the most likely reading of each
        # glyph every time, never a fluent-sounding invention.
        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
    )

    usage = response.get("usage", {}) or {}
    record(LlmCall(
        feature=FEATURE_OCR,
        model=model,
        prompt_tokens=int(usage.get("inputTokens", 0) or 0),
        completion_tokens=int(usage.get("outputTokens", 0) or 0),
        total_tokens=int(usage.get("totalTokens", 0) or 0),
    ))

    parts = [
        b["text"]
        for b in response.get("output", {}).get("message", {}).get("content", []) or []
        if "text" in b
    ]
    return "".join(parts)


def _textract_ocr(data: bytes) -> str:
    import boto3  # noqa: PLC0415

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    client = boto3.client("textract", region_name=region or None)
    response = client.detect_document_text(Document={"Bytes": data})
    # One block per detected line, already in reading order.
    return "\n".join(
        b.get("Text", "")
        for b in response.get("Blocks", []) or []
        if b.get("BlockType") == "LINE"
    )


def _tesseract_ocr(data: bytes) -> str:
    from io import BytesIO  # noqa: PLC0415

    import pytesseract  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    return pytesseract.image_to_string(Image.open(BytesIO(data)))
