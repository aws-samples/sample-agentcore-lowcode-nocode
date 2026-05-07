"""Marketplace service (Task 09).

Lifecycle:
  draft -> pending_review -> published | rejected
  published -> deprecated

Tenant model:
  - Authors own their items (author_id == user_id)
  - Admins can approve/reject others' pending items
  - Non-authors can only see status=published
  - Reviews are owned by reviewer_id; one review per (item, user)
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models.marketplace_models import (
    ItemStatus,
    MarketplaceItem,
    MarketplaceReview,
    PublishRequest,
    SubmitReviewRequest,
    UpdateItemRequest,
)
from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _delete_item,
    _get_dynamodb_resource,
    _get_item,
    _get_table,
    _put_item,
    _scan_table,
)

logger = logging.getLogger(__name__)


# Inline safety check: prevent obviously-dangerous Python in published tools.
_DANGEROUS_PATTERNS = [
    r"\bos\.system\s*\(",
    r"\bsubprocess\.",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\b__import__\s*\(",
    r"\beval\s*\(",
    r"\bopen\s*\(\s*['\"]/etc",
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class MarketplaceItemStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, item: MarketplaceItem) -> MarketplaceItem:
        _put_item(self._table, _convert_floats_to_decimals(item.model_dump(mode="json")))
        return item

    def get(self, item_id: str) -> Optional[MarketplaceItem]:
        it = _get_item(self._table, {"item_id": item_id})
        if not it:
            return None
        return MarketplaceItem.model_validate(_convert_decimals_to_floats(dict(it)))

    def delete(self, item_id: str) -> None:
        _delete_item(self._table, {"item_id": item_id})

    def scan(self) -> list[MarketplaceItem]:
        return [
            MarketplaceItem.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in _scan_table(self._table)
        ]


class MarketplaceReviewStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, r: MarketplaceReview) -> MarketplaceReview:
        _put_item(self._table, _convert_floats_to_decimals(r.model_dump(mode="json")))
        return r

    def get(self, review_id: str) -> Optional[MarketplaceReview]:
        it = _get_item(self._table, {"review_id": review_id})
        if not it:
            return None
        return MarketplaceReview.model_validate(_convert_decimals_to_floats(dict(it)))

    def list_for_item(self, item_id: str) -> list[MarketplaceReview]:
        items = _scan_table(self._table)
        out = [
            MarketplaceReview.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in items
            if i.get("item_id") == item_id
        ]
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def find_for_user(self, item_id: str, user_id: str) -> Optional[MarketplaceReview]:
        for r in self.list_for_item(item_id):
            if r.user_id == user_id:
                return r
        return None


class MarketplaceService:
    def __init__(
        self,
        items: MarketplaceItemStore,
        reviews: MarketplaceReviewStore,
        admin_user_ids: Optional[set[str]] = None,
    ) -> None:
        self._items = items
        self._reviews = reviews
        self._admin_ids = admin_user_ids or set()

    def _is_admin(self, user_id: str) -> bool:
        return user_id in self._admin_ids

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def create(self, user_id: str, req: PublishRequest, author: str = "") -> MarketplaceItem:
        self._validate_safety(req.tool_code)
        item_id = f"mi-{uuid.uuid4().hex[:16]}"
        item = MarketplaceItem(
            item_id=item_id,
            author_id=user_id,
            author=author or user_id,
            item_type=req.item_type,
            name=req.name,
            display_name=req.display_name,
            description=req.description,
            long_description=req.long_description,
            version=req.version,
            icon_url=req.icon_url,
            categories=req.categories,
            tags=req.tags,
            status=ItemStatus.DRAFT,
            workflow_json=req.workflow_json,
            tool_code=req.tool_code,
            requirements=req.requirements,
            model_requirements=req.model_requirements,
            configuration_schema=req.configuration_schema,
        )
        return self._items.put(item)

    def update(
        self,
        user_id: str,
        item_id: str,
        req: UpdateItemRequest,
    ) -> MarketplaceItem:
        item = self._items.get(item_id)
        if item is None or item.author_id != user_id:
            raise PermissionError("not found")
        if item.status == ItemStatus.PUBLISHED:
            raise ValueError("cannot edit a published item; create a new version")
        # Apply partial updates
        data = item.model_dump()
        for field, value in req.model_dump(exclude_unset=True).items():
            if value is not None:
                data[field] = value
        if req.tool_code is not None:
            self._validate_safety(req.tool_code)
        data["updated_at"] = _now()
        new = MarketplaceItem.model_validate(data)
        return self._items.put(new)

    def submit_for_review(self, user_id: str, item_id: str) -> MarketplaceItem:
        item = self._items.get(item_id)
        if item is None or item.author_id != user_id:
            raise PermissionError("not found")
        if item.status != ItemStatus.DRAFT:
            raise ValueError(f"cannot submit: current status {item.status.value}")
        item.status = ItemStatus.PENDING_REVIEW
        item.updated_at = _now()
        return self._items.put(item)

    def approve(self, admin_user_id: str, item_id: str) -> MarketplaceItem:
        if not self._is_admin(admin_user_id):
            raise PermissionError("admin only")
        item = self._items.get(item_id)
        if item is None:
            raise PermissionError("not found")
        if item.status != ItemStatus.PENDING_REVIEW:
            raise ValueError(f"cannot approve: status {item.status.value}")
        item.status = ItemStatus.PUBLISHED
        item.published_at = _now()
        item.updated_at = _now()
        return self._items.put(item)

    def reject(
        self, admin_user_id: str, item_id: str, reason: str
    ) -> MarketplaceItem:
        if not self._is_admin(admin_user_id):
            raise PermissionError("admin only")
        item = self._items.get(item_id)
        if item is None:
            raise PermissionError("not found")
        if item.status != ItemStatus.PENDING_REVIEW:
            raise ValueError(f"cannot reject: status {item.status.value}")
        item.status = ItemStatus.REJECTED
        item.rejection_reason = reason
        item.updated_at = _now()
        return self._items.put(item)

    def deprecate(self, user_id: str, item_id: str) -> MarketplaceItem:
        item = self._items.get(item_id)
        if item is None:
            raise PermissionError("not found")
        if item.author_id != user_id and not self._is_admin(user_id):
            raise PermissionError("not found")
        if item.status != ItemStatus.PUBLISHED:
            raise ValueError(f"can only deprecate published items, not {item.status.value}")
        item.status = ItemStatus.DEPRECATED
        item.updated_at = _now()
        return self._items.put(item)

    def delete_draft(self, user_id: str, item_id: str) -> bool:
        item = self._items.get(item_id)
        if item is None or item.author_id != user_id:
            raise PermissionError("not found")
        if item.status not in (ItemStatus.DRAFT, ItemStatus.REJECTED):
            raise ValueError(f"cannot delete a {item.status.value} item")
        self._items.delete(item_id)
        return True

    def get_visible(self, user_id: str, item_id: str) -> Optional[MarketplaceItem]:
        """Return the item if the caller is allowed to see it."""
        item = self._items.get(item_id)
        if item is None:
            return None
        if item.status == ItemStatus.PUBLISHED:
            return item
        if item.author_id == user_id or self._is_admin(user_id):
            return item
        return None

    def browse(
        self,
        user_id: str,
        *,
        item_type: Optional[str] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
        include_own_drafts: bool = False,
    ) -> list[MarketplaceItem]:
        all_items = self._items.scan()
        visible = [
            i
            for i in all_items
            if i.status == ItemStatus.PUBLISHED
            or (include_own_drafts and i.author_id == user_id)
        ]
        if item_type:
            visible = [i for i in visible if i.item_type.value == item_type]
        if category:
            visible = [i for i in visible if category in (i.categories or [])]
        if query:
            q = query.lower()
            visible = [
                i
                for i in visible
                if q in (i.name or "").lower()
                or q in (i.display_name or "").lower()
                or q in (i.description or "").lower()
                or any(q in t.lower() for t in (i.tags or []))
            ]
        return sorted(
            visible,
            key=lambda i: (
                -i.install_count,
                -(i.rating_average or 0),
                i.updated_at,
            ),
            reverse=False,
        )

    def list_own(self, user_id: str) -> list[MarketplaceItem]:
        return [i for i in self._items.scan() if i.author_id == user_id]

    def list_pending(self, admin_user_id: str) -> list[MarketplaceItem]:
        if not self._is_admin(admin_user_id):
            raise PermissionError("admin only")
        return [
            i for i in self._items.scan() if i.status == ItemStatus.PENDING_REVIEW
        ]

    def install(self, user_id: str, item_id: str) -> MarketplaceItem:
        item = self._items.get(item_id)
        if item is None or item.status != ItemStatus.PUBLISHED:
            raise PermissionError("not installable")
        item.install_count += 1
        item.updated_at = _now()
        return self._items.put(item)

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def add_or_replace_review(
        self, user_id: str, item_id: str, req: SubmitReviewRequest
    ) -> MarketplaceReview:
        item = self._items.get(item_id)
        if item is None or item.status != ItemStatus.PUBLISHED:
            raise PermissionError("not reviewable")
        # One review per (item, user)
        existing = self._reviews.find_for_user(item_id, user_id)
        if existing:
            review = existing.model_copy(
                update={
                    "rating": req.rating,
                    "title": req.title,
                    "body": req.body,
                }
            )
        else:
            review = MarketplaceReview(
                review_id=f"rv-{uuid.uuid4().hex[:16]}",
                item_id=item_id,
                user_id=user_id,
                rating=req.rating,
                title=req.title,
                body=req.body,
            )
        self._reviews.put(review)
        # Recompute item's rolling rating
        reviews = self._reviews.list_for_item(item_id)
        item.rating_count = len(reviews)
        item.rating_average = (
            round(sum(r.rating for r in reviews) / len(reviews), 2)
            if reviews
            else 0.0
        )
        item.updated_at = _now()
        self._items.put(item)
        return review

    def list_reviews(self, item_id: str) -> list[MarketplaceReview]:
        item = self._items.get(item_id)
        if item is None:
            raise PermissionError("not found")
        return self._reviews.list_for_item(item_id)

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_safety(tool_code: Optional[str]) -> None:
        if not tool_code:
            return
        if _DANGEROUS_RE.search(tool_code):
            raise ValueError(
                "tool_code contains disallowed patterns "
                "(exec/eval/os.system/subprocess/__import__/etc.)"
            )
