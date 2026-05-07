"""Approvals REST API (Task 02).

Endpoints:
  POST   /api/approvals              - create new approval request (agent-initiated)
  GET    /api/approvals              - list approvals for caller
  GET    /api/approvals/stats        - counts by status
  GET    /api/approvals/{id}         - read single approval (polled by waiting agent)
  POST   /api/approvals/{id}/resolve - approve or reject
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.approval_models import (
    ApprovalCreateRequest,
    ApprovalListResponse,
    ApprovalResolveRequest,
    ApprovalResponse,
    ApprovalStatsResponse,
    ApprovalStatus,
)
from app.services.approval_service import ApprovalService
from app.services.approval_store import ApprovalStore
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _get_store() -> ApprovalStore:
    return ApprovalStore(
        table_name=os.environ["APPROVALS_TABLE_NAME"], region=_region()
    )


def _get_service() -> ApprovalService:
    return ApprovalService(_get_store())


def _validate_id(approval_id: str) -> str:
    if not _ID_RE.match(approval_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid approval_id"
        )
    return approval_id


def _require_owner(approval_id: str, user_id: str):
    store = _get_store()
    approval = store.get(approval_id)
    if approval is None or approval.user_id != user_id:
        raise HTTPException(status_code=404, detail="approval not found")
    return approval


@router.post("", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    req: ApprovalCreateRequest, user_id: str = Depends(require_user)
) -> ApprovalResponse:
    try:
        approval = _get_service().create(user_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"AWS error: {e.response.get('Error', {}).get('Code')}",
        )
    return ApprovalResponse(approval=approval, message="created")


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    status_filter: Optional[ApprovalStatus] = None,
    deployment_id: Optional[str] = None,
    user_id: str = Depends(require_user),
) -> ApprovalListResponse:
    store = _get_store()
    approvals = store.list_for_user(user_id, status=status_filter)
    if deployment_id:
        approvals = [a for a in approvals if a.deployment_id == deployment_id]
    # Opportunistically expire pending-but-timed-out rows so the list reflects reality
    service = ApprovalService(store)
    approvals = [service._maybe_expire(a) for a in approvals]
    if status_filter is not None:
        approvals = [a for a in approvals if a.status == status_filter]
    return ApprovalListResponse(approvals=approvals)


@router.get("/stats", response_model=ApprovalStatsResponse)
async def approval_stats(user_id: str = Depends(require_user)) -> ApprovalStatsResponse:
    _get_service().sweep_expired(user_id)
    counts = _get_store().stats_for_user(user_id)
    return ApprovalStatsResponse(
        pending=counts.get("pending", 0),
        approved=counts.get("approved", 0),
        rejected=counts.get("rejected", 0),
        expired=counts.get("expired", 0),
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str, user_id: str = Depends(require_user)
) -> ApprovalResponse:
    approval_id = _validate_id(approval_id)
    approval = _require_owner(approval_id, user_id)
    approval = _get_service()._maybe_expire(approval)
    return ApprovalResponse(approval=approval)


@router.post("/{approval_id}/resolve", response_model=ApprovalResponse)
async def resolve_approval(
    approval_id: str,
    req: ApprovalResolveRequest,
    user_id: str = Depends(require_user),
) -> ApprovalResponse:
    approval_id = _validate_id(approval_id)
    approval = _require_owner(approval_id, user_id)
    try:
        approval = _get_service().resolve(approval, user_id, req)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ApprovalResponse(approval=approval, message="resolved")
