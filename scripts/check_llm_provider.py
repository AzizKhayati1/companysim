"""Preflight the configured LLM provider and say exactly what is wrong.

Run this before trusting a fresh machine, and after any change to
``.env``::

    .venv/Scripts/python scripts/check_llm_provider.py      # Windows
    .venv/bin/python scripts/check_llm_provider.py          # macOS/Linux

Why this exists rather than "just try the app": every LLM feature in this
codebase fails *quietly* by design. Extraction returns ``None`` and parks
the document as ``needs_review``; exit notes fall back to templates; chat
shows "temporarily unavailable". Those are the right behaviours in
production — a model outage must never take down a page — but they make a
misconfiguration indistinguishable from a model that simply declined. This
script removes that ambiguity by checking each layer separately and making
one real call, so a failure names the layer that failed.

Exits 0 when a real call succeeded, 1 otherwise.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from companysim.llm import provider  # noqa: E402

OK = "  OK  "
BAD = " FAIL "
WARN = " WARN "

_FEATURE_FLAGS = {
    "COMPANYSIM_LLM_INGEST": "document extraction",
    "COMPANYSIM_LLM_EXIT_NOTES": "LLM exit notes",
    "COMPANYSIM_LLM_CHAT": "Ask Vantage chat",
}


def line(status: str, text: str) -> None:
    print(f"[{status}] {text}")


def fail(text: str, *hints: str) -> int:
    line(BAD, text)
    for h in hints:
        print(f"         -> {h}")
    return 1


def check_sdk(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def check_bedrock() -> int:
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

    if not check_sdk("boto3"):
        return fail(
            "boto3 is not installed",
            'pip install -e ".[dev,ml,viz,api,llm]"',
        )
    line(OK, "boto3 installed")

    if not region:
        return fail(
            "no AWS region set",
            "Bedrock's endpoint is regional and does not default.",
            "Set AWS_DEFAULT_REGION=eu-west-2 in .env",
        )
    line(OK, f"region {region}")

    import boto3  # noqa: PLC0415
    from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        return fail(
            "boto3 resolved no credentials",
            "Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY in .env,",
            "or AWS_PROFILE for a profile from `aws configure`,",
            "or attach an IAM role if this is an EC2/ECS host.",
        )
    line(OK, f"credentials resolved via {creds.method}")

    # Prove the credentials are real before blaming the model id — an
    # expired key and a wrong model id both surface as an opaque error on
    # the converse() call, and they need opposite fixes.
    try:
        who = boto3.client("sts", region_name=region).get_caller_identity()
        line(OK, f"STS identity {who.get('Arn', '?')}")
    except (ClientError, BotoCoreError) as exc:
        return fail(
            f"credentials rejected by STS: {exc.__class__.__name__}",
            str(exc).strip()[:200],
            "The keys are wrong, expired, or disabled — fix those before",
            "looking at Bedrock or the model id.",
        )

    model = provider.model_id()
    line(OK, f"model id {model}")
    if model.startswith("anthropic.") and region.startswith("eu-"):
        line(WARN, "an EU region usually needs the 'eu.' inference-profile prefix")
        print("         -> try eu." + model)
    return 0


def check_groq() -> int:
    if not check_sdk("groq"):
        return fail("the groq package is not installed",
                    'pip install -e ".[dev,ml,viz,api,llm]"')
    line(OK, "groq installed")
    if not os.environ.get("GROQ_API_KEY"):
        return fail("GROQ_API_KEY is not set",
                    "Get one free at https://console.groq.com/keys")
    line(OK, "GROQ_API_KEY present")
    line(OK, f"model id {provider.model_id()}")
    return 0


def live_call() -> int:
    print("\n--- live call ---")
    try:
        response = provider.complete(
            [{"role": "user", "content":
              'Reply with exactly this JSON and nothing else: {"ok": true}'}],
            max_tokens=64,
            temperature=0.0,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - the whole point is to report it
        name = exc.__class__.__name__
        text = str(exc)
        hints: list[str] = [text.strip()[:300]]
        low = text.lower()
        if "accessdenied" in low or "not authorized" in low:
            hints += [
                "The identity is valid but lacks bedrock:InvokeModel.",
                "Attach a policy allowing bedrock:InvokeModel (and",
                "bedrock:InvokeModelWithResponseStream) on the model arn.",
            ]
        elif "validationexception" in low or "invalid model" in low or "don't have access" in low:
            hints += [
                "Usually a wrong model id, or model access not yet granted.",
                "List what this account can actually call:",
                "  aws bedrock list-inference-profiles --region eu-west-2",
                "Grant access in the Bedrock console under 'Model access'.",
            ]
        elif "throttl" in low or "toomanyrequests" in low:
            hints.append("Rate limited — the config is fine, retry in a moment.")
        elif "could not connect" in low or "endpointconnection" in low:
            hints.append("Network/proxy problem reaching the regional endpoint.")
        return fail(f"the call raised {name}", *hints)

    parsed = provider.parse_json_object(response.text)
    line(OK, f"reply {(response.text or '').strip()[:80]!r}")
    if parsed is None:
        line(WARN, "reply was not parseable JSON (fine for chat, weak for extraction)")
    u = response.usage
    line(OK, f"tokens in={u.prompt_tokens} out={u.completion_tokens} total={u.total_tokens}")
    if u.total_tokens == 0:
        line(WARN, "provider reported no token usage — the meter will read 0")
    return 0


def main() -> int:
    name = provider.active_provider()
    print(f"provider: {name}  (COMPANYSIM_LLM_PROVIDER)")
    print()

    rc = check_bedrock() if name == provider.PROVIDER_BEDROCK else check_groq()
    if rc:
        return rc

    rc = live_call()

    print("\n--- feature flags ---")
    for var, label in _FEATURE_FLAGS.items():
        on = provider.flag_enabled(var)
        line(OK if on else WARN, f"{label}: {'on' if on else 'off'}  ({var})")
    if not any(provider.flag_enabled(v) for v in _FEATURE_FLAGS):
        print("         -> the provider works but every feature is off;")
        print("            set at least one flag to 1 in .env")

    print()
    print("ready" if rc == 0 else "not ready")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
