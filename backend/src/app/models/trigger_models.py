"""Trigger models for scheduled/event-driven agent invocation.

See tasks/market-gaps/01-event-triggers-scheduling.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TriggerType(str, Enum):
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    EVENT = "event"


class TriggerStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class TriggerInvocationStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    THROTTLED = "throttled"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TriggerConfig(BaseModel):
    """Stored trigger configuration."""

    trigger_id: str
    user_id: str
    deployment_id: str
    runtime_id: Optional[str] = None
    trigger_type: TriggerType
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    enabled: bool = True
    status: TriggerStatus = TriggerStatus.ACTIVE
    # Schedule
    schedule_expression: Optional[str] = Field(default=None, max_length=256)
    schedule_timezone: Optional[str] = Field(default="UTC", max_length=64)
    # Webhook
    webhook_path: Optional[str] = Field(default=None, max_length=128)
    webhook_secret_arn: Optional[str] = None
    # Event
    event_pattern: Optional[dict[str, Any]] = None
    event_bus_name: Optional[str] = Field(default=None, max_length=256)
    # Input template (str.format style)
    input_template: Optional[str] = Field(default=None, max_length=8192)
    # AWS resource identifiers (populated after provisioning)
    schedule_name: Optional[str] = None
    schedule_arn: Optional[str] = None
    event_rule_name: Optional[str] = None
    event_rule_arn: Optional[str] = None
    # Counters
    trigger_count: int = 0
    last_triggered_at: Optional[str] = None
    last_error: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class TriggerCreateRequest(BaseModel):
    deployment_id: str = Field(..., min_length=1, max_length=128)
    runtime_id: Optional[str] = Field(default=None, max_length=128)
    trigger_type: TriggerType
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    schedule_expression: Optional[str] = Field(default=None, max_length=256)
    schedule_timezone: Optional[str] = Field(default="UTC", max_length=64)
    webhook_path: Optional[str] = Field(default=None, max_length=128)
    event_pattern: Optional[dict[str, Any]] = None
    event_bus_name: Optional[str] = Field(default=None, max_length=256)
    input_template: Optional[str] = Field(default=None, max_length=8192)
    enabled: bool = True

    @field_validator("schedule_expression")
    @classmethod
    def _validate_schedule(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("cron(") or v.startswith("rate(") or v.startswith("at(")):
            raise ValueError(
                "schedule_expression must start with cron(...), rate(...), or at(...)"
            )
        return v


class TriggerUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    enabled: Optional[bool] = None
    schedule_expression: Optional[str] = Field(default=None, max_length=256)
    input_template: Optional[str] = Field(default=None, max_length=8192)

    @field_validator("schedule_expression")
    @classmethod
    def _validate_schedule(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("cron(") or v.startswith("rate(") or v.startswith("at(")):
            raise ValueError(
                "schedule_expression must start with cron(...), rate(...), or at(...)"
            )
        return v


class TriggerInvocationRecord(BaseModel):
    """A single trigger firing event (execution history)."""

    invocation_id: str
    trigger_id: str
    user_id: str
    deployment_id: str
    status: TriggerInvocationStatus
    source: str  # "schedule" | "webhook" | "event" | "manual"
    input_payload_preview: Optional[str] = None  # truncated to 1KB
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    invoked_at: str = Field(default_factory=_now_iso)
    ttl: Optional[int] = None  # unix epoch, 90-day retention


class TriggerResponse(BaseModel):
    trigger: TriggerConfig
    message: str = "ok"


class TriggerListResponse(BaseModel):
    triggers: list[TriggerConfig]


class TriggerHistoryResponse(BaseModel):
    invocations: list[TriggerInvocationRecord]


class TriggerFireRequest(BaseModel):
    """Body for manually firing a trigger via /triggers/{id}/test."""

    input: Optional[str] = Field(default=None, max_length=8192)
