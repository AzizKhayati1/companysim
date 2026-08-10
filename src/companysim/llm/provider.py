"""Provider abstraction for the three LLM features — Groq or AWS Bedrock.

All three call sites (``ingest/llm_parser.py``, ``ml/llm_exit_notes.py``,
``api/org_chat.py``) were written directly against Groq's OpenAI-compatible
SDK. Bedrock speaks a different wire shape, so rather than branch on the
provider at each site — three copies of the same conditional, drifting
apart the first time one is edited — the difference is absorbed here.

A call site sees one function, :func:`complete`, and one normalized
:class:`ChatResponse`. Which provider serves it is a deployment decision
(``COMPANYSIM_LLM_PROVIDER``), not a code decision.

**Why Bedrock's Converse API and not ``InvokeModel``.** Converse is the
model-agnostic surface: the same request shape works across Claude, Llama
and Titan, it returns a usage block in a single documented place, and it
has first-class tool calling. ``InvokeModel`` would mean hand-writing a
different request body per model family, which is exactly the coupling
this module exists to prevent.

**Credentials are never read by this module.** Bedrock auth goes through
boto3's standard chain, so ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``
work in development while an EC2/ECS/Lambda IAM role works in production
with no key material on disk at all — the better production posture, and
available without a code change because nothing here reads those variables
by name.

**Feature parity is not total, and the gap is deliberate.** Groq's JSON
mode constrains decoding to valid JSON at the sampler; Bedrock's Converse
has no equivalent, so the JSON path there relies on the prompt plus fence
stripping in :func:`extract_json_text`. Both are then validated by the same
pydantic schema, which is the check that actually protects the database —
the difference only changes how often a call is wasted, never whether a
bad value can land.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

PROVIDER_GROQ = "groq"
PROVIDER_BEDROCK = "bedrock"

_PROVIDER_VAR = "COMPANYSIM_LLM_PROVIDER"
_BEDROCK_MODEL_VAR = "COMPANYSIM_BEDROCK_MODEL_ID"
_GROQ_MODEL_VAR = "COMPANYSIM_GROQ_MODEL_ID"

# Defaults are starting points, not guarantees. Bedrock model availability
# varies by region AND by which models an account has been granted, so the
# right value is discovered per-deployment:
#     aws bedrock list-inference-profiles --region eu-west-2
# In EU regions Claude is served through cross-region inference profiles,
# whose ids carry the "eu." prefix — a bare "anthropic.claude-..." id is
# rejected there with a ValidationException, which is the single most
# common first-run failure. `scripts/check_llm_provider.py` names it.
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_BEDROCK_MODEL = "eu.anthropic.claude-sonnet-4-20250514-v1:0"

_TRUTHY = {"1", "true", "yes"}


# --------------------------------------------------------------------------
# normalized types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation requested by the model.

    ``arguments`` is already-parsed JSON. Groq hands back a string and
    Bedrock hands back a dict; normalizing to a dict here means the chat
    loop never has to know which it was talking to.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ChatResponse:
    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    model: str = ""


# --------------------------------------------------------------------------
# provider selection
# --------------------------------------------------------------------------


def active_provider() -> str:
    """Which provider this process is configured to use.

    Defaults to Groq so an existing ``.env`` keeps working untouched after
    a pull — switching is an explicit act, never a side effect of upgrading.
    """
    value = os.environ.get(_PROVIDER_VAR, "").strip().lower()
    return PROVIDER_BEDROCK if value == PROVIDER_BEDROCK else PROVIDER_GROQ


def model_id() -> str:
    """The model this process will call, provider-appropriate."""
    if active_provider() == PROVIDER_BEDROCK:
        return os.environ.get(_BEDROCK_MODEL_VAR, "").strip() or DEFAULT_BEDROCK_MODEL
    return os.environ.get(_GROQ_MODEL_VAR, "").strip() or DEFAULT_GROQ_MODEL


def flag_enabled(flag_var: str) -> bool:
    return os.environ.get(flag_var, "").strip().lower() in _TRUTHY


def provider_problem() -> str | None:
    """``None`` when the active provider could serve a call right now, else
    one specific sentence saying what is missing. Ignores feature flags.

    This text reaches users — it is what an upload's ``needs_review``
    reason says — so it has to be a diagnosis rather than a checklist. A
    generic "needs a key and a flag" message became actively misleading the
    moment a second provider existed: someone who has configured AWS
    credentials but not ``COMPANYSIM_LLM_PROVIDER`` gets told to set a
    *Groq* key, which describes a problem they do not have and hides the
    one they do. So every branch names the active provider first.
    """
    if active_provider() == PROVIDER_BEDROCK:
        try:
            import boto3  # noqa: PLC0415
        except ImportError:
            return ("Provider is 'bedrock' but boto3 is not installed — "
                    'run: pip install -e ".[llm]"')
        if not (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")):
            return ("Provider is 'bedrock' but no AWS region is set. Bedrock's "
                    "endpoint is regional and has no default — set "
                    "AWS_DEFAULT_REGION (e.g. eu-west-2).")
        try:
            resolved = boto3.Session().get_credentials() is not None
        except Exception:
            resolved = False
        if not resolved:
            return ("Provider is 'bedrock' but boto3 resolved no credentials. "
                    "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or "
                    "AWS_PROFILE, or attach an IAM role.")
        return None

    try:
        import groq  # noqa: F401, PLC0415
    except ImportError:
        return ("Provider is 'groq' but the groq package is not installed — "
                'run: pip install -e ".[llm]"')
    if not os.environ.get("GROQ_API_KEY"):
        return ("Provider is 'groq' (the default) but GROQ_API_KEY is not set. "
                "If you meant to use AWS Bedrock, set "
                "COMPANYSIM_LLM_PROVIDER=bedrock — configuring AWS credentials "
                "alone does not switch provider.")
    return None


def provider_ready() -> bool:
    """True when the active provider has everything it needs to make a call.

    Credentials are checked the way each provider actually resolves them:
    Groq needs an env var and nothing else, while Bedrock delegates to
    boto3's chain — so an IAM role with no environment variables at all is
    correctly reported as ready, and a missing role is correctly reported
    as not.

    The region counts as a requirement rather than a detail: without one no
    Bedrock call can succeed, so calling the feature available would mean
    every document failing separately instead of the feature saying plainly
    that it is not configured.
    """
    return provider_problem() is None


def unavailable_reason(flag_var: str) -> str | None:
    """``None`` when the feature can run, else why not — its own flag first,
    then the provider."""
    if not flag_enabled(flag_var):
        return f"{flag_var}=1 is not set."
    return provider_problem()


def is_enabled(flag_var: str) -> bool:
    """The gate every feature uses: its own flag, plus a usable provider."""
    return unavailable_reason(flag_var) is None


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json_text(text: str) -> str:
    """Strip markdown fences a model wrapped around its JSON.

    Groq's JSON mode makes this unnecessary; Bedrock has no such mode and
    Claude in particular likes to answer with a ```json block even when
    told not to. Cheap to apply unconditionally, and it keeps the parsing
    path identical for both providers.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    return cleaned.strip()


def _first_json_object(text: str) -> str | None:
    """The first balanced ``{...}`` in ``text``, or ``None``.

    Brace counting rather than a regex, because a regex cannot tell a brace
    inside a string literal from a structural one — and extraction payloads
    routinely carry prose (``summary_text``, ``note_text``) that can contain
    either a brace or an escaped quote.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_json_object(text: str | None) -> dict | None:
    """Parse a model's reply into a dict, or ``None``.

    Tries the whole (de-fenced) reply first, then falls back to the first
    balanced object embedded in it. That fallback is not sloppiness — it is
    the JSON-mode parity gap made survivable. Groq constrains decoding to
    valid JSON at the sampler, so its replies are always bare; Bedrock's
    Converse API has no equivalent, and a model told "return only JSON"
    still routinely writes "Here is the extracted data:" first or adds a
    closing pleasantry. Without this, those replies parse as nothing and
    the document is parked as unreadable — the tokens spent, the content
    perfectly good, and the reviewer told the model refused when it did not.

    Deliberately *not* solved by forcing a tool call with the target schema,
    which would guarantee structure but destroy the refusal contract: a
    forced call must populate every required field, so a model that should
    have reported a missing rating would invent one instead. Tolerating
    chatter is the cheaper mistake than manufacturing data.
    """
    if not text:
        return None
    cleaned = extract_json_text(text)
    for candidate in (cleaned, _first_json_object(cleaned)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# --------------------------------------------------------------------------
# Groq
# --------------------------------------------------------------------------


def _complete_groq(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    max_tokens: int | None,
    temperature: float | None,
    json_mode: bool,
) -> ChatResponse:
    from groq import Groq  # noqa: PLC0415

    model = model_id()
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = Groq(api_key=os.environ["GROQ_API_KEY"]).chat.completions.create(**kwargs)
    msg = response.choices[0].message
    usage = getattr(response, "usage", None)

    calls: list[ToolCall] = []
    for tc in getattr(msg, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except (ValueError, TypeError):
            args = {}
        calls.append(ToolCall(
            id=tc.id, name=tc.function.name,
            arguments=args if isinstance(args, dict) else {},
        ))

    return ChatResponse(
        text=(msg.content or None),
        tool_calls=tuple(calls),
        usage=Usage(
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        ),
        model=model,
    )


# --------------------------------------------------------------------------
# Bedrock (Converse)
# --------------------------------------------------------------------------


def _bedrock_client():
    import boto3  # noqa: PLC0415

    # Region resolution is boto3's, not ours, except for one fallback: the
    # Bedrock endpoint is regional and an unset region raises NoRegionError
    # rather than defaulting, so a deployment that sets only keys would
    # fail confusingly. AWS_DEFAULT_REGION / AWS_REGION both work.
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return boto3.client("bedrock-runtime", region_name=region or None)


def _to_converse(messages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Translate OpenAI-shaped messages into Converse's shape.

    Converse differs in three ways that all matter here: the system prompt
    is a separate top-level argument rather than a message, tool results
    are user-role content blocks rather than their own role, and content is
    always a list of typed blocks rather than a bare string.
    """
    system: list[dict] = []
    out: list[dict] = []

    for m in messages:
        role = m.get("role")
        content = m.get("content")

        if role == "system":
            if content:
                system.append({"text": str(content)})
            continue

        if role == "tool":
            block = {
                "toolResult": {
                    "toolUseId": m.get("tool_call_id", ""),
                    "content": [{"text": str(content or "")}],
                }
            }
            # Consecutive tool results must be merged into one user turn;
            # Converse rejects two user messages in a row.
            if out and out[-1]["role"] == "user" and any(
                "toolResult" in b for b in out[-1]["content"]
            ):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue

        blocks: list[dict] = []
        if content:
            blocks.append({"text": str(content)})
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (ValueError, TypeError):
                args = {}
            blocks.append({"toolUse": {
                "toolUseId": tc.get("id", ""),
                "name": fn.get("name", ""),
                "input": args if isinstance(args, dict) else {},
            }})
        if not blocks:
            continue
        out.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})

    return system, out


def _to_converse_tools(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """OpenAI ``{"type":"function","function":{...}}`` -> Converse toolSpec."""
    specs = []
    for t in tools:
        fn = t.get("function", t)
        specs.append({"toolSpec": {
            "name": fn.get("name", ""),
            "description": fn.get("description", "") or "",
            "inputSchema": {"json": fn.get("parameters") or {
                "type": "object", "properties": {}, "required": [],
            }},
        }})
    return {"tools": specs}


def _complete_bedrock(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    max_tokens: int | None,
    temperature: float | None,
    json_mode: bool,
) -> ChatResponse:
    model = model_id()
    system, converse_messages = _to_converse(messages)

    inference: dict[str, Any] = {}
    if max_tokens is not None:
        inference["maxTokens"] = max_tokens
    if temperature is not None:
        inference["temperature"] = temperature

    kwargs: dict[str, Any] = {"modelId": model, "messages": converse_messages}
    if system:
        kwargs["system"] = system
    if inference:
        kwargs["inferenceConfig"] = inference
    if tools:
        kwargs["toolConfig"] = _to_converse_tools(tools)

    response = _bedrock_client().converse(**kwargs)

    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in response.get("output", {}).get("message", {}).get("content", []) or []:
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tu = block["toolUse"]
            raw = tu.get("input")
            calls.append(ToolCall(
                id=tu.get("toolUseId", ""),
                name=tu.get("name", ""),
                arguments=raw if isinstance(raw, dict) else {},
            ))

    usage = response.get("usage", {}) or {}
    text = "".join(text_parts) or None
    return ChatResponse(
        text=text,
        tool_calls=tuple(calls),
        usage=Usage(
            prompt_tokens=int(usage.get("inputTokens", 0) or 0),
            completion_tokens=int(usage.get("outputTokens", 0) or 0),
            total_tokens=int(usage.get("totalTokens", 0) or 0),
        ),
        model=model,
    )


# --------------------------------------------------------------------------
# the one entry point
# --------------------------------------------------------------------------


def complete(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    json_mode: bool = False,
) -> ChatResponse:
    """Send an OpenAI-shaped conversation to whichever provider is active.

    ``messages``, ``tools`` and the returned tool calls all use the
    OpenAI shape because that is what the existing call sites already
    speak; the Bedrock backend translates in both directions. Errors are
    *not* swallowed here — each feature has its own failure policy (exit
    notes fall back to templates, extraction refuses, chat surfaces an
    outage) and flattening those into one behaviour here would take that
    choice away from them.
    """
    if active_provider() == PROVIDER_BEDROCK:
        return _complete_bedrock(
            messages, tools=tools, max_tokens=max_tokens,
            temperature=temperature, json_mode=json_mode,
        )
    return _complete_groq(
        messages, tools=tools, max_tokens=max_tokens,
        temperature=temperature, json_mode=json_mode,
    )
