"""Marketplace REST API (Task 09)."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.models.marketplace_models import (
    InstallResponse,
    ItemListResponse,
    ItemResponse,
    ItemType,
    PublishRequest,
    RejectRequest,
    ReviewListResponse,
    SubmitReviewRequest,
    UpdateItemRequest,
)
from app.services.marketplace_service import (
    MarketplaceItemStore,
    MarketplaceReviewStore,
    MarketplaceService,
)
from app.shared.auth import get_user_email, require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _admin_ids() -> set[str]:
    raw = os.environ.get("MARKETPLACE_ADMIN_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _svc() -> MarketplaceService:
    return MarketplaceService(
        items=MarketplaceItemStore(
            table_name=os.environ["MARKETPLACE_ITEMS_TABLE_NAME"],
            region=_region(),
        ),
        reviews=MarketplaceReviewStore(
            table_name=os.environ["MARKETPLACE_REVIEWS_TABLE_NAME"],
            region=_region(),
        ),
        admin_user_ids=_admin_ids(),
    )


def _validate_id(item_id: str) -> str:
    if not _ID_RE.match(item_id):
        raise HTTPException(status_code=400, detail="Invalid item_id")
    return item_id


# ---------------------------------------------------------------------------
# Public catalog
# ---------------------------------------------------------------------------


@router.get("/items", response_model=ItemListResponse)
async def browse(
    item_type: Optional[ItemType] = None,
    category: Optional[str] = Query(default=None, max_length=64),
    q: Optional[str] = Query(default=None, max_length=256),
    include_drafts: bool = False,
    user_id: str = Depends(require_user),
) -> ItemListResponse:
    items = _svc().browse(
        user_id,
        item_type=item_type.value if item_type else None,
        category=category,
        query=q,
        include_own_drafts=include_drafts,
    )
    return ItemListResponse(items=items)


@router.get("/items/mine", response_model=ItemListResponse)
async def list_mine(user_id: str = Depends(require_user)) -> ItemListResponse:
    return ItemListResponse(items=_svc().list_own(user_id))


@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str, user_id: str = Depends(require_user)
) -> ItemResponse:
    item_id = _validate_id(item_id)
    item = _svc().get_visible(user_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return ItemResponse(item=item)


@router.post(
    "/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    req: PublishRequest,
    request: Request,
    user_id: str = Depends(require_user),
) -> ItemResponse:
    email = get_user_email(request) or ""
    try:
        item = _svc().create(user_id, req, author=email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ItemResponse(item=item)


@router.put("/items/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    req: UpdateItemRequest,
    user_id: str = Depends(require_user),
) -> ItemResponse:
    item_id = _validate_id(item_id)
    try:
        item = _svc().update(user_id, item_id, req)
    except PermissionError:
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ItemResponse(item=item)


@router.post("/items/{item_id}/submit", response_model=ItemResponse)
async def submit_for_review(
    item_id: str, user_id: str = Depends(require_user)
) -> ItemResponse:
    item_id = _validate_id(item_id)
    try:
        item = _svc().submit_for_review(user_id, item_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ItemResponse(item=item)


@router.post("/items/{item_id}/install", response_model=InstallResponse)
async def install_item(
    item_id: str, user_id: str = Depends(require_user)
) -> InstallResponse:
    item_id = _validate_id(item_id)
    try:
        item = _svc().install(user_id, item_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="not installable")
    from datetime import datetime, timezone

    return InstallResponse(
        item_id=item_id,
        installed_at=datetime.now(timezone.utc).isoformat(),
        workflow_json=item.workflow_json,
        tool_code=item.tool_code,
        configuration_schema=item.configuration_schema,
    )


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: str, user_id: str = Depends(require_user)
) -> dict:
    item_id = _validate_id(item_id)
    try:
        _svc().delete_draft(user_id, item_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"message": "deleted"}


@router.post("/items/{item_id}/deprecate", response_model=ItemResponse)
async def deprecate_item(
    item_id: str, user_id: str = Depends(require_user)
) -> ItemResponse:
    item_id = _validate_id(item_id)
    try:
        item = _svc().deprecate(user_id, item_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="item not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ItemResponse(item=item)


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


@router.get("/items/{item_id}/reviews", response_model=ReviewListResponse)
async def list_reviews(
    item_id: str, user_id: str = Depends(require_user)
) -> ReviewListResponse:
    item_id = _validate_id(item_id)
    try:
        reviews = _svc().list_reviews(item_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="item not found")
    return ReviewListResponse(reviews=reviews)


@router.post("/items/{item_id}/reviews", response_model=ReviewListResponse)
async def submit_review(
    item_id: str,
    req: SubmitReviewRequest,
    user_id: str = Depends(require_user),
) -> ReviewListResponse:
    item_id = _validate_id(item_id)
    try:
        _svc().add_or_replace_review(user_id, item_id, req)
    except PermissionError:
        raise HTTPException(status_code=404, detail="not reviewable")
    return ReviewListResponse(reviews=_svc().list_reviews(item_id))


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@router.get("/admin/pending", response_model=ItemListResponse)
async def admin_list_pending(
    user_id: str = Depends(require_user),
) -> ItemListResponse:
    try:
        items = _svc().list_pending(user_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    return ItemListResponse(items=items)


@router.post("/admin/{item_id}/approve", response_model=ItemResponse)
async def admin_approve(
    item_id: str, user_id: str = Depends(require_user)
) -> ItemResponse:
    item_id = _validate_id(item_id)
    try:
        item = _svc().approve(user_id, item_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ItemResponse(item=item)


@router.post("/admin/{item_id}/reject", response_model=ItemResponse)
async def admin_reject(
    item_id: str,
    req: RejectRequest,
    user_id: str = Depends(require_user),
) -> ItemResponse:
    item_id = _validate_id(item_id)
    try:
        item = _svc().reject(user_id, item_id, req.reason)
    except PermissionError:
        raise HTTPException(status_code=403, detail="admin only")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ItemResponse(item=item)
