"""AWS Agent Registry REST API (Task 13)."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.models.registry_models import (
    AutoPublishRequest,
    AutoPublishSourceType,
    RecordApprovalRequest,
    RecordCreateRequest,
    RecordListResponse,
    RecordRejectRequest,
    RecordResponse,
    RecordSummary,
    RegistryListResponse,
    RegistryResponse,
    RegistrySetupRequest,
)
from app.services.registry_service import (
    RegistryOwnershipStore,
    RegistryService,
    _platform_admin_ids,
)
from app.shared.auth import get_user_email, require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")

router = APIRouter(prefix="/registry", tags=["registry"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _svc() -> RegistryService:
    return RegistryService(
        ownership=RegistryOwnershipStore(
            table_name=os.environ["REGISTRY_OWNERSHIP_TABLE_NAME"],
            region=_region(),
        )
    )


def _validate_id(v: str) -> str:
    if not _ID_RE.match(v):
        raise HTTPException(status_code=400, detail="Invalid id")
    return v


def _aws_error(e: ClientError) -> HTTPException:
    code = e.response.get("Error", {}).get("Code", "")
    msg = e.response.get("Error", {}).get("Message", str(e))
    if code in ("AccessDeniedException", "ValidationException", "ResourceNotFoundException"):
        return HTTPException(status_code=400, detail=f"{code}: {msg}")
    return HTTPException(status_code=503, detail=f"AWS error: {code}: {msg}")


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k != "ResponseMetadata"}
    if isinstance(obj, list):
        return [_scrub(i) for i in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------------------
# Registries (admin)
# ---------------------------------------------------------------------------


@router.post(
    "/setup", response_model=RegistryResponse, status_code=status.HTTP_201_CREATED
)
async def create_registry(
    req: RegistrySetupRequest, user_id: str = Depends(require_user)
) -> RegistryResponse:
    try:
        r = _svc().create_registry(user_id, req)
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    except ClientError as e:
        raise _aws_error(e)
    return RegistryResponse(registry=r)


@router.get("/list", response_model=RegistryListResponse)
async def list_registries(user_id: str = Depends(require_user)) -> RegistryListResponse:
    try:
        items = _svc().list_registries()
    except ClientError as e:
        raise _aws_error(e)
    return RegistryListResponse(registries=items)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@router.post(
    "/records",
    response_model=RecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_record(
    req: RecordCreateRequest,
    request: Request,
    user_id: str = Depends(require_user),
) -> RecordResponse:
    email = get_user_email(request) or ""
    try:
        rec = _svc().create_record(user_id, email, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ClientError as e:
        raise _aws_error(e)
    return RecordResponse(record=rec)


@router.get("/records", response_model=RecordListResponse)
async def list_records(
    registry_id: str = Query(..., min_length=1, max_length=128),
    status_filter: Optional[str] = Query(default=None, max_length=32),
    descriptor_type: Optional[str] = Query(default=None, max_length=32),
    name: Optional[str] = Query(default=None, max_length=128),
    user_id: str = Depends(require_user),
) -> RecordListResponse:
    try:
        items = _svc().list_records(
            registry_id, status_filter=status_filter, descriptor_type=descriptor_type, name_filter=name
        )
    except ClientError as e:
        raise _aws_error(e)
    return RecordListResponse(records=items)


@router.get("/records/{record_id}", response_model=RecordResponse)
async def get_record(
    record_id: str,
    registry_id: str = Query(..., min_length=1, max_length=128),
    user_id: str = Depends(require_user),
) -> RecordResponse:
    record_id = _validate_id(record_id)
    try:
        detail = _svc().get_record(registry_id, record_id)
    except ClientError as e:
        raise _aws_error(e)
    clean = _scrub(detail)
    arn = clean.get("recordArn", "")
    rec = RecordSummary(
        registry_id=registry_id,
        registry_arn=clean.get("registryArn", ""),
        record_id=record_id,
        record_arn=arn,
        name=clean.get("name", ""),
        description=clean.get("description", "") or "",
        descriptor_type=clean.get("descriptorType", ""),
        record_version=clean.get("recordVersion"),
        status=clean.get("status", "UNKNOWN"),
        created_at=clean.get("createdAt"),
        updated_at=clean.get("updatedAt"),
    )
    return RecordResponse(record=rec, detail=clean)


@router.delete("/records/{record_id}")
async def delete_record(
    record_id: str,
    registry_id: str = Query(..., min_length=1, max_length=128),
    user_id: str = Depends(require_user),
) -> dict:
    record_id = _validate_id(record_id)
    try:
        _svc().delete_record(user_id, registry_id, record_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="record not found")
    except ClientError as e:
        raise _aws_error(e)
    return {"message": "deleted"}


@router.post("/records/{record_id}/submit")
async def submit_record(
    record_id: str,
    registry_id: str = Query(..., min_length=1, max_length=128),
    user_id: str = Depends(require_user),
) -> dict:
    record_id = _validate_id(record_id)
    try:
        r = _svc().submit_for_approval(user_id, registry_id, record_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="record not found")
    except ClientError as e:
        raise _aws_error(e)
    return _scrub(r)


@router.post("/records/{record_id}/approve")
async def approve_record(
    record_id: str,
    req: RecordApprovalRequest,
    registry_id: str = Query(..., min_length=1, max_length=128),
    user_id: str = Depends(require_user),
) -> dict:
    record_id = _validate_id(record_id)
    try:
        r = _svc().update_status(
            user_id, registry_id, record_id, "APPROVED", req.status_reason
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    except ClientError as e:
        raise _aws_error(e)
    return _scrub(r)


@router.post("/records/{record_id}/reject")
async def reject_record(
    record_id: str,
    req: RecordRejectRequest,
    registry_id: str = Query(..., min_length=1, max_length=128),
    user_id: str = Depends(require_user),
) -> dict:
    record_id = _validate_id(record_id)
    try:
        r = _svc().update_status(
            user_id, registry_id, record_id, "REJECTED", req.status_reason
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    except ClientError as e:
        raise _aws_error(e)
    return _scrub(r)


@router.get("/search", response_model=RecordListResponse)
async def search_records(
    registry_id: str = Query(..., min_length=1, max_length=128),
    q: str = Query(default="", max_length=256),
    descriptor_type: Optional[str] = Query(default=None, max_length=32),
    user_id: str = Depends(require_user),
) -> RecordListResponse:
    try:
        items = _svc().search(registry_id, q, descriptor_type=descriptor_type)
    except ClientError as e:
        raise _aws_error(e)
    return RecordListResponse(records=items)


@router.post("/auto-publish", response_model=RecordResponse)
async def auto_publish(
    req: AutoPublishRequest,
    user_id: str = Depends(require_user),
    user_email: str = Depends(get_user_email),
) -> RecordResponse:
    """One-click publish: turn a deployment / tool / harness the user just
    created into a registry record without hand-typing descriptor JSON.
    """
    svc = _svc()
    try:
        if req.source_type == AutoPublishSourceType.HARNESS:
            from app.services.harness_deployer import HarnessStore

            store = HarnessStore(
                table_name=os.environ["HARNESS_TABLE_NAME"], region=_region()
            )
            rec = store.get(req.source_id)
            if not rec or rec.user_id != user_id:
                raise HTTPException(status_code=404, detail="harness not found")
            if rec.status.value != "READY":
                raise HTTPException(
                    status_code=409,
                    detail=f"harness not READY (status: {rec.status.value})",
                )
            result = svc.auto_publish_for_harness(
                user_id,
                user_email,
                req.registry_id,
                rec.model_dump(mode="json"),
                name=req.name,
                description=req.description,
                submit_for_approval=req.submit_for_approval,
            )
        elif req.source_type == AutoPublishSourceType.TOOL:
            if not req.tool_payload:
                raise HTTPException(
                    status_code=400,
                    detail="tool_payload required for source_type=tool",
                )
            result = svc.auto_publish_for_tool(
                user_id,
                user_email,
                req.registry_id,
                req.tool_payload,
                name=req.name,
                description=req.description,
                submit_for_approval=req.submit_for_approval,
            )
        else:  # DEPLOYMENT
            # Load deployment metadata from the deployments table.
            from app.services.dynamodb_storage import (
                _get_dynamodb_resource,
                _get_item,
                _get_table,
            )

            table = _get_table(
                _get_dynamodb_resource(_region()),
                os.environ.get("DEPLOYMENT_TABLE_NAME", ""),
            )
            dep = _get_item(table, {"deployment_id": req.source_id}) if table else None
            if not dep:
                raise HTTPException(status_code=404, detail="deployment not found")
            if str(dep.get("user_id", "")) != user_id:
                raise HTTPException(status_code=404, detail="deployment not found")
            endpoint = dep.get("endpoint") or dep.get("invoke_url") or None
            metadata = {
                k: v
                for k, v in dep.items()
                if k not in ("deployment_id", "user_id")
            }
            result = svc.auto_publish_for_deployment(
                user_id,
                user_email,
                req.registry_id,
                req.source_id,
                str(dep.get("deployment_type", "runtime")),
                str(endpoint) if endpoint else None,
                _scrub(metadata),
                name=req.name,
                description=req.description,
                submit_for_approval=req.submit_for_approval,
            )
    except ClientError as e:
        raise _aws_error(e)

    if not result:
        raise HTTPException(status_code=500, detail="auto-publish failed")
    return RecordResponse(record=result)
