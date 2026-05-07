"""Unit tests for cost calculator and metrics emitter (Task 04)."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from app.services.cost_calculator import DEFAULT_PRICING, MODEL_PRICING, estimate_cost
from app.services.metrics_emitter import emit_invocation_metrics


def test_known_model_pricing() -> None:
    cost = estimate_cost("anthropic.claude-3-5-haiku-20241022-v1:0", 1000, 500)
    # (1000/1000)*0.001 + (500/1000)*0.005 = 0.001 + 0.0025 = 0.0035
    assert cost == 0.0035


def test_prefix_stripping() -> None:
    cost_with_prefix = estimate_cost("us.anthropic.claude-3-5-haiku-20241022-v1:0", 1000, 500)
    cost_without = estimate_cost("anthropic.claude-3-5-haiku-20241022-v1:0", 1000, 500)
    assert cost_with_prefix == cost_without


def test_unknown_model_uses_default() -> None:
    cost = estimate_cost("unknown-model-xyz", 1000, 1000)
    assert cost > 0
    assert cost == round(
        (1000 / 1000) * DEFAULT_PRICING[0] + (1000 / 1000) * DEFAULT_PRICING[1], 6
    )


def test_zero_tokens() -> None:
    assert estimate_cost("anthropic.claude-3-5-haiku-20241022-v1:0", 0, 0) == 0.0


def test_no_model_returns_zero() -> None:
    assert estimate_cost(None, 1000, 500) == 0.0


def test_emf_emits_valid_json() -> None:
    buf = StringIO()
    with patch("sys.stdout", buf):
        emit_invocation_metrics(
            deployment_id="d1",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
            metrics={
                "InvocationLatencyMs": 100,
                "InputTokens": 50,
                "OutputTokens": 25,
                "EstimatedCostUSD": 0.001,
                "ToolCallCount": 1,
                "ToolCallSuccessRate": 100.0,
                "IsError": 0,
            },
        )
    line = buf.getvalue().strip()
    assert line, "expected an EMF line"
    # Find the last JSON object in case something else went to stdout
    record = json.loads(line.split("\n")[-1])
    assert record["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "AgentCore/Agents"
    assert record["DeploymentId"] == "d1"
    assert record["InvocationCount"] == 1  # auto-injected
    assert record["InvocationLatencyMs"] == 100


def test_all_known_models_nonzero() -> None:
    for model_id in MODEL_PRICING:
        assert estimate_cost(model_id, 1000, 1000) > 0
