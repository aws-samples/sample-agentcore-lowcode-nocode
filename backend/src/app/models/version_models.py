"""Agent version / snapshot models (Task 03).

Versions are captured automatically at each deploy. The snapshot records
everything needed to understand *what was deployed*, enabling diff + rollback.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentVersion(BaseModel):
    """A single, immutable snapshot of a deployment's state."""

    deployment_id: str
    version: int
    user_id: str
    workflow_snapshot: dict[str, Any] = Field(default_factory=dict)
    agent_code: Optional[str] = None
    agent_code_hash: Optional[str] = None
    model_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    tools_config: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: Optional[str] = None
    memory_config: Optional[dict[str, Any]] = None
    policy_config: Optional[dict[str, Any]] = None
    guardrails_config: Optional[dict[str, Any]] = None
    knowledge_base_config: Optional[dict[str, Any]] = None
    runtime_arn: Optional[str] = None
    runtime_id: Optional[str] = None
    change_description: str = ""
    deployed_by: str = ""
    deployed_at: str = Field(default_factory=_now_iso)
    status: str = "active"  # active | rolled-back | archived

    @staticmethod
    def compute_hash(agent_code: Optional[str]) -> Optional[str]:
        if not agent_code:
            return None
        return hashlib.sha256(agent_code.encode("utf-8")).hexdigest()


class VersionSummary(BaseModel):
    deployment_id: str
    version: int
    user_id: str
    status: str
    deployed_by: str
    deployed_at: str
    change_description: str
    agent_code_hash: Optional[str] = None
    runtime_id: Optional[str] = None


class VersionListResponse(BaseModel):
    versions: list[VersionSummary]


class VersionResponse(BaseModel):
    version: AgentVersion


class VersionDiff(BaseModel):
    deployment_id: str
    from_version: int
    to_version: int
    changes: list[dict[str, Any]]  # list of {field, from, to}


class RollbackRequest(BaseModel):
    target_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=1024)


class RollbackResult(BaseModel):
    deployment_id: str
    new_version: int
    restored_from_version: int
    workflow_snapshot: dict[str, Any]
    message: str = "rolled back to previous version; redeploy to apply"


class SnapshotCreateRequest(BaseModel):
    deployment_id: str = Field(..., min_length=1, max_length=128)
    user_id: Optional[str] = None  # overridden by auth
    workflow_snapshot: dict[str, Any] = Field(default_factory=dict)
    agent_code: Optional[str] = None
    model_config_snapshot: dict[str, Any] = Field(default_factory=dict)
    tools_config: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: Optional[str] = None
    memory_config: Optional[dict[str, Any]] = None
    policy_config: Optional[dict[str, Any]] = None
    guardrails_config: Optional[dict[str, Any]] = None
    knowledge_base_config: Optional[dict[str, Any]] = None
    runtime_arn: Optional[str] = None
    runtime_id: Optional[str] = None
    change_description: str = ""


def compute_diff(
    a: AgentVersion, b: AgentVersion
) -> list[dict[str, Any]]:
    """Compute a field-level diff suitable for UI rendering."""
    changes: list[dict[str, Any]] = []
    fields = [
        "system_prompt",
        "agent_code_hash",
        "model_config_snapshot",
        "tools_config",
        "memory_config",
        "policy_config",
        "guardrails_config",
        "knowledge_base_config",
        "runtime_id",
    ]
    for f in fields:
        va = getattr(a, f, None)
        vb = getattr(b, f, None)
        if _normalize(va) != _normalize(vb):
            changes.append({"field": f, "from": va, "to": vb})
    return changes


def _normalize(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str)
    return v
