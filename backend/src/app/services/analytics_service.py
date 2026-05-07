"""Analytics service: query CloudWatch metrics + compute summaries (Task 04).

This service fetches `AgentCore/Agents` namespace metrics for a deployment
and exposes summary + timeseries APIs. Because tenant isolation matters
but CloudWatch metrics are account-wide, we verify the caller owns a
deployment before exposing its metrics (the frontend passes deployment_id
as a path param; the router checks user ownership via the Versions table).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3

from app.services.cost_calculator import estimate_cost

logger = logging.getLogger(__name__)

NAMESPACE = "AgentCore/Agents"


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _cw() -> Any:
    return boto3.client("cloudwatch", region_name=_region())


def _period_for_range(hours: int) -> int:
    if hours <= 3:
        return 60  # 1-minute granularity
    if hours <= 24:
        return 300  # 5-minute
    if hours <= 24 * 7:
        return 3600  # 1-hour
    return 21600  # 6-hour for 30d


class AnalyticsService:
    def summary(self, deployment_id: str, hours: int = 24) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        dims = [{"Name": "DeploymentId", "Value": deployment_id}]

        def _sum(name: str) -> float:
            return self._aggregate_sum(dims, name, start, end)

        def _avg(name: str) -> float:
            return self._aggregate_avg(dims, name, start, end)

        invocation_count = _sum("InvocationCount")
        input_tokens = _sum("InputTokens")
        output_tokens = _sum("OutputTokens")
        errors = _sum("IsError")
        total_cost = _sum("EstimatedCostUSD")
        avg_latency = _avg("InvocationLatencyMs")
        p95 = self._percentile(dims, "InvocationLatencyMs", 95, start, end)
        p99 = self._percentile(dims, "InvocationLatencyMs", 99, start, end)

        error_rate = (errors / invocation_count * 100.0) if invocation_count > 0 else 0.0

        return {
            "deployment_id": deployment_id,
            "window_hours": hours,
            "invocations": int(invocation_count),
            "errors": int(errors),
            "error_rate_pct": round(error_rate, 2),
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "estimated_cost_usd": round(total_cost, 6),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95, 1),
            "p99_latency_ms": round(p99, 1),
        }

    def timeseries(
        self,
        deployment_id: str,
        metric_name: str,
        hours: int = 24,
        stat: str = "Sum",
    ) -> list[dict[str, Any]]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        period = _period_for_range(hours)
        resp = _cw().get_metric_statistics(
            Namespace=NAMESPACE,
            MetricName=metric_name,
            Dimensions=[{"Name": "DeploymentId", "Value": deployment_id}],
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=[stat],
        )
        datapoints = sorted(resp.get("Datapoints", []), key=lambda d: d["Timestamp"])
        return [
            {"timestamp": dp["Timestamp"].isoformat(), "value": dp.get(stat, 0)}
            for dp in datapoints
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _aggregate_sum(
        self,
        dims: list[dict[str, str]],
        metric: str,
        start: datetime,
        end: datetime,
    ) -> float:
        try:
            resp = _cw().get_metric_statistics(
                Namespace=NAMESPACE,
                MetricName=metric,
                Dimensions=dims,
                StartTime=start,
                EndTime=end,
                Period=max(60, int((end - start).total_seconds())),
                Statistics=["Sum"],
            )
        except Exception as e:
            logger.warning("cw get_metric_statistics(%s, Sum) failed: %s", metric, e)
            return 0.0
        return sum(dp.get("Sum", 0) for dp in resp.get("Datapoints", []))

    def _aggregate_avg(
        self,
        dims: list[dict[str, str]],
        metric: str,
        start: datetime,
        end: datetime,
    ) -> float:
        try:
            resp = _cw().get_metric_statistics(
                Namespace=NAMESPACE,
                MetricName=metric,
                Dimensions=dims,
                StartTime=start,
                EndTime=end,
                Period=max(60, int((end - start).total_seconds())),
                Statistics=["Average"],
            )
        except Exception as e:
            logger.warning("cw get_metric_statistics(%s, Average) failed: %s", metric, e)
            return 0.0
        points = resp.get("Datapoints", [])
        if not points:
            return 0.0
        return sum(dp.get("Average", 0) for dp in points) / len(points)

    def _percentile(
        self,
        dims: list[dict[str, str]],
        metric: str,
        pct: int,
        start: datetime,
        end: datetime,
    ) -> float:
        try:
            resp = _cw().get_metric_statistics(
                Namespace=NAMESPACE,
                MetricName=metric,
                Dimensions=dims,
                StartTime=start,
                EndTime=end,
                Period=max(60, int((end - start).total_seconds())),
                ExtendedStatistics=[f"p{pct}"],
            )
        except Exception as e:
            logger.warning(
                "cw get_metric_statistics(%s, p%d) failed: %s", metric, pct, e
            )
            return 0.0
        key = f"p{pct}"
        points = resp.get("Datapoints", [])
        if not points:
            return 0.0
        # Flatten extended stats
        values: list[float] = []
        for dp in points:
            stats = dp.get("ExtendedStatistics") or {}
            if key in stats:
                values.append(float(stats[key]))
        if not values:
            return 0.0
        return sum(values) / len(values)


def estimated_cost_for_invocation(
    model_id: Optional[str], input_tokens: int, output_tokens: int
) -> float:
    return estimate_cost(model_id, input_tokens, output_tokens)
