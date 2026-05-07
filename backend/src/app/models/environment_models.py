"""Environment promotion models (Task 07).

Environments are a logical overlay on the existing deployment model:
  - dev, staging, prod (fixed set)
  - each (deployment_id, env) has a single "active version"
  - promotion copies a version snapshot from one env to the next

Promotions that target prod require explicit approval before execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


NEXT_ENVIRONMENT: dict[Environment, Optional[Environment]] = {
    Environment.DEV: Environment.STAGING,
    Environment.STAGING: Environment.PROD,
    Environment.PROD: None,
}


class PromotionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTING = "promoting"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class EnvironmentBinding(BaseModel):
    """Current state of an environment for a deployment."""

    deployment_id: str
    env: Environment
    user_id: str
    active_version: Optional[int] = None
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=_now_iso)


class EnvironmentBindingListResponse(BaseModel):
    bindings: list[EnvironmentBinding]


class PromotionRequest(BaseModel):
    deployment_id: str = Field(..., min_length=1, max_length=128)
    source_env: Environment
    target_env: Environment
    source_version: Optional[int] = Field(default=None, ge=1)
    change_description: str = Field(..., min_length=1, max_length=1024)


class PromotionRecord(BaseModel):
    promotion_id: str
    deployment_id: str
    user_id: str
    source_env: Environment
    target_env: Environment
    source_version: int
    target_version: Optional[int] = None
    status: PromotionStatus
    change_description: str
    requested_by: str
    requested_at: str = Field(default_factory=_now_iso)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class PromotionResponse(BaseModel):
    promotion: PromotionRecord


class PromotionListResponse(BaseModel):
    promotions: list[PromotionRecord]


class ApproveRequest(BaseModel):
    comment: str = Field(default="", max_length=1024)


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1024)


class UpdateEnvConfigRequest(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)
