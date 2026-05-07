"""Approval service: create, resolve, and expire approvals (Task 02).

The current execution model is **polling**: an agent tool creates an approval
request and repeatedly calls `GET /api/approvals/{id}` until status transitions
from `pending` to `approved|rejected|expired`.

A future version can wire SFN task tokens for push-based resume; that requires
the agent to run inside a Step Function, which is out of scope for this task.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.approval_models import (
    ApprovalCreateRequest,
    ApprovalRequest,
    ApprovalResolveRequest,
    ApprovalStatus,
)
from app.services.approval_store import ApprovalStore

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    def create(self, user_id: str, req: ApprovalCreateRequest) -> ApprovalRequest:
        if req.approval_type.value == "choice" and not req.options:
            raise ValueError("options required for choice approval")
        if req.approval_type.value == "form" and not req.form_schema:
            raise ValueError("form_schema required for form approval")
        if req.approval_type.value == "review" and req.content_to_review is None:
            raise ValueError("content_to_review required for review approval")

        approval_id = f"apr-{uuid.uuid4().hex[:16]}"
        now = _now()
        # TTL: keep records for 30 days after expiry so history survives
        expiry_ttl = int(
            (now + timedelta(minutes=req.timeout_minutes) + timedelta(days=30)).timestamp()
        )
        approval = ApprovalRequest(
            approval_id=approval_id,
            user_id=user_id,
            deployment_id=req.deployment_id,
            runtime_id=req.runtime_id,
            session_id=req.session_id,
            approval_type=req.approval_type,
            title=req.title,
            description=req.description,
            context=req.context,
            proposed_action=req.proposed_action,
            options=req.options,
            form_schema=req.form_schema,
            content_to_review=req.content_to_review,
            status=ApprovalStatus.PENDING,
            timeout_minutes=req.timeout_minutes,
            created_at=now.isoformat(),
            ttl=expiry_ttl,
        )
        return self._store.put(approval)

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        approval = self._store.get(approval_id)
        if approval is None:
            return None
        return self._maybe_expire(approval)

    def resolve(
        self,
        approval: ApprovalRequest,
        resolver_user_id: str,
        req: ApprovalResolveRequest,
    ) -> ApprovalRequest:
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"approval {approval.approval_id} is already {approval.status.value}"
            )
        if req.decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise ValueError("decision must be approved or rejected")
        now = _now()
        resolution: dict = {}
        if req.feedback is not None:
            resolution["feedback"] = req.feedback
        if req.edited_content is not None:
            resolution["edited_content"] = req.edited_content
        if req.form_data is not None:
            resolution["form_data"] = req.form_data
        if req.selected_option is not None:
            resolution["selected_option"] = req.selected_option
        approval.status = req.decision
        approval.resolved_at = now.isoformat()
        approval.resolved_by = resolver_user_id
        approval.resolution = resolution
        return self._store.put(approval)

    def _maybe_expire(self, approval: ApprovalRequest) -> ApprovalRequest:
        """If a pending approval has passed its timeout window, mark it expired."""
        if approval.status != ApprovalStatus.PENDING:
            return approval
        try:
            created = datetime.fromisoformat(approval.created_at)
        except ValueError:
            return approval
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if _now() >= created + timedelta(minutes=approval.timeout_minutes):
            approval.status = ApprovalStatus.EXPIRED
            approval.resolved_at = _now().isoformat()
            approval.resolution = {"reason": "timeout"}
            self._store.put(approval)
        return approval

    def sweep_expired(self, user_id: str) -> int:
        """Scan this user's pending approvals and expire any past their timeout."""
        expired = 0
        for a in self._store.list_for_user(user_id, status=ApprovalStatus.PENDING):
            before = a.status
            a = self._maybe_expire(a)
            if before != a.status:
                expired += 1
        return expired
