"""DynamoDB store for approval requests (Task 02)."""

from __future__ import annotations

import logging
from typing import Optional

from app.models.approval_models import ApprovalRequest, ApprovalStatus
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


def _serialize(a: ApprovalRequest) -> dict:
    return _convert_floats_to_decimals(a.model_dump(mode="json"))


def _deserialize(item: dict) -> ApprovalRequest:
    return ApprovalRequest.model_validate(_convert_decimals_to_floats(dict(item)))


class ApprovalStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table_name = table_name
        self._region = region
        self._dynamodb = _get_dynamodb_resource(region)
        self._table = _get_table(self._dynamodb, table_name)

    def put(self, approval: ApprovalRequest) -> ApprovalRequest:
        _put_item(self._table, _serialize(approval))
        return approval

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        item = _get_item(self._table, {"approval_id": approval_id})
        return _deserialize(item) if item else None

    def delete(self, approval_id: str) -> bool:
        if not self.get(approval_id):
            return False
        _delete_item(self._table, {"approval_id": approval_id})
        return True

    def list_for_user(
        self, user_id: str, status: Optional[ApprovalStatus] = None
    ) -> list[ApprovalRequest]:
        try:
            resp = self._table.query(
                IndexName="user_id-index",
                KeyConditionExpression="user_id = :uid",
                ExpressionAttributeValues={":uid": user_id},
            )
            items = resp.get("Items", [])
            results = [_deserialize(i) for i in items]
        except Exception as e:
            logger.warning("user_id-index query failed, falling back: %s", e)
            results = [
                _deserialize(i)
                for i in _scan_table(self._table)
                if i.get("user_id") == user_id
            ]
        if status is not None:
            results = [a for a in results if a.status == status]
        return sorted(results, key=lambda a: a.created_at, reverse=True)

    def list_for_deployment(
        self, deployment_id: str, status: Optional[ApprovalStatus] = None
    ) -> list[ApprovalRequest]:
        try:
            resp = self._table.query(
                IndexName="deployment_id-index",
                KeyConditionExpression="deployment_id = :d",
                ExpressionAttributeValues={":d": deployment_id},
            )
            items = resp.get("Items", [])
            results = [_deserialize(i) for i in items]
        except Exception as e:
            logger.warning("deployment_id-index query failed: %s", e)
            results = [
                _deserialize(i)
                for i in _scan_table(self._table)
                if i.get("deployment_id") == deployment_id
            ]
        if status is not None:
            results = [a for a in results if a.status == status]
        return sorted(results, key=lambda a: a.created_at, reverse=True)

    def stats_for_user(self, user_id: str) -> dict[str, int]:
        counts = {
            ApprovalStatus.PENDING.value: 0,
            ApprovalStatus.APPROVED.value: 0,
            ApprovalStatus.REJECTED.value: 0,
            ApprovalStatus.EXPIRED.value: 0,
        }
        for a in self.list_for_user(user_id):
            counts[a.status.value] = counts.get(a.status.value, 0) + 1
        return counts
