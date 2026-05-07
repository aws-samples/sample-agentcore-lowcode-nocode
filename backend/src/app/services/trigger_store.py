"""DynamoDB-backed storage for triggers and their execution history.

Two tables:
  - AgentTriggers: PK=trigger_id, GSI user_id-index, GSI deployment_id-index
  - AgentTriggerInvocations: PK=trigger_id, SK=invoked_at (sort by time)

Both serialize Pydantic models via model_dump(mode="json") with float→Decimal conversion.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.models.trigger_models import TriggerConfig, TriggerInvocationRecord
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


def _serialize_trigger(t: TriggerConfig) -> dict:
    item = t.model_dump(mode="json")
    return _convert_floats_to_decimals(item)


def _deserialize_trigger(item: dict) -> TriggerConfig:
    data = _convert_decimals_to_floats(dict(item))
    return TriggerConfig.model_validate(data)


def _serialize_invocation(inv: TriggerInvocationRecord) -> dict:
    item = inv.model_dump(mode="json")
    return _convert_floats_to_decimals(item)


def _deserialize_invocation(item: dict) -> TriggerInvocationRecord:
    data = _convert_decimals_to_floats(dict(item))
    return TriggerInvocationRecord.model_validate(data)


class TriggerStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table_name = table_name
        self._region = region
        self._dynamodb = _get_dynamodb_resource(region)
        self._table = _get_table(self._dynamodb, table_name)

    def put(self, trigger: TriggerConfig) -> TriggerConfig:
        _put_item(self._table, _serialize_trigger(trigger))
        return trigger

    def get(self, trigger_id: str) -> Optional[TriggerConfig]:
        item = _get_item(self._table, {"trigger_id": trigger_id})
        return _deserialize_trigger(item) if item else None

    def delete(self, trigger_id: str) -> bool:
        if not self.get(trigger_id):
            return False
        _delete_item(self._table, {"trigger_id": trigger_id})
        return True

    def list_for_user(self, user_id: str) -> list[TriggerConfig]:
        """Query via user_id-index GSI."""
        try:
            resp = self._table.query(
                IndexName="user_id-index",
                KeyConditionExpression="user_id = :uid",
                ExpressionAttributeValues={":uid": user_id},
            )
            items = resp.get("Items", [])
            return [_deserialize_trigger(i) for i in items]
        except Exception as e:
            logger.warning("user_id-index query failed, falling back to scan: %s", e)
            all_items = _scan_table(self._table)
            return [
                _deserialize_trigger(i)
                for i in all_items
                if i.get("user_id") == user_id
            ]

    def list_for_deployment(self, deployment_id: str) -> list[TriggerConfig]:
        try:
            resp = self._table.query(
                IndexName="deployment_id-index",
                KeyConditionExpression="deployment_id = :d",
                ExpressionAttributeValues={":d": deployment_id},
            )
            items = resp.get("Items", [])
            return [_deserialize_trigger(i) for i in items]
        except Exception as e:
            logger.warning("deployment_id-index query failed, falling back to scan: %s", e)
            all_items = _scan_table(self._table)
            return [
                _deserialize_trigger(i)
                for i in all_items
                if i.get("deployment_id") == deployment_id
            ]

    def find_by_webhook_path(self, webhook_path: str) -> Optional[TriggerConfig]:
        """Used by the webhook handler to look up the target deployment."""
        items = _scan_table(self._table)
        for i in items:
            if i.get("webhook_path") == webhook_path:
                return _deserialize_trigger(i)
        return None


class TriggerInvocationStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table_name = table_name
        self._region = region
        self._dynamodb = _get_dynamodb_resource(region)
        self._table = _get_table(self._dynamodb, table_name)

    def put(self, inv: TriggerInvocationRecord) -> TriggerInvocationRecord:
        _put_item(self._table, _serialize_invocation(inv))
        return inv

    def list_for_trigger(self, trigger_id: str, limit: int = 100) -> list[TriggerInvocationRecord]:
        try:
            resp = self._table.query(
                KeyConditionExpression="trigger_id = :t",
                ExpressionAttributeValues={":t": trigger_id},
                ScanIndexForward=False,  # newest first
                Limit=limit,
            )
            items = resp.get("Items", [])
            return [_deserialize_invocation(i) for i in items]
        except Exception as e:
            logger.warning("invocation query failed: %s", e)
            return []
