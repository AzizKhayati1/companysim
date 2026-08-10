"""Tests for the Groq/Bedrock provider abstraction.

The risk this module guards against is subtle: every LLM feature here
fails *silently by design* (extraction returns ``None``, exit notes fall
back to templates, chat reports an outage). So a broken Bedrock
translation would not raise anywhere — it would look exactly like a model
that kept declining. Nothing but a test can tell those apart, which is why
the translation is asserted structurally rather than through the features.

No network: ``boto3.client`` is stubbed, so these run in CI with no AWS
account, no credentials and no region.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from companysim.llm import provider
from companysim.llm.usage import FEATURE_CHAT, collect, record_completion


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "COMPANYSIM_LLM_PROVIDER", "COMPANYSIM_BEDROCK_MODEL_ID",
        "COMPANYSIM_GROQ_MODEL_ID", "GROQ_API_KEY",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION", "AWS_REGION", "AWS_PROFILE",
    ):
        monkeypatch.delenv(var, raising=False)


# ---- provider selection -------------------------------------------------


def test_defaults_to_groq_so_an_existing_env_keeps_working():
    assert provider.active_provider() == provider.PROVIDER_GROQ
    assert provider.model_id() == provider.DEFAULT_GROQ_MODEL


def test_bedrock_is_opt_in_by_exact_value(monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    assert provider.active_provider() == provider.PROVIDER_BEDROCK
    assert provider.model_id() == provider.DEFAULT_BEDROCK_MODEL


def test_an_unrecognized_provider_falls_back_to_groq_not_an_error(monkeypatch):
    # A typo must not silently disable every LLM feature at 3am; the safe
    # reading of a bad value is "the default", not "nothing".
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrok")
    assert provider.active_provider() == provider.PROVIDER_GROQ


def test_model_id_is_overridable_per_provider(monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("COMPANYSIM_BEDROCK_MODEL_ID", "eu.anthropic.custom-v1:0")
    assert provider.model_id() == "eu.anthropic.custom-v1:0"


# ---- readiness ----------------------------------------------------------


def test_groq_needs_a_key(monkeypatch):
    pytest.importorskip("groq")
    assert provider.provider_ready() is False
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert provider.provider_ready() is True


def test_bedrock_readiness_follows_boto3_not_env_vars(monkeypatch):
    """An IAM role sets no environment variables at all, so readiness has
    to ask boto3 what it resolved rather than looking for keys."""
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")  # separately required

    monkeypatch.setattr(
        boto3, "Session",
        lambda *a, **k: types.SimpleNamespace(get_credentials=lambda: None))
    assert provider.provider_ready() is False

    monkeypatch.setattr(
        boto3, "Session",
        lambda *a, **k: types.SimpleNamespace(get_credentials=lambda: object()))
    assert provider.provider_ready() is True


def test_is_enabled_requires_both_the_flag_and_the_provider(monkeypatch):
    pytest.importorskip("groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert provider.is_enabled("SOME_FLAG") is False
    monkeypatch.setenv("SOME_FLAG", "1")
    assert provider.is_enabled("SOME_FLAG") is True


def test_missing_sdk_reports_not_ready(monkeypatch):
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setitem(sys.modules, "boto3", None)  # import boto3 -> ImportError
    assert provider.provider_ready() is False


def test_bedrock_without_a_region_is_not_ready(monkeypatch):
    """No region means no call can ever succeed, so the honest report is
    'not configured' rather than every document failing separately."""
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(
        boto3, "Session",
        lambda *a, **k: types.SimpleNamespace(get_credentials=lambda: object()))
    assert provider.provider_ready() is False
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    assert provider.provider_ready() is True


# ---- the diagnosis users actually read ----------------------------------


def test_configuring_aws_without_switching_provider_says_so(monkeypatch):
    """The regression that prompted this: AWS credentials set, provider
    left at its default, and the old message told the user to set a Groq
    key — advice for a problem they did not have, hiding the one they did.
    """
    pytest.importorskip("groq")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("COMPANYSIM_LLM_INGEST", "1")

    reason = provider.unavailable_reason("COMPANYSIM_LLM_INGEST")
    assert reason is not None
    assert "COMPANYSIM_LLM_PROVIDER=bedrock" in reason


def test_the_flag_is_reported_before_the_provider(monkeypatch):
    # Nothing else can be wrong yet if the feature was never turned on.
    reason = provider.unavailable_reason("COMPANYSIM_LLM_INGEST")
    assert reason == "COMPANYSIM_LLM_INGEST=1 is not set."


def test_a_missing_region_is_named_specifically(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("COMPANYSIM_LLM_INGEST", "1")
    monkeypatch.setattr(
        boto3, "Session",
        lambda *a, **k: types.SimpleNamespace(get_credentials=lambda: object()))
    reason = provider.unavailable_reason("COMPANYSIM_LLM_INGEST")
    assert "AWS_DEFAULT_REGION" in reason


def test_missing_bedrock_credentials_are_named_specifically(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("COMPANYSIM_LLM_INGEST", "1")
    monkeypatch.setattr(
        boto3, "Session",
        lambda *a, **k: types.SimpleNamespace(get_credentials=lambda: None))
    reason = provider.unavailable_reason("COMPANYSIM_LLM_INGEST")
    assert "AWS_ACCESS_KEY_ID" in reason
    assert "bedrock" in reason


def test_a_working_config_has_no_reason(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv("COMPANYSIM_LLM_INGEST", "1")
    monkeypatch.setattr(
        boto3, "Session",
        lambda *a, **k: types.SimpleNamespace(get_credentials=lambda: object()))
    assert provider.unavailable_reason("COMPANYSIM_LLM_INGEST") is None


def test_no_user_facing_message_hardcodes_groq():
    """Guards the actual regression: a provider-specific string baked into
    a message shown to everyone, whichever provider they configured."""
    from pathlib import Path

    src = Path(provider.__file__).resolve().parents[1]
    for rel in ("api/routers/ingest.py", "api/routers/chat.py"):
        text = (src / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "GROQ_API_KEY" not in line:
                continue
            pytest.fail(f"{rel} mentions GROQ_API_KEY outside a comment: {stripped}")


# ---- JSON handling ------------------------------------------------------


@pytest.mark.parametrize("raw", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    '```\n{"a": 1}\n```',
    '   {"a": 1}   ',
])
def test_fenced_json_is_recovered(raw):
    """Groq's JSON mode guarantees bare JSON; Bedrock has no such mode and
    Claude wraps in a fence even when told not to."""
    assert provider.parse_json_object(raw) == {"a": 1}


@pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]", '"a string"'])
def test_non_objects_parse_to_none(raw):
    assert provider.parse_json_object(raw) is None


# ---- Converse translation ----------------------------------------------


def test_system_prompt_moves_out_of_the_message_list():
    system, messages = provider._to_converse([
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
    ])
    assert system == [{"text": "be helpful"}]
    assert messages == [{"role": "user", "content": [{"text": "hi"}]}]


def test_tool_calls_become_tooluse_blocks():
    _, messages = provider._to_converse([
        {"role": "assistant", "content": "thinking",
         "tool_calls": [{"id": "t1", "function": {
             "name": "get_org_overview", "arguments": '{"top_k": 3}'}}]},
    ])
    blocks = messages[0]["content"]
    assert blocks[0] == {"text": "thinking"}
    assert blocks[1]["toolUse"] == {
        "toolUseId": "t1", "name": "get_org_overview", "input": {"top_k": 3},
    }


def test_consecutive_tool_results_merge_into_one_user_turn():
    """Converse rejects two user messages in a row, but the chat loop
    appends one ``role="tool"`` message per parallel call — so they have to
    be folded together or a multi-tool turn is a hard API error."""
    _, messages = provider._to_converse([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "function": {"name": "f", "arguments": "{}"}},
            {"id": "b", "function": {"name": "g", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "a", "content": "ra"},
        {"role": "tool", "tool_call_id": "b", "content": "rb"},
    ])
    tool_turns = [m for m in messages if m["role"] == "user"]
    assert len(tool_turns) == 1
    assert [b["toolResult"]["toolUseId"] for b in tool_turns[0]["content"]] == ["a", "b"]


def test_assistant_turn_with_no_content_and_no_calls_is_dropped():
    # Converse rejects a message whose content list is empty.
    _, messages = provider._to_converse([{"role": "assistant", "content": None}])
    assert messages == []


def test_openai_tool_schema_becomes_a_toolspec():
    config = provider._to_converse_tools([{
        "type": "function",
        "function": {
            "name": "get_top_at_risk_employees",
            "description": "ranked list",
            "parameters": {"type": "object", "properties": {"top_k": {"type": "integer"}},
                           "required": []},
        },
    }])
    spec = config["tools"][0]["toolSpec"]
    assert spec["name"] == "get_top_at_risk_employees"
    assert spec["description"] == "ranked list"
    assert spec["inputSchema"]["json"]["properties"] == {"top_k": {"type": "integer"}}


# ---- Bedrock responses --------------------------------------------------


def _stub_bedrock(monkeypatch, response: dict, captured: dict | None = None):
    boto3 = pytest.importorskip("boto3")

    def converse(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return response

    def client(name, **kwargs):
        assert name == "bedrock-runtime"
        return types.SimpleNamespace(converse=converse)

    monkeypatch.setattr(boto3, "client", client)
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")


def test_text_and_usage_are_normalized(monkeypatch):
    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [{"text": '{"rating": 4}'}]}},
        "usage": {"inputTokens": 120, "outputTokens": 30, "totalTokens": 150},
    })
    r = provider.complete([{"role": "user", "content": "x"}], json_mode=True)
    assert r.text == '{"rating": 4}'
    assert (r.usage.prompt_tokens, r.usage.completion_tokens, r.usage.total_tokens) == (120, 30, 150)
    assert r.model == provider.DEFAULT_BEDROCK_MODEL


def test_bedrock_tool_use_is_normalized_to_toolcall(monkeypatch):
    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [
            {"text": "let me look"},
            {"toolUse": {"toolUseId": "tu1", "name": "get_org_overview", "input": {}}},
        ]}},
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
    })
    r = provider.complete([{"role": "user", "content": "x"}], tools=[
        {"type": "function", "function": {"name": "get_org_overview",
                                          "description": "d", "parameters": {}}},
    ])
    assert r.text == "let me look"
    assert len(r.tool_calls) == 1
    call = r.tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("tu1", "get_org_overview", {})


def test_bedrock_arguments_arrive_parsed_not_as_a_string(monkeypatch):
    """Groq hands back a JSON string and Bedrock hands back a dict. The
    chat loop calls ``fn(**tc.arguments)``, so normalizing to a dict is
    what stops one provider raising TypeError on every tool call."""
    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [
            {"toolUse": {"toolUseId": "t", "name": "f", "input": {"top_k": 5}}}]}},
        "usage": {},
    })
    r = provider.complete([{"role": "user", "content": "x"}])
    assert r.tool_calls[0].arguments == {"top_k": 5}


def test_inference_config_and_tools_reach_converse(monkeypatch):
    captured: dict = {}
    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [{"text": "ok"}]}}, "usage": {},
    }, captured)
    provider.complete(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "f", "description": "",
                                                 "parameters": {}}}],
        max_tokens=64, temperature=0.0,
    )
    assert captured["inferenceConfig"] == {"maxTokens": 64, "temperature": 0.0}
    assert captured["system"] == [{"text": "sys"}]
    assert captured["toolConfig"]["tools"][0]["toolSpec"]["name"] == "f"
    assert captured["modelId"] == provider.DEFAULT_BEDROCK_MODEL


def test_a_missing_usage_block_records_zeros_not_a_crash(monkeypatch):
    _stub_bedrock(monkeypatch, {"output": {"message": {"content": [{"text": "hi"}]}}})
    r = provider.complete([{"role": "user", "content": "x"}])
    assert r.usage.total_tokens == 0


# ---- usage attribution --------------------------------------------------


def test_usage_rows_name_the_model_that_actually_served_the_call(monkeypatch):
    """Once the model is a deployment setting, a usage row that hardcodes
    it is worse than useless — it would attribute Bedrock spend to Groq."""
    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [{"text": "hi"}]}},
        "usage": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10},
    })
    monkeypatch.setenv("COMPANYSIM_BEDROCK_MODEL_ID", "eu.anthropic.some-model-v1:0")

    with collect() as calls:
        record_completion(
            provider.complete([{"role": "user", "content": "x"}]), feature=FEATURE_CHAT)

    assert len(calls) == 1
    assert calls[0].model == "eu.anthropic.some-model-v1:0"
    assert calls[0].total_tokens == 10


# ---- the features, over Bedrock ----------------------------------------


def test_document_extraction_works_over_bedrock(monkeypatch):
    """End-to-end through the real extract function, fenced JSON and all —
    the combination that would break if either half regressed."""
    from companysim.ingest import llm_parser

    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [{"text": json.dumps({
            "employee_email": "a@b.com",
            "review_period_end": "2025-12-31",
            "rating": 4.0,
            "summary_text": "solid half",
        })}]}},
        "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
    })
    monkeypatch.setenv(llm_parser._FLAG_VAR, "1")

    result = llm_parser.extract_performance_review("some review text")
    assert result is not None
    assert result.employee_email == "a@b.com"
    assert result.rating == 4.0


def test_a_bedrock_refusal_still_stages_nothing(monkeypatch):
    """The ``{"error": ...}`` refusal contract is provider-independent —
    it is what stops a half-read document writing a wrong model feature."""
    from companysim.ingest import llm_parser

    _stub_bedrock(monkeypatch, {
        "output": {"message": {"content": [
            {"text": '{"error": "no rating stated"}'}]}},
        "usage": {},
    })
    monkeypatch.setenv(llm_parser._FLAG_VAR, "1")
    assert llm_parser.extract_performance_review("a development conversation") is None


def test_a_bedrock_api_error_is_swallowed_into_none(monkeypatch):
    from companysim.ingest import llm_parser
    boto3 = pytest.importorskip("boto3")

    def boom(name, **kwargs):
        raise RuntimeError("ValidationException: model not found")

    monkeypatch.setattr(boto3, "client", boom)
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setenv(llm_parser._FLAG_VAR, "1")

    assert llm_parser.extract_performance_review("text") is None


def test_exit_notes_fall_back_when_bedrock_fails(monkeypatch):
    from companysim.ml import llm_exit_notes
    boto3 = pytest.importorskip("boto3")

    def boom(name, **kwargs):
        raise RuntimeError("AccessDeniedException")

    monkeypatch.setattr(boto3, "client", boom)
    monkeypatch.setenv("COMPANYSIM_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")

    assert llm_exit_notes.generate_note_via_llm({"workload_perceived": 0.95}) is None
