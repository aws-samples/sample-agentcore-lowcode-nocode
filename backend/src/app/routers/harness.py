"""AgentCore Harness REST API (Task 11).

Endpoints:
  POST   /api/harness               - Create a harness
  GET    /api/harness               - List caller's harnesses
  GET    /api/harness/{id}          - Get single harness (refreshed from AWS)
  POST   /api/harness/{id}/invoke   - Invoke the harness
  DELETE /api/harness/{id}          - Delete the harness
  GET    /api/harness/meta/region   - Report region + whether Harness is available
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.harness_models import (
    HarnessCreateRequest,
    HarnessInvokeRequest,
    HarnessInvokeResponse,
    HarnessListResponse,
    HarnessRecord,
    HarnessResponse,
)
from app.services.harness_deployer import HarnessDeployer, HarnessStore
from app.services.harness_invoker import HarnessInvoker
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Preview regions published by the service
SUPPORTED_REGIONS = {"us-east-1", "us-west-2", "ap-southeast-2", "eu-central-1"}

router = APIRouter(prefix="/harness", tags=["harness"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _execution_role_arn() -> str:
    arn = os.environ.get("HARNESS_EXECUTION_ROLE_ARN", "")
    if not arn:
        raise RuntimeError("HARNESS_EXECUTION_ROLE_ARN env var not set")
    return arn


def _store() -> HarnessStore:
    return HarnessStore(
        table_name=os.environ["HARNESS_TABLE_NAME"], region=_region()
    )


def _deployer() -> HarnessDeployer:
    return HarnessDeployer(_store())


def _validate_id(harness_id: str) -> str:
    if not _ID_RE.match(harness_id):
        raise HTTPException(status_code=400, detail="Invalid harness_id")
    return harness_id


def _require_owner(harness_id: str, user_id: str) -> HarnessRecord:
    rec = _store().get(harness_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(status_code=404, detail="harness not found")
    return rec


def _region_guard() -> None:
    if _region() not in SUPPORTED_REGIONS:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"AgentCore Harness is not available in {_region()}. "
                f"Supported: {sorted(SUPPORTED_REGIONS)}"
            ),
        )


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@router.get("/meta/region")
async def region_meta() -> dict:
    return {
        "region": _region(),
        "available": _region() in SUPPORTED_REGIONS,
        "supported_regions": sorted(SUPPORTED_REGIONS),
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=HarnessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_harness(
    req: HarnessCreateRequest, user_id: str = Depends(require_user)
) -> HarnessResponse:
    _region_guard()
    try:
        rec = _deployer().create(user_id, req, _execution_role_arn())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        logger.exception("create_harness failed")
        if code in ("AccessDeniedException", "ValidationException"):
            raise HTTPException(status_code=400, detail=f"{code}: {msg}")
        raise HTTPException(status_code=503, detail=f"AWS error: {code}")
    return HarnessResponse(harness=rec)


@router.get("", response_model=HarnessListResponse)
async def list_harnesses(user_id: str = Depends(require_user)) -> HarnessListResponse:
    return HarnessListResponse(harnesses=_store().list_for_user(user_id))


@router.get("/{harness_id}", response_model=HarnessResponse)
async def get_harness(
    harness_id: str,
    refresh: bool = False,
    user_id: str = Depends(require_user),
) -> HarnessResponse:
    harness_id = _validate_id(harness_id)
    rec = _require_owner(harness_id, user_id)
    if refresh:
        try:
            rec = _deployer().refresh(rec)
        except ClientError as e:
            logger.warning("refresh failed: %s", e)
    return HarnessResponse(harness=rec)


@router.post("/{harness_id}/invoke", response_model=HarnessInvokeResponse)
async def invoke_harness(
    harness_id: str,
    req: HarnessInvokeRequest,
    user_id: str = Depends(require_user),
) -> HarnessInvokeResponse:
    harness_id = _validate_id(harness_id)
    rec = _require_owner(harness_id, user_id)
    # If not READY yet, try a quick refresh
    if rec.status.value != "READY":
        try:
            rec = _deployer().refresh(rec)
        except ClientError:
            pass
    if rec.status.value != "READY":
        raise HTTPException(
            status_code=409,
            detail=f"harness not ready (status={rec.status.value})",
        )
    return HarnessInvoker().invoke(rec, req.prompt, req.session_id)


@router.delete("/{harness_id}")
async def delete_harness(
    harness_id: str, user_id: str = Depends(require_user)
) -> dict:
    harness_id = _validate_id(harness_id)
    rec = _require_owner(harness_id, user_id)
    _deployer().delete(rec)
    return {"message": "deleted", "harness_id": harness_id}
