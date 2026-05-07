"""SDK unit tests — mock httpx to avoid real network calls."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agentcore_sdk import AgentCoreClient, AgentCoreError


def _mock_client(response_status: int = 200, response_json=None):
    resp = MagicMock()
    resp.status_code = response_status
    resp.json.return_value = response_json or {}
    resp.text = "text"
    resp.content = b"{}"
    return resp


def test_init_requires_url_and_token() -> None:
    with pytest.raises(ValueError):
        AgentCoreClient(api_url="", token="t")
    with pytest.raises(ValueError):
        AgentCoreClient(api_url="http://x", token="")


def test_list_triggers_filters_by_deployment() -> None:
    c = AgentCoreClient("http://x", "t")
    c.raw.request = MagicMock(
        return_value=_mock_client(200, {"triggers": [{"trigger_id": "trg-1"}]})
    )
    result = c.list_triggers(deployment_id="d1")
    assert result == [{"trigger_id": "trg-1"}]
    c.raw.request.assert_called_once_with(
        "GET", "/api/triggers", params={"deployment_id": "d1"}
    )


def test_create_schedule_trigger_body_shape() -> None:
    c = AgentCoreClient("http://x", "t")
    c.raw.request = MagicMock(
        return_value=_mock_client(201, {"trigger": {"trigger_id": "trg-1"}})
    )
    result = c.create_schedule_trigger(
        deployment_id="d1",
        runtime_id="r1",
        name="nightly",
        schedule_expression="cron(0 9 * * ? *)",
    )
    assert result == {"trigger_id": "trg-1"}
    args, kwargs = c.raw.request.call_args
    assert args == ("POST", "/api/triggers")
    assert kwargs["json"]["trigger_type"] == "schedule"
    assert kwargs["json"]["schedule_expression"] == "cron(0 9 * * ? *)"


def test_error_raises_with_detail() -> None:
    c = AgentCoreClient("http://x", "t")
    c.raw.request = MagicMock(
        return_value=_mock_client(400, {"detail": "bad thing"})
    )
    with pytest.raises(AgentCoreError) as exc:
        c.list_triggers()
    assert exc.value.status_code == 400
    assert "bad thing" in str(exc.value)


def test_rollback_body() -> None:
    c = AgentCoreClient("http://x", "t")
    c.raw.request = MagicMock(
        return_value=_mock_client(200, {"new_version": 2, "restored_from_version": 1})
    )
    result = c.rollback("d1", target_version=1, reason="regression")
    assert result["new_version"] == 2
    _, kwargs = c.raw.request.call_args
    assert kwargs["json"] == {"target_version": 1, "reason": "regression"}


def test_promote_preserves_optional_source_version() -> None:
    c = AgentCoreClient("http://x", "t")
    c.raw.request = MagicMock(
        return_value=_mock_client(201, {"promotion": {"promotion_id": "p1"}})
    )
    c.promote(
        "d1",
        source_env="dev",
        target_env="staging",
        change_description="ok",
        source_version=3,
    )
    _, kwargs = c.raw.request.call_args
    assert kwargs["json"]["source_version"] == 3
