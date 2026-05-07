"""A2A router (Task 05).

Routes:
  GET  /.well-known/agents/{deployment_id}   - agent card (public)
  POST /a2a/{deployment_id}                  - JSON-RPC endpoint (public, subject
                                                to rate-limiting via API GW)
  GET  /api/a2a/config                       - list caller's A2A configs (auth)
  GET  /api/a2a/config/{deployment_id}       - read one (auth)
  PUT  /api/a2a/config                       - upsert config (auth)
  DELETE /api/a2a/config/{deployment_id}     - delete config (auth)

Design note: the well-known/json-rpc routes intentionally do NOT require a
Cognito JWT — they are the public interface for cross-vendor A2A. Auth is
delegated to the Agent Card's declared schemes; for this MVP we accept
anonymous tasks/send. A future iteration can wire Bearer tokens through
the A2A spec's authentication flow.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.models.a2a_models import (
    A2AConfigRecord,
    A2AConfigRequest,
    AgentCard,
)
from app.services.a2a_service import (
    A2AConfigStore,
    A2AService,
    A2ATaskStore,
    dispatch_jsonrpc,
)
from app.shared.auth import require_user

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

config_router = APIRouter(prefix="/a2a/config", tags=["a2a-config"])
well_known_router = APIRouter(prefix="/.well-known", tags=["a2a-well-known"])
jsonrpc_router = APIRouter(prefix="/a2a", tags=["a2a-jsonrpc"])


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _svc() -> A2AService:
    return A2AService(
        config_store=A2AConfigStore(
            table_name=os.environ["A2A_CONFIGS_TABLE_NAME"], region=_region()
        ),
        task_store=A2ATaskStore(
            table_name=os.environ["A2A_TASKS_TABLE_NAME"], region=_region()
        ),
    )


def _validate_id(deployment_id: str) -> str:
    if not _ID_RE.match(deployment_id):
        raise HTTPException(status_code=400, detail="Invalid deployment_id")
    return deployment_id


# ---------------------------------------------------------------------------
# Config CRUD (authenticated)
# ---------------------------------------------------------------------------


class ConfigResponse(BaseModel):
    config: A2AConfigRecord


class ConfigListResponse(BaseModel):
    configs: list[A2AConfigRecord]


@config_router.get("", response_model=ConfigListResponse)
async def list_configs(user_id: str = Depends(require_user)) -> ConfigListResponse:
    return ConfigListResponse(configs=_svc()._config_store.list_for_user(user_id))


@config_router.put("", response_model=ConfigResponse)
async def upsert_config(
    req: A2AConfigRequest, user_id: str = Depends(require_user)
) -> ConfigResponse:
    try:
        cfg = _svc().upsert_config(user_id, req)
    except PermissionError:
        raise HTTPException(status_code=404, detail="deployment not found")
    return ConfigResponse(config=cfg)


@config_router.get("/{deployment_id}", response_model=ConfigResponse)
async def get_config(
    deployment_id: str, user_id: str = Depends(require_user)
) -> ConfigResponse:
    deployment_id = _validate_id(deployment_id)
    cfg = _svc().get_config(deployment_id)
    if cfg is None or cfg.user_id != user_id:
        raise HTTPException(status_code=404, detail="config not found")
    return ConfigResponse(config=cfg)


@config_router.delete("/{deployment_id}")
async def delete_config(
    deployment_id: str, user_id: str = Depends(require_user)
) -> dict:
    deployment_id = _validate_id(deployment_id)
    try:
        deleted = _svc().delete_config(deployment_id, user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="config not found")
    if not deleted:
        raise HTTPException(status_code=404, detail="config not found")
    return {"message": "deleted"}


# ---------------------------------------------------------------------------
# Well-known Agent Card (public)
# ---------------------------------------------------------------------------


@well_known_router.get("/agents/{deployment_id}", response_model=AgentCard)
async def get_agent_card(deployment_id: str, request: Request) -> AgentCard:
    deployment_id = _validate_id(deployment_id)
    cfg = _svc().get_config(deployment_id)
    if cfg is None or not cfg.enabled:
        raise HTTPException(status_code=404, detail="agent not found")
    # Agent's A2A endpoint is /a2a/{deployment_id} on the same host
    base = str(request.base_url).rstrip("/")
    card_url = f"{base}/a2a/{deployment_id}"
    return _svc().build_agent_card(cfg, card_url)


# ---------------------------------------------------------------------------
# JSON-RPC endpoint (public)
# ---------------------------------------------------------------------------


@jsonrpc_router.post("/{deployment_id}")
async def jsonrpc(deployment_id: str, request: Request) -> dict[str, Any]:
    deployment_id = _validate_id(deployment_id)
    try:
        body = await request.json()
    except Exception:
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "parse error"},
        }
    if not isinstance(body, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "invalid request"},
        }
    # Verify the agent exists + is enabled before dispatching.
    cfg = _svc().get_config(deployment_id)
    if cfg is None or not cfg.enabled:
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32000, "message": "agent not available"},
        }
    return dispatch_jsonrpc(_svc(), deployment_id, body)
