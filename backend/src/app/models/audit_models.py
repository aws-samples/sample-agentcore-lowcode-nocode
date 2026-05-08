"""Audit log models (Task 10)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditEvent(BaseModel):
    event_id: str
    date_partition: str  # YYYY-MM-DD for cheap GSI lookups
    timestamp: str = Field(default_factory=_now_iso)
    user_id: str
    user_email: Optional[str] = None
    action: str = Field(..., max_length=128)
    resource_type: str = Field(..., max_length=64)
    resource_id: Optional[str] = Field(default=None, max_length=128)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=256)
    result: str = Field(..., max_length=32)  # allowed | denied | error
    error: Optional[str] = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditListResponse(BaseModel):
    events: list[AuditEvent]
