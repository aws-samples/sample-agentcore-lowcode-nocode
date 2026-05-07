"""A2A service: config store, task store, JSON-RPC dispatch (Task 05).

Implements tasks/send (delegate to AgentCore runtime) and tasks/get
(polling) against the A2A spec v0.2.
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
from botocore.exceptions import ClientError

from app.models.a2a_models import (
    A2AConfigRecord,
    A2AConfigRequest,
    A2ATask,
    A2ATaskState,
    AgentCard,
)
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

TASK_TTL_DAYS = 30


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class A2AConfigStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, cfg: A2AConfigRecord) -> A2AConfigRecord:
        _put_item(self._table, _convert_floats_to_decimals(cfg.model_dump(mode="json")))
        return cfg

    def get(self, deployment_id: str) -> Optional[A2AConfigRecord]:
        item = _get_item(self._table, {"deployment_id": deployment_id})
        if not item:
            return None
        return A2AConfigRecord.model_validate(_convert_decimals_to_floats(dict(item)))

    def delete(self, deployment_id: str) -> bool:
        if not self.get(deployment_id):
            return False
        _delete_item(self._table, {"deployment_id": deployment_id})
        return True

    def list_for_user(self, user_id: str) -> list[A2AConfigRecord]:
        items = _scan_table(self._table)
        return [
            A2AConfigRecord.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in items
            if i.get("user_id") == user_id
        ]


class A2ATaskStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, t: A2ATask) -> A2ATask:
        _put_item(self._table, _convert_floats_to_decimals(t.model_dump(mode="json")))
        return t

    def get(self, task_id: str) -> Optional[A2ATask]:
        item = _get_item(self._table, {"task_id": task_id})
        if not item:
            return None
        return A2ATask.model_validate(_convert_decimals_to_floats(dict(item)))

    def update_state(
        self,
        task: A2ATask,
        new_state: A2ATaskState,
        messages: Optional[list[dict[str, Any]]] = None,
        artifacts: Optional[list[dict[str, Any]]] = None,
    ) -> A2ATask:
        task.state = new_state
        task.updated_at = datetime.now(timezone.utc).isoformat()
        if messages is not None:
            task.messages = messages
        if artifacts is not None:
            task.artifacts = artifacts
        return self.put(task)


class A2AService:
    def __init__(
        self, config_store: A2AConfigStore, task_store: A2ATaskStore
    ) -> None:
        self._config_store = config_store
        self._task_store = task_store
        self._agentcore = boto3.client("bedrock-agentcore", region_name=_region())
        self._sts = boto3.client("sts", region_name=_region())
        self._account: Optional[str] = None

    def _account_id(self) -> str:
        if self._account is None:
            self._account = self._sts.get_caller_identity()["Account"]
        return self._account

    def upsert_config(
        self, user_id: str, req: A2AConfigRequest
    ) -> A2AConfigRecord:
        now = datetime.now(timezone.utc).isoformat()
        existing = self._config_store.get(req.deployment_id)
        if existing and existing.user_id != user_id:
            raise PermissionError("not your deployment")
        rec = A2AConfigRecord(
            deployment_id=req.deployment_id,
            user_id=user_id,
            enabled=req.enabled,
            name=req.name,
            description=req.description,
            skills=req.skills,
            runtime_id=req.runtime_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        return self._config_store.put(rec)

    def get_config(self, deployment_id: str) -> Optional[A2AConfigRecord]:
        return self._config_store.get(deployment_id)

    def delete_config(self, deployment_id: str, user_id: str) -> bool:
        existing = self._config_store.get(deployment_id)
        if existing is None:
            return False
        if existing.user_id != user_id:
            raise PermissionError("not your deployment")
        return self._config_store.delete(deployment_id)

    def build_agent_card(self, cfg: A2AConfigRecord, base_url: str) -> AgentCard:
        return AgentCard(
            name=cfg.name,
            description=cfg.description,
            url=base_url.rstrip("/"),
            skills=cfg.skills,
        )

    # ------------------------------------------------------------------
    # JSON-RPC tasks/send
    # ------------------------------------------------------------------

    def create_and_execute_task(
        self, deployment_id: str, message: dict[str, Any]
    ) -> A2ATask:
        cfg = self._config_store.get(deployment_id)
        if cfg is None or not cfg.enabled:
            raise ValueError("agent not available")
        if not cfg.runtime_id:
            raise ValueError("agent has no bound runtime")
        task_id = f"task-{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        ttl = int((now + timedelta(days=TASK_TTL_DAYS)).timestamp())
        task = A2ATask(
            task_id=task_id,
            deployment_id=deployment_id,
            state=A2ATaskState.WORKING,
            messages=[message],
            ttl=ttl,
        )
        self._task_store.put(task)

        # Invoke the runtime
        prompt = self._extract_text(message)
        runtime_arn = (
            f"arn:aws:bedrock-agentcore:{_region()}:{self._account_id()}:"
            f"runtime/{cfg.runtime_id}"
        )
        agent_reply: Optional[str] = None
        error: Optional[str] = None
        try:
            resp = self._agentcore.invoke_agent_runtime(
                agentRuntimeArn=runtime_arn,
                payload=json.dumps({"prompt": prompt}),
            )
            raw = resp.get("response", "") or resp.get("body", b"")
            if hasattr(raw, "read"):
                raw = raw.read()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            agent_reply = _parse_response_text(raw)
        except ClientError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001
            error = str(e)

        if agent_reply is not None and error is None:
            return self._task_store.update_state(
                task,
                A2ATaskState.COMPLETED,
                messages=[
                    *task.messages,
                    {
                        "role": "agent",
                        "parts": [{"type": "text", "text": agent_reply}],
                    },
                ],
            )
        return self._task_store.update_state(
            task,
            A2ATaskState.FAILED,
            messages=[
                *task.messages,
                {
                    "role": "agent",
                    "parts": [{"type": "text", "text": f"error: {error}"}],
                },
            ],
        )

    def get_task(self, task_id: str) -> Optional[A2ATask]:
        return self._task_store.get(task_id)

    def cancel_task(self, task_id: str) -> Optional[A2ATask]:
        task = self._task_store.get(task_id)
        if task is None:
            return None
        if task.state in (A2ATaskState.COMPLETED, A2ATaskState.FAILED):
            return task
        return self._task_store.update_state(task, A2ATaskState.CANCELED)

    @staticmethod
    def _extract_text(message: dict[str, Any]) -> str:
        parts = message.get("parts") or []
        texts = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                texts.append(str(p.get("text", "")))
        return "\n".join(texts).strip() or json.dumps(message, default=str)


def _parse_response_text(raw: str) -> str:
    """Best-effort extraction of assistant text from various payload shapes."""
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for key in ("response", "message", "content", "text"):
            v = obj.get(key)
            if isinstance(v, str):
                return v
        return json.dumps(obj)[:8192]
    return str(obj)[:8192]


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 dispatch
# ---------------------------------------------------------------------------


def dispatch_jsonrpc(
    svc: A2AService, deployment_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Parse a JSON-RPC 2.0 request and dispatch to the appropriate service method."""
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    def _error(code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        }

    def _result(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    if body.get("jsonrpc") != "2.0":
        return _error(-32600, "expected jsonrpc:2.0")
    if not isinstance(method, str):
        return _error(-32600, "missing method")

    if method == "tasks/send":
        message = params.get("message")
        if not isinstance(message, dict):
            return _error(-32602, "message required")
        try:
            task = svc.create_and_execute_task(deployment_id, message)
        except ValueError as e:
            return _error(-32000, str(e))
        return _result(task.model_dump(mode="json"))

    if method == "tasks/get":
        task_id = params.get("task_id") or params.get("id")
        if not isinstance(task_id, str):
            return _error(-32602, "task_id required")
        task = svc.get_task(task_id)
        if task is None or task.deployment_id != deployment_id:
            return _error(-32001, "task not found")
        return _result(task.model_dump(mode="json"))

    if method == "tasks/cancel":
        task_id = params.get("task_id") or params.get("id")
        if not isinstance(task_id, str):
            return _error(-32602, "task_id required")
        task = svc.get_task(task_id)
        if task is None or task.deployment_id != deployment_id:
            return _error(-32001, "task not found")
        canceled = svc.cancel_task(task_id)
        return _result(canceled.model_dump(mode="json") if canceled else None)

    return _error(-32601, f"method not found: {method}")
