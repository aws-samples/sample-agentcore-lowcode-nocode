"""Unit tests for Harness models + deployer (Task 11).

No network calls — boto3 client is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.harness_models import (
    BedrockModelConfig,
    HarnessCreateRequest,
    HarnessModelConfig,
    HarnessTool,
    HarnessToolType,
    HarnessTruncationConfig,
    ModelProvider,
    TruncationStrategy,
)


def _req(**overrides) -> HarnessCreateRequest:
    base = dict(
        harness_name="test_harness",
        model=HarnessModelConfig(
            bedrock=BedrockModelConfig(model_id="anthropic.claude-3-haiku-20240307-v1:0")
        ),
    )
    base.update(overrides)
    return HarnessCreateRequest(**base)


def test_name_rule_valid() -> None:
    assert _req(harness_name="ab12_foo").harness_name == "ab12_foo"


def test_name_rule_rejects_digit_start() -> None:
    with pytest.raises(ValueError):
        _req(harness_name="1bad")


def test_name_rule_rejects_hyphen() -> None:
    with pytest.raises(ValueError):
        _req(harness_name="has-hyphen")


def test_name_rule_rejects_too_long() -> None:
    with pytest.raises(ValueError):
        _req(harness_name="a" * 65)


def test_bedrock_model_to_api() -> None:
    cfg = BedrockModelConfig(
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        max_tokens=500,
        temperature=0.2,
    )
    assert cfg.to_api() == {
        "modelId": "anthropic.claude-3-haiku-20240307-v1:0",
        "maxTokens": 500,
        "temperature": 0.2,
    }


def test_model_tagged_union_rejects_empty() -> None:
    with pytest.raises(ValueError):
        HarnessModelConfig().to_api()


def test_remote_mcp_tool_requires_url() -> None:
    with pytest.raises(ValueError):
        HarnessTool(type=HarnessToolType.REMOTE_MCP).to_api()


def test_gateway_tool_requires_arn() -> None:
    with pytest.raises(ValueError):
        HarnessTool(type=HarnessToolType.AGENTCORE_GATEWAY).to_api()


def test_code_interpreter_tool_builds_with_defaults() -> None:
    tool = HarnessTool(type=HarnessToolType.AGENTCORE_CODE_INTERPRETER).to_api()
    assert tool["type"] == "agentcore_code_interpreter"
    assert tool["config"] == {"agentCoreCodeInterpreter": {}}


def test_inline_function_tool_requires_schema() -> None:
    with pytest.raises(ValueError):
        HarnessTool(
            type=HarnessToolType.INLINE_FUNCTION,
            inline_description="do a thing",
        ).to_api()


def test_truncation_sliding_window() -> None:
    t = HarnessTruncationConfig(
        strategy=TruncationStrategy.SLIDING_WINDOW, sliding_window_messages=10
    )
    assert t.to_api() == {
        "strategy": "sliding_window",
        "config": {"slidingWindow": {"messagesCount": 10}},
    }


def test_vpc_network_mode_requires_subnets() -> None:
    from app.services.harness_deployer import HarnessDeployer, HarnessStore

    req = _req(network_mode="VPC")
    store = MagicMock(spec=HarnessStore)
    with patch(
        "app.services.harness_deployer._control_client",
        return_value=MagicMock(),
    ):
        deployer = HarnessDeployer.__new__(HarnessDeployer)
        deployer._store = store  # type: ignore
        deployer._client = MagicMock()
        with pytest.raises(ValueError):
            deployer._build_create_params(
                req,
                execution_role_arn="arn:aws:iam::1:role/x",
                user_id="u1",
            )


def test_build_create_params_tagging_owner() -> None:
    from app.services.harness_deployer import HarnessDeployer

    req = _req(tags={"team": "platform"})
    with patch(
        "app.services.harness_deployer._control_client",
        return_value=MagicMock(),
    ):
        deployer = HarnessDeployer.__new__(HarnessDeployer)
        deployer._store = MagicMock()  # type: ignore
        deployer._client = MagicMock()
        params = deployer._build_create_params(
            req,
            execution_role_arn="arn:aws:iam::1:role/x",
            user_id="u1",
        )
    assert params["harnessName"] == "test_harness"
    assert params["executionRoleArn"] == "arn:aws:iam::1:role/x"
    assert params["model"] == {
        "bedrockModelConfig": {"modelId": "anthropic.claude-3-haiku-20240307-v1:0"}
    }
    assert params["tags"] == {"owner": "u1", "team": "platform"}
    assert params["environment"]["agentCoreRuntimeEnvironment"]["networkConfiguration"]["networkMode"] == "PUBLIC"


def test_provider_of_resolves_correctly() -> None:
    from app.services.harness_deployer import HarnessDeployer

    req = _req()
    assert HarnessDeployer._provider_of(req) == ModelProvider.BEDROCK

    from app.models.harness_models import OpenAiModelConfig

    req2 = HarnessCreateRequest(
        harness_name="t2",
        model=HarnessModelConfig(
            openai=OpenAiModelConfig(
                model_id="gpt-4o",
                api_key_arn="arn:aws:bedrock-agentcore:us-east-1:1:credential-provider/x",
            )
        ),
    )
    assert HarnessDeployer._provider_of(req2) == ModelProvider.OPENAI


def test_extract_runtime_ids_returns_nones_when_absent() -> None:
    from app.services.harness_deployer import HarnessDeployer

    assert HarnessDeployer._extract_runtime_ids({}) == (None, None)
    assert HarnessDeployer._extract_runtime_ids(
        {"environment": {"agentCoreRuntimeEnvironment": {"agentRuntimeArn": "arn:...", "agentRuntimeId": "r-1"}}}
    ) == ("arn:...", "r-1")


def test_drain_stream_surfaces_errors() -> None:
    """The invoker must not claim success when the stream raises."""
    from app.services.harness_invoker import _drain_stream

    class BadStream:
        def __iter__(self):
            raise RuntimeError("runtimeClientError: legacy model")

    text, err = _drain_stream(BadStream())
    assert text == ""
    assert err is not None
    assert "legacy model" in err


def test_drain_stream_extracts_converse_deltas() -> None:
    """Delta events should accumulate into clean text."""
    from app.services.harness_invoker import _drain_stream

    events = [
        {"role": "assistant"},
        {"contentBlockIndex": 0, "delta": {"text": "Hi"}},
        {"contentBlockIndex": 0, "delta": {"text": " world"}},
        {"stopReason": "end_turn"},
        {"usage": {"inputTokens": 10}},
    ]
    text, err = _drain_stream(events)
    assert err is None
    assert text == "Hi world"


def test_drain_stream_empty_none() -> None:
    from app.services.harness_invoker import _drain_stream

    text, err = _drain_stream(None)
    assert text == ""
    assert err is None


def test_coerce_session_id_pads_short_ids() -> None:
    """AWS InvokeHarness requires runtimeSessionId >= 33 chars."""
    from app.services.harness_invoker import _coerce_session_id

    assert len(_coerce_session_id(None)) >= 33
    assert len(_coerce_session_id("")) >= 33
    assert len(_coerce_session_id("sess-A")) >= 33
    # Already long enough — leave untouched
    big = "a" * 33
    assert _coerce_session_id(big) == big
    # Deterministic padding so short IDs map to a stable session
    assert _coerce_session_id("sess-A") == _coerce_session_id("sess-A")
