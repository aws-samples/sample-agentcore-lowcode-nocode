"""Triggers REST API.

Endpoints:
  POST   /api/triggers                       - create
  GET    /api/triggers                       - list (scoped to caller)
  GET    /api/triggers/{trigger_id}          - read
  PUT    /api/triggers/{trigger_id}          - update (enable, name, schedule, template)
  DELETE /api/triggers/{trigger_id}          - delete + cleanup AWS resources
  POST   /api/triggers/{trigger_id}/test     - manually fire
  GET    /api/triggers/{trigger_id}/history  - recent invocations
  GET    /api/triggers/{trigger_id}/secret   - fetch webhook secret (owner only)

And the public webhook endpoint:
  POST   /api/webhooks/{webhook_path}        - HMAC-verified webhook

The webhook endpoint intentionally does NOT require the Cognito JWT.
It verifies an HMAC-SHA256 signature over the raw request body using the
per-trigger secret from Secrets Manager.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.trigger_models import (
    TriggerCreateRequest,
    TriggerFireRequest,
    TriggerHistoryResponse,
    TriggerListResponse,
    TriggerResponse,
    TriggerType,
    TriggerUpdateRequest,
)
from app.services.trigger_executor import TriggerExecutor
from app.services.trigger_manager import TriggerManager
from app.services.trigger_store import TriggerInvocationStore, TriggerStore
from app.shared.auth import require_user

logger = logging.getLogger(__name__)


_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_PATH_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


router = APIRouter(prefix="/triggers", tags=["triggers"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _get_store() -> TriggerStore:
    return TriggerStore(
        table_name=os.environ["TRIGGERS_TABLE_NAME"], region=_region()
    )


def _get_invocation_store() -> TriggerInvocationStore:
    return TriggerInvocationStore(
        table_name=os.environ["TRIGGER_INVOCATIONS_TABLE_NAME"], region=_region()
    )


def _get_manager() -> TriggerManager:
    return TriggerManager(_get_store())


def _validate_id(trigger_id: str) -> str:
    if not _ID_RE.match(trigger_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid trigger_id"
        )
    return trigger_id


def _require_owner(trigger_id: str, user_id: str):
    trigger = _get_store().get(trigger_id)
    if trigger is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trigger not found"
        )
    if trigger.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trigger not found"
        )
    return trigger


# ---------------------------------------------------------------------------
# Authenticated trigger endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TriggerResponse, status_code=status.HTTP_201_CREATED)
async def create_trigger(
    req: TriggerCreateRequest, user_id: str = Depends(require_user)
) -> TriggerResponse:
    manager = _get_manager()
    try:
        trigger = manager.create(user_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ClientError as e:
        logger.exception("AWS error creating trigger")
        raise HTTPException(
            status_code=503, detail=f"AWS error: {e.response.get('Error', {}).get('Code')}"
        )
    return TriggerResponse(trigger=trigger, message="created")


@router.get("", response_model=TriggerListResponse)
async def list_triggers(
    deployment_id: Optional[str] = None, user_id: str = Depends(require_user)
) -> TriggerListResponse:
    store = _get_store()
    triggers = store.list_for_user(user_id)
    if deployment_id:
        triggers = [t for t in triggers if t.deployment_id == deployment_id]
    return TriggerListResponse(triggers=triggers)


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: str, user_id: str = Depends(require_user)
) -> TriggerResponse:
    trigger_id = _validate_id(trigger_id)
    trigger = _require_owner(trigger_id, user_id)
    return TriggerResponse(trigger=trigger)


@router.put("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: str,
    req: TriggerUpdateRequest,
    user_id: str = Depends(require_user),
) -> TriggerResponse:
    trigger_id = _validate_id(trigger_id)
    trigger = _require_owner(trigger_id, user_id)
    manager = _get_manager()
    try:
        if req.enabled is not None and req.enabled != trigger.enabled:
            trigger = manager.set_enabled(trigger, req.enabled)
        if req.schedule_expression is not None:
            trigger = manager.update_schedule_expression(trigger, req.schedule_expression)
        if "input_template" in req.model_fields_set:
            trigger = manager.update_input_template(trigger, req.input_template)
        if req.name is not None or req.description is not None:
            if req.name is not None:
                trigger.name = req.name
            if req.description is not None:
                trigger.description = req.description
            _get_store().put(trigger)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TriggerResponse(trigger=trigger, message="updated")


@router.delete("/{trigger_id}")
async def delete_trigger(
    trigger_id: str, user_id: str = Depends(require_user)
) -> dict:
    trigger_id = _validate_id(trigger_id)
    trigger = _require_owner(trigger_id, user_id)
    _get_manager().delete(trigger)
    return {"message": "deleted", "trigger_id": trigger_id}


@router.post("/{trigger_id}/test", response_model=dict)
async def test_trigger(
    trigger_id: str,
    body: TriggerFireRequest,
    user_id: str = Depends(require_user),
) -> dict:
    trigger_id = _validate_id(trigger_id)
    trigger = _require_owner(trigger_id, user_id)
    executor = TriggerExecutor(_get_store(), _get_invocation_store())
    event_data = {"input": body.input or ""} if body.input else {}
    record = executor.execute(trigger, source="manual", event_data=event_data)
    return {
        "invocation_id": record.invocation_id,
        "status": record.status.value,
        "duration_ms": record.duration_ms,
        "error": record.error,
    }


@router.get("/{trigger_id}/history", response_model=TriggerHistoryResponse)
async def trigger_history(
    trigger_id: str, user_id: str = Depends(require_user)
) -> TriggerHistoryResponse:
    trigger_id = _validate_id(trigger_id)
    _require_owner(trigger_id, user_id)
    invocations = _get_invocation_store().list_for_trigger(trigger_id, limit=100)
    return TriggerHistoryResponse(invocations=invocations)


@router.get("/{trigger_id}/secret", response_model=dict)
async def trigger_secret(
    trigger_id: str, user_id: str = Depends(require_user)
) -> dict:
    """Return the webhook signing secret. Owner-only, webhook triggers only."""
    trigger_id = _validate_id(trigger_id)
    trigger = _require_owner(trigger_id, user_id)
    if trigger.trigger_type != TriggerType.WEBHOOK:
        raise HTTPException(status_code=400, detail="not a webhook trigger")
    secret = _get_manager().get_webhook_secret(trigger)
    if secret is None:
        raise HTTPException(status_code=404, detail="secret not found")
    return {
        "trigger_id": trigger_id,
        "webhook_path": trigger.webhook_path,
        "secret": secret,
    }


# ---------------------------------------------------------------------------
# Webhook endpoint (unauthenticated but HMAC-verified)
# ---------------------------------------------------------------------------


@webhook_router.post("/{webhook_path}")
async def fire_webhook(webhook_path: str, request: Request) -> dict:
    if not _PATH_RE.match(webhook_path):
        raise HTTPException(status_code=404, detail="not found")
    store = _get_store()
    trigger = store.find_by_webhook_path(webhook_path)
    if trigger is None or trigger.trigger_type != TriggerType.WEBHOOK:
        # constant 404 for both "no such path" and "wrong type" to avoid probing
        raise HTTPException(status_code=404, detail="not found")
    if not trigger.enabled:
        raise HTTPException(status_code=403, detail="trigger disabled")

    raw_body = await request.body()
    signature = request.headers.get("X-AgentCore-Signature", "")
    if not _verify_signature(trigger, raw_body, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        event_data = json.loads(raw_body or b"{}")
        if not isinstance(event_data, dict):
            event_data = {"body": event_data}
    except json.JSONDecodeError:
        event_data = {"body": raw_body.decode("utf-8", errors="replace")}

    executor = TriggerExecutor(store, _get_invocation_store())
    record = executor.execute(trigger, source="webhook", event_data=event_data)
    return {
        "invocation_id": record.invocation_id,
        "status": record.status.value,
    }


def _verify_signature(trigger, raw_body: bytes, signature_header: str) -> bool:
    if not signature_header:
        return False
    secret = _get_manager().get_webhook_secret(trigger)
    if not secret:
        return False
    # Accept "sha256=<hex>" or raw hex
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if signature_header.startswith("sha256="):
        signature_header = signature_header[len("sha256=") :]
    return hmac.compare_digest(expected, signature_header.lower())
