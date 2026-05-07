"""Unit tests for the A2A JSON-RPC dispatcher (Task 05)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.a2a_models import A2ATask, A2ATaskState
from app.services.a2a_service import dispatch_jsonrpc


def _svc_with_task(task: A2ATask) -> MagicMock:
    svc = MagicMock()
    svc.get_task.return_value = task
    svc.create_and_execute_task.return_value = task
    svc.cancel_task.return_value = task.model_copy(
        update={"state": A2ATaskState.CANCELED}
    )
    return svc


def test_rejects_non_jsonrpc() -> None:
    svc = MagicMock()
    resp = dispatch_jsonrpc(svc, "d1", {"method": "tasks/send", "params": {}})
    assert resp["error"]["code"] == -32600


def test_method_not_found() -> None:
    svc = MagicMock()
    resp = dispatch_jsonrpc(svc, "d1", {"jsonrpc": "2.0", "id": 1, "method": "unknown"})
    assert resp["error"]["code"] == -32601


def test_tasks_send_requires_message() -> None:
    svc = MagicMock()
    resp = dispatch_jsonrpc(
        svc, "d1", {"jsonrpc": "2.0", "id": 1, "method": "tasks/send", "params": {}}
    )
    assert resp["error"]["code"] == -32602


def test_tasks_send_happy_path() -> None:
    task = A2ATask(task_id="t1", deployment_id="d1", state=A2ATaskState.COMPLETED)
    svc = _svc_with_task(task)
    resp = dispatch_jsonrpc(
        svc,
        "d1",
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tasks/send",
            "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]}},
        },
    )
    assert resp["id"] == 7
    assert resp["result"]["state"] == "completed"
    svc.create_and_execute_task.assert_called_once()


def test_tasks_send_runtime_error_as_jsonrpc_error() -> None:
    svc = MagicMock()
    svc.create_and_execute_task.side_effect = ValueError("agent not available")
    resp = dispatch_jsonrpc(
        svc,
        "d1",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {"message": {"role": "user", "parts": []}},
        },
    )
    assert resp["error"]["code"] == -32000
    assert "agent not available" in resp["error"]["message"]


def test_tasks_get_returns_task() -> None:
    task = A2ATask(task_id="t1", deployment_id="d1", state=A2ATaskState.WORKING)
    svc = _svc_with_task(task)
    resp = dispatch_jsonrpc(
        svc,
        "d1",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/get",
            "params": {"task_id": "t1"},
        },
    )
    assert resp["result"]["task_id"] == "t1"


def test_tasks_get_isolation_across_deployments() -> None:
    task = A2ATask(task_id="t1", deployment_id="other", state=A2ATaskState.WORKING)
    svc = _svc_with_task(task)
    resp = dispatch_jsonrpc(
        svc,
        "d1",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tasks/get",
            "params": {"task_id": "t1"},
        },
    )
    assert resp["error"]["code"] == -32001


def test_tasks_cancel() -> None:
    task = A2ATask(task_id="t1", deployment_id="d1", state=A2ATaskState.WORKING)
    svc = _svc_with_task(task)
    resp = dispatch_jsonrpc(
        svc,
        "d1",
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tasks/cancel",
            "params": {"task_id": "t1"},
        },
    )
    assert resp["result"]["state"] == "canceled"
