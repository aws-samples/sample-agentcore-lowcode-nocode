"""A2A (Agent-to-Agent) Protocol models (Task 05).

Partial implementation of the A2A v0.2 spec (a2a-protocol.org):
  - Agent Card (GET /.well-known/agent.json)
  - tasks/send and tasks/get JSON-RPC methods

Streaming (tasks/sendSubscribe) is declared off in capabilities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class A2ATaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentSkill(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., max_length=1024)
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """Published at GET /.well-known/agent.json for discovery."""

    name: str
    description: str
    url: str  # base URL of the A2A endpoint for this card
    version: str = "1.0.0"
    protocol_version: str = "0.2"
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {
            "streaming": False,
            "push_notifications": False,
            "state_transition_history": True,
        }
    )
    skills: list[AgentSkill] = Field(default_factory=list)
    authentication: dict[str, Any] = Field(
        default_factory=lambda: {"schemes": ["bearer"]}
    )


class A2AConfigRecord(BaseModel):
    """Per-deployment A2A config — agent card metadata + runtime binding."""

    deployment_id: str
    user_id: str
    enabled: bool = True
    name: str
    description: str = ""
    skills: list[AgentSkill] = Field(default_factory=list)
    runtime_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class A2AConfigRequest(BaseModel):
    deployment_id: str = Field(..., min_length=1, max_length=128)
    runtime_id: Optional[str] = Field(default=None, max_length=128)
    enabled: bool = True
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    skills: list[AgentSkill] = Field(default_factory=list)


class A2ATaskMessage(BaseModel):
    role: str = Field(..., pattern="^(user|agent)$")
    parts: list[dict[str, Any]]  # [{type:"text", text:"..."}]


class A2ATask(BaseModel):
    task_id: str
    deployment_id: str
    session_id: Optional[str] = None
    state: A2ATaskState = A2ATaskState.SUBMITTED
    messages: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    ttl: Optional[int] = None  # 30-day retention
