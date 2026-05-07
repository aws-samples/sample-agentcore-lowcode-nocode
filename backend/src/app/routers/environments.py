"""Environment promotion API (Task 07).

Endpoints:
  GET    /api/environments/{deployment_id}              - list bindings (dev/staging/prod)
  PUT    /api/environments/{deployment_id}/{env}/config - update config overrides
  POST   /api/environments/{deployment_id}/promote      - request a promotion
  POST   /api/environments/{deployment_id}/promotions/{id}/approve  - approve
  POST   /api/environments/{deployment_id}/promotions/{id}/reject   - reject
  GET    /api/environments/{deployment_id}/promotions   - list promotion audit
"""

from __future__ import annotations

import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.environment_models import (
    ApproveRequest,
    Environment,
    EnvironmentBindingListResponse,
    PromotionListResponse,
    PromotionRequest,
    PromotionResponse,
    RejectRequest,
    UpdateEnvConfigRequest,
)
from app.services.promotion_service import (
    EnvironmentBindingStore,
    PromotionService,
    PromotionStore,
)
from app.services.version_store import VersionStore
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

router = APIRouter(prefix="/environments", tags=["environments"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _svc() -> PromotionService:
    return PromotionService(
        env_store=EnvironmentBindingStore(
            table_name=os.environ["ENVIRONMENTS_TABLE_NAME"], region=_region()
        ),
        promo_store=PromotionStore(
            table_name=os.environ["PROMOTIONS_TABLE_NAME"], region=_region()
        ),
        version_store=VersionStore(
            table_name=os.environ["VERSIONS_TABLE_NAME"], region=_region()
        ),
    )


def _validate_id(deployment_id: str) -> str:
    if not _ID_RE.match(deployment_id):
        raise HTTPException(status_code=400, detail="Invalid deployment_id")
    return deployment_id


def _require_owner(deployment_id: str, user_id: str) -> None:
    versions = VersionStore(
        table_name=os.environ["VERSIONS_TABLE_NAME"], region=_region()
    ).list_for_deployment(deployment_id)
    if not versions or not any(v.user_id == user_id for v in versions):
        raise HTTPException(status_code=404, detail="deployment not found")


@router.get("/{deployment_id}", response_model=EnvironmentBindingListResponse)
async def list_environments(
    deployment_id: str, user_id: str = Depends(require_user)
) -> EnvironmentBindingListResponse:
    deployment_id = _validate_id(deployment_id)
    _require_owner(deployment_id, user_id)
    bindings = _svc().list_bindings(deployment_id)
    # Filter to this user (belt and braces — the ownership check above already
    # established they own at least one version)
    mine = [b for b in bindings if b.user_id == user_id]
    return EnvironmentBindingListResponse(bindings=mine)


@router.put(
    "/{deployment_id}/{env}/config",
    response_model=EnvironmentBindingListResponse,
)
async def update_env_config(
    deployment_id: str,
    env: Environment,
    req: UpdateEnvConfigRequest,
    user_id: str = Depends(require_user),
) -> EnvironmentBindingListResponse:
    deployment_id = _validate_id(deployment_id)
    _require_owner(deployment_id, user_id)
    try:
        _svc().update_overrides(deployment_id, env, req.overrides, user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="deployment not found")
    bindings = _svc().list_bindings(deployment_id)
    mine = [b for b in bindings if b.user_id == user_id]
    return EnvironmentBindingListResponse(bindings=mine)


@router.post(
    "/{deployment_id}/promote",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_promotion(
    deployment_id: str,
    req: PromotionRequest,
    user_id: str = Depends(require_user),
) -> PromotionResponse:
    deployment_id = _validate_id(deployment_id)
    if req.deployment_id != deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id mismatch")
    _require_owner(deployment_id, user_id)
    try:
        record = _svc().request(user_id, req)
    except PermissionError:
        raise HTTPException(status_code=404, detail="not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PromotionResponse(promotion=record)


@router.post(
    "/{deployment_id}/promotions/{promotion_id}/approve",
    response_model=PromotionResponse,
)
async def approve_promotion(
    deployment_id: str,
    promotion_id: str,
    req: ApproveRequest,
    user_id: str = Depends(require_user),
) -> PromotionResponse:
    deployment_id = _validate_id(deployment_id)
    _require_owner(deployment_id, user_id)
    try:
        record = _svc().approve(user_id, promotion_id, req.comment)
    except PermissionError:
        raise HTTPException(status_code=404, detail="promotion not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if record.deployment_id != deployment_id:
        raise HTTPException(status_code=404, detail="promotion not found")
    return PromotionResponse(promotion=record)


@router.post(
    "/{deployment_id}/promotions/{promotion_id}/reject",
    response_model=PromotionResponse,
)
async def reject_promotion(
    deployment_id: str,
    promotion_id: str,
    req: RejectRequest,
    user_id: str = Depends(require_user),
) -> PromotionResponse:
    deployment_id = _validate_id(deployment_id)
    _require_owner(deployment_id, user_id)
    try:
        record = _svc().reject(user_id, promotion_id, req.reason)
    except PermissionError:
        raise HTTPException(status_code=404, detail="promotion not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if record.deployment_id != deployment_id:
        raise HTTPException(status_code=404, detail="promotion not found")
    return PromotionResponse(promotion=record)


@router.get(
    "/{deployment_id}/promotions", response_model=PromotionListResponse
)
async def list_promotions(
    deployment_id: str, user_id: str = Depends(require_user)
) -> PromotionListResponse:
    deployment_id = _validate_id(deployment_id)
    _require_owner(deployment_id, user_id)
    promotions = _svc().list_for_deployment(deployment_id)
    return PromotionListResponse(promotions=[p for p in promotions if p.user_id == user_id])
