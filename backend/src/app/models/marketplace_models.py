"""Agent/Tool Marketplace models (Task 09).

Lifecycle:
    draft  -> pending_review  -> published
                              -> rejected
    published -> deprecated
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ItemType(str, Enum):
    AGENT_TEMPLATE = "agent_template"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    WORKFLOW = "workflow"


class ItemStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class MarketplaceItem(BaseModel):
    item_id: str
    author_id: str
    author: str = ""
    item_type: ItemType
    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=512)
    long_description: Optional[str] = Field(default=None, max_length=8192)
    version: str = Field(default="1.0.0")
    icon_url: Optional[str] = Field(default=None, max_length=512)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: ItemStatus = ItemStatus.DRAFT
    workflow_json: Optional[dict[str, Any]] = None
    tool_code: Optional[str] = Field(default=None, max_length=65536)
    requirements: list[str] = Field(default_factory=list)
    model_requirements: list[str] = Field(default_factory=list)
    configuration_schema: Optional[dict[str, Any]] = None
    install_count: int = 0
    rating_average: float = 0.0
    rating_count: int = 0
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    published_at: Optional[str] = None
    rejection_reason: Optional[str] = None


class PublishRequest(BaseModel):
    item_type: ItemType
    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=512)
    long_description: Optional[str] = Field(default=None, max_length=8192)
    version: str = "1.0.0"
    icon_url: Optional[str] = Field(default=None, max_length=512)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    workflow_json: Optional[dict[str, Any]] = None
    tool_code: Optional[str] = Field(default=None, max_length=65536)
    requirements: list[str] = Field(default_factory=list)
    model_requirements: list[str] = Field(default_factory=list)
    configuration_schema: Optional[dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        # alphanumeric + underscore + hyphen
        if not all(c.isalnum() or c in ("_", "-") for c in v):
            raise ValueError("name may only contain alphanumeric, _, and -")
        return v


class UpdateItemRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, min_length=1, max_length=512)
    long_description: Optional[str] = Field(default=None, max_length=8192)
    version: Optional[str] = None
    icon_url: Optional[str] = Field(default=None, max_length=512)
    categories: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    workflow_json: Optional[dict[str, Any]] = None
    tool_code: Optional[str] = Field(default=None, max_length=65536)
    configuration_schema: Optional[dict[str, Any]] = None


class SubmitRequest(BaseModel):
    """Move a draft into pending_review."""


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1024)


class MarketplaceReview(BaseModel):
    review_id: str
    item_id: str
    user_id: str
    rating: int = Field(..., ge=1, le=5)
    title: str = Field(..., min_length=1, max_length=128)
    body: str = Field(default="", max_length=2048)
    helpful_count: int = 0
    created_at: str = Field(default_factory=_now_iso)


class SubmitReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: str = Field(..., min_length=1, max_length=128)
    body: str = Field(default="", max_length=2048)


class ItemResponse(BaseModel):
    item: MarketplaceItem


class ItemListResponse(BaseModel):
    items: list[MarketplaceItem]


class ReviewListResponse(BaseModel):
    reviews: list[MarketplaceReview]


class InstallResponse(BaseModel):
    item_id: str
    installed_at: str
    workflow_json: Optional[dict[str, Any]] = None
    tool_code: Optional[str] = None
    configuration_schema: Optional[dict[str, Any]] = None
