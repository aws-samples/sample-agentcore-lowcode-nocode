"""DynamoDB store for agent versions (Task 03).

Table key schema:
  PK: deployment_id
  SK: version (Number)

Each item is an immutable snapshot. Sort-key range queries yield the history.
"""

from __future__ import annotations

import logging
from typing import Optional

from boto3.dynamodb.conditions import Key

from app.models.version_models import AgentVersion
from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _get_dynamodb_resource,
    _get_table,
    _put_item,
    _scan_table,
)

logger = logging.getLogger(__name__)


def _serialize(v: AgentVersion) -> dict:
    return _convert_floats_to_decimals(v.model_dump(mode="json"))


def _deserialize(item: dict) -> AgentVersion:
    return AgentVersion.model_validate(_convert_decimals_to_floats(dict(item)))


class VersionStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, v: AgentVersion) -> AgentVersion:
        _put_item(self._table, _serialize(v))
        return v

    def get(self, deployment_id: str, version: int) -> Optional[AgentVersion]:
        resp = self._table.get_item(
            Key={"deployment_id": deployment_id, "version": version}
        )
        item = resp.get("Item")
        return _deserialize(item) if item else None

    def list_for_deployment(self, deployment_id: str) -> list[AgentVersion]:
        resp = self._table.query(
            KeyConditionExpression=Key("deployment_id").eq(deployment_id),
            ScanIndexForward=False,  # newest version first
        )
        return [_deserialize(i) for i in resp.get("Items", [])]

    def latest_version_number(self, deployment_id: str) -> int:
        versions = self.list_for_deployment(deployment_id)
        return max((v.version for v in versions), default=0)

    def update_status(
        self, deployment_id: str, version: int, new_status: str
    ) -> None:
        self._table.update_item(
            Key={"deployment_id": deployment_id, "version": version},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": new_status},
        )

    def list_for_user(self, user_id: str) -> list[AgentVersion]:
        """Best-effort scan by user_id; deployments are usually queried directly."""
        items = _scan_table(self._table)
        return [_deserialize(i) for i in items if i.get("user_id") == user_id]
