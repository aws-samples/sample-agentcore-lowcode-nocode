"""Unit tests for approval service (Task 02, no AWS)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest

from app.models.approval_models import (
    ApprovalCreateRequest,
    ApprovalRequest,
    ApprovalResolveRequest,
    ApprovalStatus,
    ApprovalType,
)
from app.services.approval_service import ApprovalService


class InMemoryStore:
    def __init__(self) -> None:
        self.items: dict[str, ApprovalRequest] = {}

    def put(self, a: ApprovalRequest) -> ApprovalRequest:
        self.items[a.approval_id] = a
        return a

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        return self.items.get(approval_id)

    def list_for_user(self, user_id: str, status: Optional[ApprovalStatus] = None):
        res = [a for a in self.items.values() if a.user_id == user_id]
        if status is not None:
            res = [a for a in res if a.status == status]
        return res


@pytest.fixture
def svc() -> ApprovalService:
    return ApprovalService(InMemoryStore())  # type: ignore[arg-type]


def test_create_binary(svc: ApprovalService) -> None:
    a = svc.create(
        "u1",
        ApprovalCreateRequest(
            deployment_id="d1",
            title="Send email",
            description="Really?",
            timeout_minutes=60,
        ),
    )
    assert a.status == ApprovalStatus.PENDING
    assert a.user_id == "u1"
    assert a.approval_id.startswith("apr-")
    assert a.ttl is not None


def test_create_choice_requires_options(svc: ApprovalService) -> None:
    with pytest.raises(ValueError):
        svc.create(
            "u1",
            ApprovalCreateRequest(
                deployment_id="d1",
                approval_type=ApprovalType.CHOICE,
                title="Pick one",
            ),
        )


def test_resolve_approved(svc: ApprovalService) -> None:
    a = svc.create(
        "u1",
        ApprovalCreateRequest(deployment_id="d1", title="Do thing"),
    )
    out = svc.resolve(
        a,
        "u1",
        ApprovalResolveRequest(decision=ApprovalStatus.APPROVED, feedback="lgtm"),
    )
    assert out.status == ApprovalStatus.APPROVED
    assert out.resolved_by == "u1"
    assert out.resolution and out.resolution["feedback"] == "lgtm"


def test_resolve_twice_rejected(svc: ApprovalService) -> None:
    a = svc.create("u1", ApprovalCreateRequest(deployment_id="d1", title="t"))
    svc.resolve(a, "u1", ApprovalResolveRequest(decision=ApprovalStatus.APPROVED))
    with pytest.raises(ValueError):
        svc.resolve(a, "u1", ApprovalResolveRequest(decision=ApprovalStatus.REJECTED))


def test_cannot_resolve_with_expired(svc: ApprovalService) -> None:
    a = svc.create("u1", ApprovalCreateRequest(deployment_id="d1", title="t"))
    with pytest.raises(ValueError):
        svc.resolve(a, "u1", ApprovalResolveRequest(decision=ApprovalStatus.EXPIRED))


def test_maybe_expire_marks_pending_past_timeout(svc: ApprovalService) -> None:
    a = svc.create(
        "u1",
        ApprovalCreateRequest(deployment_id="d1", title="t", timeout_minutes=1),
    )
    # Rewind created_at to 2 minutes ago
    a.created_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    res = svc._maybe_expire(a)
    assert res.status == ApprovalStatus.EXPIRED


def test_maybe_expire_does_not_touch_resolved(svc: ApprovalService) -> None:
    a = svc.create("u1", ApprovalCreateRequest(deployment_id="d1", title="t"))
    svc.resolve(a, "u1", ApprovalResolveRequest(decision=ApprovalStatus.APPROVED))
    # Pretend it was approved long ago
    a.created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    res = svc._maybe_expire(a)
    assert res.status == ApprovalStatus.APPROVED


def test_title_length_validation() -> None:
    with pytest.raises(ValueError):
        ApprovalCreateRequest(deployment_id="d1", title="")
