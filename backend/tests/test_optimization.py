"""Optimization unit tests (Task 12) — no network."""

from __future__ import annotations

import pytest

from app.models.optimization_models import (
    BundleComponent,
    CloudWatchDataSourceInput,
    ConfigurationBundleRequest,
    OnlineEvaluationConfigRequest,
    SamplingConfigInput,
)


def test_bundle_name_rules() -> None:
    with pytest.raises(ValueError):
        ConfigurationBundleRequest(bundle_name="1bad")
    with pytest.raises(ValueError):
        ConfigurationBundleRequest(bundle_name="x" * 200)
    # good
    ok = ConfigurationBundleRequest(
        bundle_name="prod_v1",
        description="production config v1",
        components=[
            BundleComponent(
                resource_arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/a-b",
                configuration={"systemPrompt": "hi"},
            )
        ],
    )
    assert ok.bundle_name == "prod_v1"
    assert ok.branch_name == "mainline"


def test_online_eval_sampling_bounds() -> None:
    with pytest.raises(ValueError):
        SamplingConfigInput(sampling_percentage=150.0)
    with pytest.raises(ValueError):
        SamplingConfigInput(sampling_percentage=-1.0)
    SamplingConfigInput(sampling_percentage=50.0)


def test_online_eval_request_build() -> None:
    req = OnlineEvaluationConfigRequest(
        name="prod_eval",
        sampling=SamplingConfigInput(sampling_percentage=10.0, session_timeout_minutes=30),
        data_source=CloudWatchDataSourceInput(
            log_group_names=["/aws/bedrock-agentcore/agent-traces"],
            service_names=["bedrock-agentcore"],
        ),
        evaluator_ids=["Builtin.Correctness", "Builtin.Helpfulness"],
        execution_role_arn="arn:aws:iam::1:role/x",
    )
    assert req.name == "prod_eval"
    assert len(req.evaluator_ids) == 2


def test_online_eval_requires_at_least_one_evaluator() -> None:
    with pytest.raises(ValueError):
        OnlineEvaluationConfigRequest(
            name="bad",
            sampling=SamplingConfigInput(sampling_percentage=1.0),
            data_source=CloudWatchDataSourceInput(
                log_group_names=["g"], service_names=["s"]
            ),
            evaluator_ids=[],
            execution_role_arn="arn:aws:iam::1:role/x",
        )


def test_online_eval_name_rules() -> None:
    with pytest.raises(ValueError):
        OnlineEvaluationConfigRequest(
            name="1bad",
            sampling=SamplingConfigInput(sampling_percentage=1.0),
            data_source=CloudWatchDataSourceInput(log_group_names=["g"], service_names=["s"]),
            evaluator_ids=["x"],
            execution_role_arn="arn:aws:iam::1:role/x",
        )
