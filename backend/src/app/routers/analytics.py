"""Analytics REST API (Task 04).

Endpoints:
  GET /api/analytics/{deployment_id}/summary      - KPI summary
  GET /api/analytics/{deployment_id}/timeseries   - metric over time
  GET /api/analytics/{deployment_id}/costs        - daily cost rollup
  POST /api/analytics/{deployment_id}/record      - record an invocation metric
      (called by the agent Lambda — or by tests)

Tenant isolation: we check that the caller owns at least one version of this
deployment_id before exposing metrics. The metrics themselves are in
CloudWatch, which is account-wide, so ownership is validated via the Versions
table (the one place where we have ground truth on who deployed what).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.analytics_service import (
    AnalyticsService,
    estimated_cost_for_invocation,
)
from app.services.metrics_emitter import emit_invocation_metrics
from app.services.version_store import VersionStore
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _version_store() -> VersionStore:
    return VersionStore(
        table_name=os.environ["VERSIONS_TABLE_NAME"], region=_region()
    )


def _validate_id(deployment_id: str) -> str:
    if not _ID_RE.match(deployment_id):
        raise HTTPException(status_code=400, detail="Invalid deployment_id")
    return deployment_id


def _require_ownership(deployment_id: str, user_id: str) -> None:
    """Returns silently if the caller owns at least one version of this deployment.

    Otherwise raises 404. If there are zero versions we also 404 because
    there's nothing to report on.
    """
    versions = _version_store().list_for_deployment(deployment_id)
    if not versions or not any(v.user_id == user_id for v in versions):
        raise HTTPException(status_code=404, detail="deployment not found")


class RecordInvocationRequest(BaseModel):
    model_id: Optional[str] = Field(default=None, max_length=128)
    input_tokens: int = Field(default=0, ge=0, le=10_000_000)
    output_tokens: int = Field(default=0, ge=0, le=10_000_000)
    latency_ms: int = Field(default=0, ge=0, le=600_000)
    tool_call_count: int = Field(default=0, ge=0, le=100_000)
    tool_call_success_rate: float = Field(default=100.0, ge=0.0, le=100.0)
    is_error: bool = False


@router.post("/{deployment_id}/record", status_code=status.HTTP_202_ACCEPTED)
async def record_invocation(
    deployment_id: str,
    req: RecordInvocationRequest,
    user_id: str = Depends(require_user),
) -> dict:
    deployment_id = _validate_id(deployment_id)
    _require_ownership(deployment_id, user_id)
    cost = estimated_cost_for_invocation(req.model_id, req.input_tokens, req.output_tokens)
    emit_invocation_metrics(
        deployment_id=deployment_id,
        model_id=req.model_id,
        metrics={
            "InvocationLatencyMs": req.latency_ms,
            "InputTokens": req.input_tokens,
            "OutputTokens": req.output_tokens,
            "EstimatedCostUSD": cost,
            "ToolCallCount": req.tool_call_count,
            "ToolCallSuccessRate": req.tool_call_success_rate,
            "IsError": 1 if req.is_error else 0,
        },
    )
    return {"status": "accepted", "estimated_cost_usd": cost}


@router.get("/{deployment_id}/summary")
async def get_summary(
    deployment_id: str,
    hours: int = Query(24, ge=1, le=30 * 24),
    user_id: str = Depends(require_user),
) -> dict:
    deployment_id = _validate_id(deployment_id)
    _require_ownership(deployment_id, user_id)
    return AnalyticsService().summary(deployment_id, hours=hours)


@router.get("/{deployment_id}/timeseries")
async def get_timeseries(
    deployment_id: str,
    metric: str = Query("InvocationCount", max_length=64),
    hours: int = Query(24, ge=1, le=30 * 24),
    stat: str = Query("Sum"),
    user_id: str = Depends(require_user),
) -> dict:
    deployment_id = _validate_id(deployment_id)
    _require_ownership(deployment_id, user_id)
    if metric not in {
        "InvocationCount",
        "InvocationLatencyMs",
        "InputTokens",
        "OutputTokens",
        "EstimatedCostUSD",
        "ToolCallCount",
        "IsError",
    }:
        raise HTTPException(status_code=400, detail="unsupported metric")
    if stat not in {"Sum", "Average", "Minimum", "Maximum"}:
        raise HTTPException(status_code=400, detail="unsupported stat")
    data = AnalyticsService().timeseries(
        deployment_id, metric_name=metric, hours=hours, stat=stat
    )
    return {"metric": metric, "stat": stat, "hours": hours, "points": data}
