"""Unit tests for the Marketplace service (Task 09)."""

from __future__ import annotations

from typing import Optional

import pytest

from app.models.marketplace_models import (
    ItemStatus,
    ItemType,
    MarketplaceItem,
    MarketplaceReview,
    PublishRequest,
    SubmitReviewRequest,
    UpdateItemRequest,
)
from app.services.marketplace_service import MarketplaceService


class InMemoryItemStore:
    def __init__(self) -> None:
        self.items: dict[str, MarketplaceItem] = {}

    def put(self, i: MarketplaceItem) -> MarketplaceItem:
        self.items[i.item_id] = i
        return i

    def get(self, item_id: str) -> Optional[MarketplaceItem]:
        return self.items.get(item_id)

    def delete(self, item_id: str) -> None:
        self.items.pop(item_id, None)

    def scan(self) -> list[MarketplaceItem]:
        return list(self.items.values())


class InMemoryReviewStore:
    def __init__(self) -> None:
        self.items: dict[str, MarketplaceReview] = {}

    def put(self, r: MarketplaceReview) -> MarketplaceReview:
        self.items[r.review_id] = r
        return r

    def get(self, rid):
        return self.items.get(rid)

    def list_for_item(self, item_id):
        return [r for r in self.items.values() if r.item_id == item_id]

    def find_for_user(self, item_id, user_id):
        for r in self.list_for_item(item_id):
            if r.user_id == user_id:
                return r
        return None


@pytest.fixture
def svc() -> MarketplaceService:
    return MarketplaceService(
        items=InMemoryItemStore(),  # type: ignore[arg-type]
        reviews=InMemoryReviewStore(),  # type: ignore[arg-type]
        admin_user_ids={"admin-1"},
    )


def _publish_req(**overrides) -> PublishRequest:
    body = {
        "item_type": ItemType.TOOL,
        "name": "my-tool",
        "display_name": "My Tool",
        "description": "test",
    }
    body.update(overrides)
    return PublishRequest(**body)


def test_create_returns_draft(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req(), author="me@example.com")
    assert item.status == ItemStatus.DRAFT
    assert item.author_id == "u1"
    assert item.author == "me@example.com"


def test_lifecycle_draft_submit_approve(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    item = svc.submit_for_review("u1", item.item_id)
    assert item.status == ItemStatus.PENDING_REVIEW
    item = svc.approve("admin-1", item.item_id)
    assert item.status == ItemStatus.PUBLISHED
    assert item.published_at is not None


def test_non_admin_cannot_approve(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.submit_for_review("u1", item.item_id)
    with pytest.raises(PermissionError):
        svc.approve("u2", item.item_id)


def test_reject_records_reason(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.submit_for_review("u1", item.item_id)
    item = svc.reject("admin-1", item.item_id, "bad code")
    assert item.status == ItemStatus.REJECTED
    assert item.rejection_reason == "bad code"


def test_cannot_edit_published(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.submit_for_review("u1", item.item_id)
    svc.approve("admin-1", item.item_id)
    with pytest.raises(ValueError):
        svc.update("u1", item.item_id, UpdateItemRequest(description="x"))


def test_dangerous_tool_code_rejected_on_create(svc: MarketplaceService) -> None:
    with pytest.raises(ValueError):
        svc.create(
            "u1",
            _publish_req(tool_code="import os\nos.system('rm -rf /')"),
        )


def test_dangerous_tool_code_rejected_on_update(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    with pytest.raises(ValueError):
        svc.update(
            "u1",
            item.item_id,
            UpdateItemRequest(tool_code="exec('print(1)')"),
        )


def test_non_author_cannot_edit(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    with pytest.raises(PermissionError):
        svc.update("u2", item.item_id, UpdateItemRequest(description="hack"))


def test_unpublished_item_invisible_to_others(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    # owner sees
    assert svc.get_visible("u1", item.item_id) is not None
    # stranger does not
    assert svc.get_visible("u2", item.item_id) is None
    # admin sees
    assert svc.get_visible("admin-1", item.item_id) is not None


def test_browse_only_published(svc: MarketplaceService) -> None:
    item1 = svc.create("u1", _publish_req(name="a", display_name="A"))
    item2 = svc.create("u1", _publish_req(name="b", display_name="B"))
    svc.submit_for_review("u1", item1.item_id)
    svc.approve("admin-1", item1.item_id)
    # user2 should only see item1
    listed = svc.browse("u2")
    names = {i.name for i in listed}
    assert "a" in names
    assert "b" not in names


def test_install_increments_counter(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.submit_for_review("u1", item.item_id)
    svc.approve("admin-1", item.item_id)
    before = item.install_count
    updated = svc.install("u2", item.item_id)
    assert updated.install_count == before + 1


def test_cannot_install_unpublished(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    with pytest.raises(PermissionError):
        svc.install("u2", item.item_id)


def test_review_is_idempotent_per_user(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.submit_for_review("u1", item.item_id)
    svc.approve("admin-1", item.item_id)
    svc.add_or_replace_review(
        "u2", item.item_id, SubmitReviewRequest(rating=5, title="great", body="")
    )
    # same user updates their review
    svc.add_or_replace_review(
        "u2",
        item.item_id,
        SubmitReviewRequest(rating=3, title="changed mind", body=""),
    )
    reviews = svc.list_reviews(item.item_id)
    assert len(reviews) == 1
    assert reviews[0].rating == 3
    # item's rating updated too
    updated_item = svc._items.get(item.item_id)  # type: ignore[attr-defined]
    assert updated_item.rating_count == 1
    assert updated_item.rating_average == 3.0


def test_delete_draft(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.delete_draft("u1", item.item_id)
    assert svc._items.get(item.item_id) is None  # type: ignore[attr-defined]


def test_cannot_delete_published(svc: MarketplaceService) -> None:
    item = svc.create("u1", _publish_req())
    svc.submit_for_review("u1", item.item_id)
    svc.approve("admin-1", item.item_id)
    with pytest.raises(ValueError):
        svc.delete_draft("u1", item.item_id)
