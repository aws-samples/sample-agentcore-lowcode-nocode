"""Agent version & rollback REST API (Task 03).

Mounted at `/api/deployments/{deployment_id}/versions`.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.version_models import (
    AgentVersion,
    RollbackRequest,
    RollbackResult,
    SnapshotCreateRequest,
    VersionListResponse,
    VersionResponse,
    VersionSummary,
)
from app.services.version_manager import VersionManager
from app.services.version_store import VersionStore
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

router = APIRouter(prefix="/deployments", tags=["versions"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _store() -> VersionStore:
    return VersionStore(
        table_name=os.environ["VERSIONS_TABLE_NAME"], region=_region()
    )


def _manager() -> VersionManager:
    return VersionManager(_store())


def _validate_id(deployment_id: str) -> str:
    if not _ID_RE.match(deployment_id):
        raise HTTPException(status_code=400, detail="Invalid deployment_id")
    return deployment_id


def _check_owner_on_versions(
    deployment_id: str, user_id: str
) -> list[AgentVersion]:
    versions = _store().list_for_deployment(deployment_id)
    if versions and any(v.user_id != user_id for v in versions):
        # If any existing row has a different owner, treat as not-found for this user
        if all(v.user_id != user_id for v in versions):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="deployment not found",
            )
    return versions


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get(
    "/{deployment_id}/versions", response_model=VersionListResponse
)
async def list_versions(
    deployment_id: str, user_id: str = Depends(require_user)
) -> VersionListResponse:
    deployment_id = _validate_id(deployment_id)
    versions = _check_owner_on_versions(deployment_id, user_id)
    visible = [v for v in versions if v.user_id == user_id]
    summaries = [
        VersionSummary(
            deployment_id=v.deployment_id,
            version=v.version,
            user_id=v.user_id,
            status=v.status,
            deployed_by=v.deployed_by,
            deployed_at=v.deployed_at,
            change_description=v.change_description,
            agent_code_hash=v.agent_code_hash,
            runtime_id=v.runtime_id,
        )
        for v in visible
    ]
    return VersionListResponse(versions=summaries)


# ---------------------------------------------------------------------------
# Get specific or active
# ---------------------------------------------------------------------------


@router.get(
    "/{deployment_id}/versions/active", response_model=VersionResponse
)
async def get_active_version(
    deployment_id: str, user_id: str = Depends(require_user)
) -> VersionResponse:
    deployment_id = _validate_id(deployment_id)
    versions = _check_owner_on_versions(deployment_id, user_id)
    active = [v for v in versions if v.user_id == user_id and v.status == "active"]
    if not active:
        raise HTTPException(status_code=404, detail="no active version")
    return VersionResponse(version=active[0])


@router.get(
    "/{deployment_id}/versions/diff", response_model=dict
)
async def get_diff(
    deployment_id: str,
    from_version: int = Query(..., ge=1),
    to_version: int = Query(..., ge=1),
    user_id: str = Depends(require_user),
) -> dict:
    deployment_id = _validate_id(deployment_id)
    _check_owner_on_versions(deployment_id, user_id)
    try:
        a, b, changes = _manager().diff(deployment_id, from_version, to_version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if a.user_id != user_id or b.user_id != user_id:
        raise HTTPException(status_code=404, detail="version not found")
    return {
        "deployment_id": deployment_id,
        "from_version": from_version,
        "to_version": to_version,
        "changes": changes,
    }


@router.get(
    "/{deployment_id}/versions/{version}", response_model=VersionResponse
)
async def get_version(
    deployment_id: str,
    version: int,
    user_id: str = Depends(require_user),
) -> VersionResponse:
    deployment_id = _validate_id(deployment_id)
    v = _store().get(deployment_id, version)
    if v is None or v.user_id != user_id:
        raise HTTPException(status_code=404, detail="version not found")
    return VersionResponse(version=v)


# ---------------------------------------------------------------------------
# Create snapshot (agent-facing; also used internally by deploy flow)
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/versions",
    response_model=VersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_snapshot(
    deployment_id: str,
    req: SnapshotCreateRequest,
    user_id: str = Depends(require_user),
) -> VersionResponse:
    deployment_id = _validate_id(deployment_id)
    if req.deployment_id != deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id mismatch")
    # If there are prior versions, enforce ownership
    prior = _store().list_for_deployment(deployment_id)
    if prior and any(p.user_id != user_id for p in prior):
        raise HTTPException(status_code=404, detail="deployment not found")
    v = _manager().snapshot(
        deployment_id=deployment_id,
        user_id=user_id,
        workflow_snapshot=req.workflow_snapshot,
        agent_code=req.agent_code,
        model_config_snapshot=req.model_config_snapshot,
        tools_config=req.tools_config,
        system_prompt=req.system_prompt,
        memory_config=req.memory_config,
        policy_config=req.policy_config,
        guardrails_config=req.guardrails_config,
        knowledge_base_config=req.knowledge_base_config,
        runtime_arn=req.runtime_arn,
        runtime_id=req.runtime_id,
        change_description=req.change_description,
        deployed_by=user_id,
    )
    return VersionResponse(version=v)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/versions/rollback",
    response_model=RollbackResult,
)
async def rollback_version(
    deployment_id: str,
    req: RollbackRequest,
    user_id: str = Depends(require_user),
) -> RollbackResult:
    deployment_id = _validate_id(deployment_id)
    _check_owner_on_versions(deployment_id, user_id)
    # Confirm target exists and is ours
    target = _store().get(deployment_id, req.target_version)
    if target is None or target.user_id != user_id:
        raise HTTPException(status_code=404, detail="version not found")
    try:
        return _manager().rollback(
            deployment_id,
            req.target_version,
            req.reason,
            actor_user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
