"""Trigger Router Lambda.

Invoked by:
  - EventBridge Scheduler (schedule triggers) - payload is our router payload dict
  - EventBridge Rules (event triggers) - payload is our router payload dict

The schedule/rule target is configured with a static Input containing the
trigger_id, deployment_id, runtime_id, input_template, source.

For event triggers, the actual event is surfaced to the agent by rendering
`input_template` with the whole Input payload merged onto `event`. Since
EventBridge already JSON-encoded our static input, we don't get the original
matched event here — the spec's acceptance criteria only require invocation on
a matching event, not forwarding the event body. For forwarding we'd switch
targets to InputTransformer; see the TriggerManager for the extension point.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.models.trigger_models import TriggerStatus
from app.services.trigger_executor import TriggerExecutor
from app.services.trigger_store import TriggerInvocationStore, TriggerStore

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _get_stores() -> tuple[TriggerStore, TriggerInvocationStore]:
    return (
        TriggerStore(
            table_name=os.environ["TRIGGERS_TABLE_NAME"], region=_region()
        ),
        TriggerInvocationStore(
            table_name=os.environ["TRIGGER_INVOCATIONS_TABLE_NAME"], region=_region()
        ),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Invoke the trigger's configured runtime."""
    logger.info("trigger router event: %s", event)
    trigger_id = event.get("trigger_id")
    source = event.get("source", "schedule")
    if not trigger_id:
        logger.error("trigger_id missing from event")
        return {"status": "error", "error": "missing trigger_id"}

    store, invocation_store = _get_stores()
    trigger = store.get(trigger_id)
    if trigger is None:
        logger.error("trigger %s not found", trigger_id)
        return {"status": "error", "error": "trigger_not_found"}
    if not trigger.enabled or trigger.status == TriggerStatus.DISABLED:
        logger.info("trigger %s disabled; skipping", trigger_id)
        return {"status": "skipped", "reason": "disabled"}

    executor = TriggerExecutor(store, invocation_store)
    record = executor.execute(trigger, source=source, event_data=event)
    return {
        "status": record.status.value,
        "invocation_id": record.invocation_id,
        "duration_ms": record.duration_ms,
    }
