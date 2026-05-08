"""Admin REST API for RBAC + Audit + DLP (Task 10)."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.models.audit_models import AuditEvent, AuditListResponse
from app.models.rbac_models import (
    AssignRoleRequest,
    MeResponse,
    Permission,
    Role,
    UserRoleListResponse,
    UserRoleResponse,
)
from app.services.audit_service import singleton_audit_service
from app.services.dlp_service import DlpPolicyStore, DlpService
from app.services.rbac_service import RbacService, RbacStore, _singleton_service
from app.shared.auth import get_user_email, require_user

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

router = APIRouter(prefix="/admin", tags=["admin"])
rbac_router = APIRouter(prefix="/rbac", tags=["rbac"])
dlp_router = APIRouter(prefix="/dlp", tags=["dlp"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _dlp() -> DlpService:
    table = os.environ.get("DLP_POLICIES_TABLE_NAME")
    if not table:
        return DlpService(policy_store=None)
    return DlpService(policy_store=DlpPolicyStore(table_name=table, region=_region()))


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@rbac_router.get("/me", response_model=MeResponse)
async def me(
    request: Request, user_id: str = Depends(require_user)
) -> MeResponse:
    svc = _singleton_service()
    role = svc.resolve_role(user_id)
    return MeResponse(
        user_id=user_id,
        email=get_user_email(request),
        role=role,
        permissions=svc.effective_permissions(role),
    )


@router.get("/users", response_model=UserRoleListResponse)
async def list_users(user_id: str = Depends(require_user)) -> UserRoleListResponse:
    svc = _singleton_service()
    try:
        users = svc.list_users(user_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    return UserRoleListResponse(users=users)


@router.put("/users/role", response_model=UserRoleResponse)
async def assign_role(
    req: AssignRoleRequest,
    request: Request,
    user_id: str = Depends(require_user),
) -> UserRoleResponse:
    svc = _singleton_service()
    try:
        rec = svc.assign(user_id, req.user_id, req.role)
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    audit = singleton_audit_service()
    audit.log(
        user_id=user_id,
        user_email=get_user_email(request),
        action="assign_role",
        resource_type="user",
        resource_id=req.user_id,
        metadata={"role": req.role.value},
    )
    return UserRoleResponse(user=rec)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@router.get("/audit", response_model=AuditListResponse)
async def list_audit(
    date: Optional[str] = Query(default=None, max_length=10),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Depends(require_user),
) -> AuditListResponse:
    svc = _singleton_service()
    if not svc.has(user_id, Permission.ADMIN_VIEW_AUDIT):
        raise HTTPException(status_code=403, detail="admin only")
    if date is not None and not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    audit = singleton_audit_service()
    events = audit.recent(date_partition=date, limit=limit)
    return AuditListResponse(events=events)


# ---------------------------------------------------------------------------
# DLP
# ---------------------------------------------------------------------------


class DlpScanRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=16384)
    action: str = Field(default="mask", pattern="^(none|mask|block|alert)$")
    use_comprehend: bool = True


class DlpScanResponse(BaseModel):
    action: str
    matched_types: list[str]
    match_count: int
    masked_text: Optional[str] = None


class DlpPolicyRequest(BaseModel):
    deployment_id: str = Field(..., min_length=1, max_length=128)
    action: str = Field(..., pattern="^(none|mask|block|alert)$")
    use_comprehend: bool = True


@dlp_router.post("/scan", response_model=DlpScanResponse)
async def dlp_scan(
    req: DlpScanRequest, user_id: str = Depends(require_user)
) -> DlpScanResponse:
    result = _dlp().scan(
        req.text, action=req.action, use_comprehend=req.use_comprehend
    )
    return DlpScanResponse(
        action=result.action,
        matched_types=result.matched_types,
        match_count=result.match_count,
        masked_text=result.masked_text,
    )


@dlp_router.put("/policies", response_model=DlpPolicyRequest)
async def upsert_policy(
    req: DlpPolicyRequest,
    request: Request,
    user_id: str = Depends(require_user),
) -> DlpPolicyRequest:
    svc = _singleton_service()
    if not svc.has(user_id, Permission.ADMIN_MANAGE_DLP):
        raise HTTPException(status_code=403, detail="admin only")
    try:
        _dlp().save_policy(
            req.deployment_id, user_id, req.action, req.use_comprehend
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    singleton_audit_service().log(
        user_id=user_id,
        user_email=get_user_email(request),
        action="upsert_dlp_policy",
        resource_type="dlp_policy",
        resource_id=req.deployment_id,
        metadata={"action": req.action},
    )
    return req


@dlp_router.get("/policies/{deployment_id}")
async def get_policy(
    deployment_id: str, user_id: str = Depends(require_user)
) -> dict:
    svc = _singleton_service()
    if not svc.has(user_id, Permission.ADMIN_MANAGE_DLP):
        raise HTTPException(status_code=403, detail="admin only")
    policy = _dlp().get_policy(deployment_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="policy not found")
    return policy
