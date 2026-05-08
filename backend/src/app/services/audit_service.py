"""Audit logging service (Task 10).

Write model: fire-and-forget append-only. Reads are admin-only (IAM + app-level).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.audit_models import AuditEvent
from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _get_dynamodb_resource,
    _get_table,
    _put_item,
    _scan_table,
)

logger = logging.getLogger(__name__)


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class AuditStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, event: AuditEvent) -> AuditEvent:
        _put_item(self._table, _convert_floats_to_decimals(event.model_dump(mode="json")))
        return event

    def query_recent(
        self, date_partition: str, limit: int = 100
    ) -> list[AuditEvent]:
        try:
            resp = self._table.query(
                KeyConditionExpression="date_partition = :d",
                ExpressionAttributeValues={":d": date_partition},
                ScanIndexForward=False,
                Limit=limit,
            )
            return [
                AuditEvent.model_validate(_convert_decimals_to_floats(dict(i)))
                for i in resp.get("Items", [])
            ]
        except Exception as e:
            logger.warning("query audit by date failed, scanning: %s", e)
            items = _scan_table(self._table)
            events = [
                AuditEvent.model_validate(_convert_decimals_to_floats(dict(i)))
                for i in items
                if i.get("date_partition") == date_partition
            ]
            return sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]

    def scan_recent(self, limit: int = 200) -> list[AuditEvent]:
        items = _scan_table(self._table)
        events = [
            AuditEvent.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in items
        ]
        return sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]


class AuditService:
    def __init__(self, store: AuditStore) -> None:
        self._store = store

    def log(
        self,
        *,
        user_id: str,
        user_email: Optional[str],
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        result: str = "allowed",
        error: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        now = datetime.now(timezone.utc)
        event = AuditEvent(
            event_id=f"ae-{uuid.uuid4().hex[:16]}",
            date_partition=now.strftime("%Y-%m-%d"),
            timestamp=now.isoformat(),
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            error=error,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {},
        )
        try:
            self._store.put(event)
        except Exception:
            logger.exception("audit write failed")
        return event

    def recent(self, date_partition: Optional[str] = None, limit: int = 200) -> list[AuditEvent]:
        if date_partition:
            return self._store.query_recent(date_partition, limit=limit)
        return self._store.scan_recent(limit=limit)


def singleton_audit_service() -> AuditService:
    table_name = os.environ.get("AUDIT_TABLE_NAME")
    if not table_name:
        raise RuntimeError("AUDIT_TABLE_NAME env var required")
    return AuditService(AuditStore(table_name=table_name, region=_region()))
