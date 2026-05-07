"""Approval models for Human-in-the-Loop (Task 02)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalType(str, Enum):
    BINARY = "binary"
    CHOICE = "choice"
    FORM = "form"
    REVIEW = "review"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalRequest(BaseModel):
    """An approval record (one row in the approvals table)."""

    approval_id: str
    user_id: str  # owner — who created the request (typically the agent's deployment owner)
    deployment_id: str
    runtime_id: Optional[str] = None
    session_id: Optional[str] = None
    approval_type: ApprovalType = ApprovalType.BINARY
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=4096)
    context: dict[str, Any] = Field(default_factory=dict)
    proposed_action: str = Field(default="", max_length=2048)
    options: Optional[list[str]] = None
    form_schema: Optional[dict[str, Any]] = None
    content_to_review: Optional[str] = Field(default=None, max_length=16384)

    status: ApprovalStatus = ApprovalStatus.PENDING
    timeout_minutes: int = Field(default=60, ge=1, le=10080)  # up to 7 days
    created_at: str = Field(default_factory=_now_iso)
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution: Optional[dict[str, Any]] = None
    ttl: Optional[int] = None  # DynamoDB TTL, epoch seconds


class ApprovalCreateRequest(BaseModel):
    deployment_id: str = Field(..., min_length=1, max_length=128)
    runtime_id: Optional[str] = Field(default=None, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=256)
    approval_type: ApprovalType = ApprovalType.BINARY
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=4096)
    context: dict[str, Any] = Field(default_factory=dict)
    proposed_action: str = Field(default="", max_length=2048)
    options: Optional[list[str]] = None
    form_schema: Optional[dict[str, Any]] = None
    content_to_review: Optional[str] = Field(default=None, max_length=16384)
    timeout_minutes: int = Field(default=60, ge=1, le=10080)


class ApprovalResolveRequest(BaseModel):
    decision: ApprovalStatus  # approved or rejected
    feedback: Optional[str] = Field(default=None, max_length=2048)
    edited_content: Optional[str] = Field(default=None, max_length=16384)
    form_data: Optional[dict[str, Any]] = None
    selected_option: Optional[str] = Field(default=None, max_length=256)


class ApprovalResponse(BaseModel):
    approval: ApprovalRequest
    message: str = "ok"


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalRequest]


class ApprovalStatsResponse(BaseModel):
    pending: int
    approved: int
    rejected: int
    expired: int
