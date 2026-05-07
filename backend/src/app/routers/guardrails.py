"""Guardrails management API (Task 06)."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.guardrail_models import (
    GuardrailConfigRequest,
    GuardrailListResponse,
    GuardrailRecordResponse,
    TestGuardrailRequest,
    TestGuardrailResponse,
)
from app.services.guardrails_manager import GuardrailsManager, GuardrailStore
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

router = APIRouter(prefix="/guardrails", tags=["guardrails"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _mgr() -> GuardrailsManager:
    return GuardrailsManager(
        GuardrailStore(
            table_name=os.environ["GUARDRAILS_TABLE_NAME"], region=_region()
        )
    )


def _validate_id(gid: str) -> str:
    if not _ID_RE.match(gid):
        raise HTTPException(status_code=400, detail="Invalid guardrail_id")
    return gid


@router.post("", response_model=GuardrailRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    req: GuardrailConfigRequest, user_id: str = Depends(require_user)
) -> GuardrailRecordResponse:
    try:
        rec = _mgr().create(user_id, req)
    except Exception as e:
        logger.exception("create guardrail failed")
        raise HTTPException(status_code=400, detail=str(e))
    return GuardrailRecordResponse(guardrail=rec)


@router.get("", response_model=GuardrailListResponse)
async def list_guardrails(user_id: str = Depends(require_user)) -> GuardrailListResponse:
    return GuardrailListResponse(guardrails=_mgr()._store.list_for_user(user_id))


@router.get("/{guardrail_id}", response_model=GuardrailRecordResponse)
async def get_guardrail(
    guardrail_id: str, user_id: str = Depends(require_user)
) -> GuardrailRecordResponse:
    guardrail_id = _validate_id(guardrail_id)
    rec = _mgr()._store.get(guardrail_id)
    if rec is None or rec.user_id != user_id:
        raise HTTPException(status_code=404, detail="guardrail not found")
    return GuardrailRecordResponse(guardrail=rec)


@router.put("/{guardrail_id}", response_model=GuardrailRecordResponse)
async def update_guardrail(
    guardrail_id: str,
    req: GuardrailConfigRequest,
    user_id: str = Depends(require_user),
) -> GuardrailRecordResponse:
    guardrail_id = _validate_id(guardrail_id)
    try:
        rec = _mgr().update(user_id, guardrail_id, req)
    except PermissionError:
        raise HTTPException(status_code=404, detail="guardrail not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return GuardrailRecordResponse(guardrail=rec)


@router.delete("/{guardrail_id}")
async def delete_guardrail(
    guardrail_id: str, user_id: str = Depends(require_user)
) -> dict:
    guardrail_id = _validate_id(guardrail_id)
    try:
        deleted = _mgr().delete(user_id, guardrail_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="guardrail not found")
    if not deleted:
        raise HTTPException(status_code=404, detail="guardrail not found")
    return {"message": "deleted"}


@router.post("/test", response_model=TestGuardrailResponse)
async def test_guardrail(
    req: TestGuardrailRequest, user_id: str = Depends(require_user)
) -> TestGuardrailResponse:
    _validate_id(req.guardrail_id)
    try:
        resp = _mgr().test(user_id, req.guardrail_id, req.text, req.source)
    except PermissionError:
        raise HTTPException(status_code=404, detail="guardrail not found")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    action = resp.get("action", "NONE")
    outputs = []
    for out in resp.get("outputs", []) or []:
        if isinstance(out, dict) and "text" in out:
            outputs.append(out["text"])
    return TestGuardrailResponse(
        action=action,
        blocked=action == "GUARDRAIL_INTERVENED",
        outputs=outputs,
        details={
            "assessments": resp.get("assessments", []),
            "usage": resp.get("usage", {}),
        },
    )
