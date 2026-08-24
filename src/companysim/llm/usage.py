"""Token accounting for Groq calls — recorded here, persisted by the API.

The three LLM features live in modules with different rules about the
database: ``ml/llm_exit_notes.py`` and ``ingest/llm_parser.py`` are
DB-agnostic by design (same separation ``ml/gate.py`` keeps), while
``api/org_chat.py`` sits in the webapp layer. Having each of them write a
usage row directly would drag a ``Session`` into ``ml/`` and ``ingest/``,
which is exactly the coupling those modules were written to avoid.

So this module is a *sink*, not a writer. A call site records a
:class:`LlmCall` and knows nothing about where it goes; the router that
started the work opens a :func:`collect` block and hands whatever
accumulated to ``api.llm_usage`` to persist. Outside a ``collect`` block
recording is a no-op, so the CLI, the offline pipeline and the test suite
all keep working with no sink at all.

The sink is a :class:`~contextvars.ContextVar` rather than a module-level
list because FastAPI runs sync endpoints in a threadpool — a plain global
would interleave two concurrent requests' tokens into one bill. A
ContextVar is per-request under both the async and threadpool paths.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

# Feature labels — the granularity the usage dashboard groups by. Kept as
# constants so a typo can't silently create a fourth category.
FEATURE_EXIT_NOTES = "exit_notes"
FEATURE_CHAT = "chat"
FEATURE_INGEST = "ingest"
# OCR runs at *upload* rather than at extraction, so its spend would
# otherwise be invisible next to the extraction it enables.
FEATURE_OCR = "ocr"


@dataclass(frozen=True)
class LlmCall:
    """One completed request to the model.

    ``total_tokens`` is taken from the provider rather than summed locally:
    Groq bills on its own count, and for tool-calling turns the two parts
    don't always add up to it exactly. When the response carries no usage
    block at all (older stubs, or a mocked client in tests) every field is
    0 — a call that happened but reported nothing, which is honest, and
    distinguishable from no call at all because the row still exists.
    """

    feature: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


_SINK: ContextVar[list[LlmCall] | None] = ContextVar("companysim_llm_usage_sink", default=None)


def record(call: LlmCall) -> None:
    """Add ``call`` to the active sink, or do nothing if there isn't one."""
    sink = _SINK.get()
    if sink is not None:
        sink.append(call)


def record_response(response: Any, *, feature: str, model: str) -> None:
    """Record straight from a raw Groq response object.

    Tolerates a response with no ``usage`` attribute rather than raising —
    a token counter must never be the reason a working feature breaks.

    Prefer :func:`record_completion` at call sites: it takes the
    provider-normalized :class:`~companysim.llm.provider.ChatResponse`, so
    it reports the same numbers whether Groq or Bedrock served the call.
    This function remains for anything holding a raw SDK object.
    """
    usage = getattr(response, "usage", None)
    record(LlmCall(
        feature=feature,
        model=model,
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    ))


def record_completion(response: Any, *, feature: str) -> None:
    """Record a normalized ``ChatResponse``.

    The model name comes off the response rather than from the caller, so
    a usage row always names the model that actually served the request —
    which is the whole point of the row once two providers are in play and
    the answer is a deployment setting rather than a constant in the code.
    """
    usage = getattr(response, "usage", None)
    record(LlmCall(
        feature=feature,
        model=str(getattr(response, "model", "") or ""),
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    ))


@contextmanager
def collect() -> Iterator[list[LlmCall]]:
    """Capture every :func:`record` made inside the block.

    The list is live — a caller can read it after the block exits. Nesting
    is safe: the inner block's calls go only to the inner list, and the
    token reset restores the outer sink.
    """
    calls: list[LlmCall] = []
    token = _SINK.set(calls)
    try:
        yield calls
    finally:
        _SINK.reset(token)
