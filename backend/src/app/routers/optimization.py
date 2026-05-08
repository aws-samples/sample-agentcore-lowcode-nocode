"""AgentCore Optimization REST API (Task 12).

Real API paths (bundles, evaluators, online-evals). Recommendations +
explicit A/B test APIs are returned as 501 with a clear "coming soon"
reason until they're in the SDK.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.models.optimization_models import (
    ConfigurationBundleListResponse,
    ConfigurationBundleRequest,
    ConfigurationBundleResponse,
    ConfigurationBundleUpdateRequest,
    EvaluatorListResponse,
    OnlineEvaluationConfigListResponse,
    OnlineEvaluationConfigRequest,
    OnlineEvaluationConfigResponse,
)
from app.services.optimization_service import (
    BundleStore,
    OnlineEvalStore,
    OptimizationService,
)
from app.shared.auth import get_user_email, require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")

router = APIRouter(prefix="/optimization", tags=["optimization"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _svc() -> OptimizationService:
    return OptimizationService(
        bundle_store=BundleStore(
            table_name=os.environ["OPTIMIZATION_BUNDLES_TABLE_NAME"], region=_region()
        ),
        online_eval_store=OnlineEvalStore(
            table_name=os.environ["OPTIMIZATION_ONLINE_EVALS_TABLE_NAME"],
            region=_region(),
        ),
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


# ---------------------------------------------------------------------------
# Configuration bundles
# ---------------------------------------------------------------------------


@router.post(
    "/bundles",
    response_model=ConfigurationBundleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bundle(
    req: ConfigurationBundleRequest,
    request: Request,
    user_id: str = Depends(require_user),
) -> ConfigurationBundleResponse:
    email = get_user_email(request) or ""
    try:
        rec = _svc().create_bundle(user_id, email, req)
    except ClientError as e:
        raise _aws_error(e)
    return ConfigurationBundleResponse(bundle=rec)


@router.get("/bundles", response_model=ConfigurationBundleListResponse)
async def list_bundles(user_id: str = Depends(require_user)) -> ConfigurationBundleListResponse:
    return ConfigurationBundleListResponse(bundles=_svc().list_bundles(user_id))


@router.get("/bundles/{bundle_id}", response_model=ConfigurationBundleResponse)
async def get_bundle(
    bundle_id: str,
    version_id: Optional[str] = Query(default=None),
    user_id: str = Depends(require_user),
) -> ConfigurationBundleResponse:
    bundle_id = _validate_id(bundle_id)
    try:
        rec, detail = _svc().get_bundle(user_id, bundle_id, version_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="bundle not found")
    except ClientError as e:
        raise _aws_error(e)
    # Strip any non-JSON-serializable fields (datetimes already convert via pydantic)
    return ConfigurationBundleResponse(bundle=rec, detail=_scrub(detail))


@router.get("/bundles/{bundle_id}/versions")
async def list_bundle_versions(
    bundle_id: str, user_id: str = Depends(require_user)
) -> dict:
    bundle_id = _validate_id(bundle_id)
    try:
        versions = _svc().list_versions(user_id, bundle_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="bundle not found")
    except ClientError as e:
        raise _aws_error(e)
    return {"versions": _scrub(versions)}


@router.put("/bundles/{bundle_id}", response_model=ConfigurationBundleResponse)
async def update_bundle(
    bundle_id: str,
    req: ConfigurationBundleUpdateRequest,
    request: Request,
    user_id: str = Depends(require_user),
) -> ConfigurationBundleResponse:
    bundle_id = _validate_id(bundle_id)
    email = get_user_email(request) or ""
    try:
        rec = _svc().update_bundle(user_id, email, bundle_id, req)
    except PermissionError:
        raise HTTPException(status_code=404, detail="bundle not found")
    except ClientError as e:
        raise _aws_error(e)
    return ConfigurationBundleResponse(bundle=rec)


@router.delete("/bundles/{bundle_id}")
async def delete_bundle(
    bundle_id: str, user_id: str = Depends(require_user)
) -> dict:
    bundle_id = _validate_id(bundle_id)
    try:
        _svc().delete_bundle(user_id, bundle_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="bundle not found")
    except ClientError as e:
        raise _aws_error(e)
    return {"message": "deleted"}


# ---------------------------------------------------------------------------
# Evaluators (read-only list)
# ---------------------------------------------------------------------------


@router.get("/evaluators", response_model=EvaluatorListResponse)
async def list_evaluators(user_id: str = Depends(require_user)) -> EvaluatorListResponse:
    try:
        items = _svc().list_evaluators()
    except ClientError as e:
        raise _aws_error(e)
    return EvaluatorListResponse(evaluators=items)


# ---------------------------------------------------------------------------
# Online evaluation configs
# ---------------------------------------------------------------------------


@router.post(
    "/online-evals",
    response_model=OnlineEvaluationConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_online_eval(
    req: OnlineEvaluationConfigRequest,
    user_id: str = Depends(require_user),
) -> OnlineEvaluationConfigResponse:
    try:
        rec = _svc().create_online_eval(user_id, req)
    except ClientError as e:
        raise _aws_error(e)
    return OnlineEvaluationConfigResponse(config=rec)


@router.get("/online-evals", response_model=OnlineEvaluationConfigListResponse)
async def list_online_evals(
    user_id: str = Depends(require_user),
) -> OnlineEvaluationConfigListResponse:
    return OnlineEvaluationConfigListResponse(configs=_svc().list_online_evals(user_id))


@router.get(
    "/online-evals/{config_id}", response_model=OnlineEvaluationConfigResponse
)
async def get_online_eval(
    config_id: str, user_id: str = Depends(require_user)
) -> OnlineEvaluationConfigResponse:
    config_id = _validate_id(config_id)
    try:
        rec, detail = _svc().get_online_eval(user_id, config_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="config not found")
    except ClientError as e:
        raise _aws_error(e)
    return OnlineEvaluationConfigResponse(config=rec, detail=_scrub(detail))


@router.delete("/online-evals/{config_id}")
async def delete_online_eval(
    config_id: str, user_id: str = Depends(require_user)
) -> dict:
    config_id = _validate_id(config_id)
    try:
        _svc().delete_online_eval(user_id, config_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="config not found")
    except ClientError as e:
        raise _aws_error(e)
    return {"message": "deleted"}


# ---------------------------------------------------------------------------
# Not-yet-available APIs (preview)
# ---------------------------------------------------------------------------


@router.post("/recommendations", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_recommendation(user_id: str = Depends(require_user)) -> dict:
    raise HTTPException(
        status_code=501,
        detail=(
            "The AgentCore Recommendations API is not yet available in boto3. "
            "Track https://docs.aws.amazon.com/bedrock-agentcore/ for its release."
        ),
    )


@router.post("/ab-tests", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_ab_test(user_id: str = Depends(require_user)) -> dict:
    raise HTTPException(
        status_code=501,
        detail=(
            "Explicit A/B testing API is not yet available in boto3. "
            "Gateway Rules can be used for manual traffic splitting in the meantime."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scrub(obj):
    """Remove ResponseMetadata + convert datetimes for JSON safety."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k != "ResponseMetadata"}
    if isinstance(obj, list):
        return [_scrub(i) for i in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj
