"""CloudWatch EMF (Embedded Metric Format) emitter for agent metrics (Task 04).

Any code running in Lambda can call `emit_invocation_metrics` to record
per-invocation metrics. The Lambda log driver auto-ingests EMF-formatted
JSON as CloudWatch metrics under the declared namespace/dimensions.

Usage:
    from app.services.metrics_emitter import emit_invocation_metrics
    emit_invocation_metrics(
        deployment_id=...,
        model_id=...,
        metrics={
            "InvocationLatencyMs": 842,
            "InputTokens": 1204,
            "OutputTokens": 318,
            "EstimatedCostUSD": 0.0042,
            "ToolCallCount": 2,
            "ToolCallSuccessRate": 100.0,
            "IsError": 0,
        },
    )
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NAMESPACE = "AgentCore/Agents"

_METRIC_DEFS = [
    {"Name": "InvocationCount", "Unit": "Count"},
    {"Name": "InvocationLatencyMs", "Unit": "Milliseconds"},
    {"Name": "InputTokens", "Unit": "Count"},
    {"Name": "OutputTokens", "Unit": "Count"},
    {"Name": "EstimatedCostUSD", "Unit": "None"},
    {"Name": "ToolCallCount", "Unit": "Count"},
    {"Name": "ToolCallSuccessRate", "Unit": "Percent"},
    {"Name": "IsError", "Unit": "Count"},
]


def emit_invocation_metrics(
    *,
    deployment_id: str,
    model_id: str | None = None,
    metrics: dict[str, Any],
) -> None:
    """Print a single EMF log line. Automatically picked up by CloudWatch."""
    record: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": (
                        [["DeploymentId"], ["DeploymentId", "ModelId"]]
                        if model_id
                        else [["DeploymentId"]]
                    ),
                    "Metrics": _METRIC_DEFS,
                }
            ],
        },
        "DeploymentId": deployment_id,
    }
    if model_id:
        record["ModelId"] = model_id
    # Always include InvocationCount = 1 so count-based queries work without
    # requiring callers to remember to set it.
    metrics = {"InvocationCount": 1, **metrics}
    record.update(metrics)
    try:
        print(json.dumps(record, default=str))
    except (TypeError, ValueError):
        logger.exception("failed to emit EMF record")
