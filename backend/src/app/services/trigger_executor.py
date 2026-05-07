"""Shared execution path for triggers: invoke the runtime, record history.

Used by both the trigger-router Lambda (Scheduler/EventBridge) and the webhook
handler inside the main workflow Lambda.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3

from app.models.trigger_models import (
    TriggerConfig,
    TriggerInvocationRecord,
    TriggerInvocationStatus,
)
from app.services.trigger_store import TriggerInvocationStore, TriggerStore

logger = logging.getLogger(__name__)


INVOCATION_TTL_DAYS = 90
MAX_PAYLOAD_PREVIEW = 1024  # bytes


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class TriggerExecutor:
    """Invoke an AgentCore runtime on behalf of a trigger, record history."""

    def __init__(
        self, trigger_store: TriggerStore, invocation_store: TriggerInvocationStore
    ) -> None:
        self._store = trigger_store
        self._invocations = invocation_store
        self._agentcore = boto3.client("bedrock-agentcore", region_name=_region())
        self._sts = boto3.client("sts", region_name=_region())
        self._account: Optional[str] = None

    def _get_account_id(self) -> str:
        if self._account is None:
            self._account = self._sts.get_caller_identity()["Account"]
        return self._account

    def _resolve_runtime_arn(self, trigger: TriggerConfig) -> str:
        if trigger.runtime_id:
            return (
                f"arn:aws:bedrock-agentcore:{_region()}:{self._get_account_id()}:"
                f"runtime/{trigger.runtime_id}"
            )
        raise RuntimeError(
            f"Trigger {trigger.trigger_id} has no runtime_id; cannot invoke"
        )

    def render_input(
        self, trigger: TriggerConfig, event_data: Optional[dict[str, Any]] = None
    ) -> str:
        """Render the input template. Safe str.format with a single `event` key.

        Missing keys are replaced with empty string, not KeyError, to avoid
        blowing up on malformed templates at runtime.
        """
        template = trigger.input_template or "{event}"
        payload = {"event": json.dumps(event_data or {})}
        try:
            return template.format_map(_SafeDict(payload))
        except Exception as e:
            logger.warning("input template rendering failed: %s", e)
            return json.dumps(event_data or {})

    def execute(
        self,
        trigger: TriggerConfig,
        *,
        source: str,
        event_data: Optional[dict[str, Any]] = None,
    ) -> TriggerInvocationRecord:
        """Invoke the runtime and record an invocation row."""
        started = time.time()
        invocation_id = f"inv-{uuid.uuid4().hex[:16]}"
        invoked_at = datetime.now(timezone.utc).isoformat()
        ttl = int(
            (
                datetime.now(timezone.utc) + timedelta(days=INVOCATION_TTL_DAYS)
            ).timestamp()
        )
        try:
            runtime_arn = self._resolve_runtime_arn(trigger)
            prompt = self.render_input(trigger, event_data)
            preview = prompt[:MAX_PAYLOAD_PREVIEW]
            invoke_params: dict[str, Any] = {
                "agentRuntimeArn": runtime_arn,
                "payload": json.dumps({"prompt": prompt}),
            }
            self._agentcore.invoke_agent_runtime(**invoke_params)
            record = TriggerInvocationRecord(
                invocation_id=invocation_id,
                trigger_id=trigger.trigger_id,
                user_id=trigger.user_id,
                deployment_id=trigger.deployment_id,
                status=TriggerInvocationStatus.SUCCESS,
                source=source,
                input_payload_preview=preview,
                duration_ms=int((time.time() - started) * 1000),
                invoked_at=invoked_at,
                ttl=ttl,
            )
        except Exception as e:  # noqa: BLE001 — capture everything for history
            logger.exception("trigger %s invocation failed", trigger.trigger_id)
            record = TriggerInvocationRecord(
                invocation_id=invocation_id,
                trigger_id=trigger.trigger_id,
                user_id=trigger.user_id,
                deployment_id=trigger.deployment_id,
                status=TriggerInvocationStatus.FAILED,
                source=source,
                error=str(e)[:512],
                duration_ms=int((time.time() - started) * 1000),
                invoked_at=invoked_at,
                ttl=ttl,
            )
        finally:
            try:
                self._invocations.put(record)
            except Exception:
                logger.exception("failed to write invocation history")
            # Update trigger counters
            trigger.trigger_count += 1
            trigger.last_triggered_at = invoked_at
            trigger.updated_at = invoked_at
            if record.status == TriggerInvocationStatus.FAILED:
                trigger.last_error = record.error
            else:
                trigger.last_error = None
            try:
                self._store.put(trigger)
            except Exception:
                logger.exception("failed to update trigger counters")
        return record


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return ""
