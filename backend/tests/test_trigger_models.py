"""Unit tests for trigger models (Task 01)."""

from __future__ import annotations

import pytest

from app.models.trigger_models import (
    TriggerCreateRequest,
    TriggerStatus,
    TriggerType,
    TriggerUpdateRequest,
)


def test_create_schedule_valid_cron() -> None:
    req = TriggerCreateRequest(
        deployment_id="d1",
        trigger_type=TriggerType.SCHEDULE,
        name="daily-report",
        schedule_expression="cron(0 9 * * ? *)",
    )
    assert req.trigger_type == TriggerType.SCHEDULE
    assert req.schedule_expression == "cron(0 9 * * ? *)"


def test_create_schedule_valid_rate() -> None:
    req = TriggerCreateRequest(
        deployment_id="d1",
        trigger_type=TriggerType.SCHEDULE,
        name="hourly",
        schedule_expression="rate(1 hour)",
    )
    assert req.schedule_expression == "rate(1 hour)"


def test_create_rejects_bad_expression() -> None:
    with pytest.raises(ValueError):
        TriggerCreateRequest(
            deployment_id="d1",
            trigger_type=TriggerType.SCHEDULE,
            name="bad",
            schedule_expression="every minute",
        )


def test_create_webhook() -> None:
    req = TriggerCreateRequest(
        deployment_id="d1",
        trigger_type=TriggerType.WEBHOOK,
        name="hook",
        webhook_path="incoming",
    )
    assert req.webhook_path == "incoming"


def test_update_enabled_only() -> None:
    u = TriggerUpdateRequest(enabled=False)
    assert u.enabled is False
    assert u.name is None


def test_create_event_with_pattern() -> None:
    req = TriggerCreateRequest(
        deployment_id="d1",
        trigger_type=TriggerType.EVENT,
        name="s3-upload",
        event_pattern={"source": ["aws.s3"]},
    )
    assert req.event_pattern == {"source": ["aws.s3"]}


def test_name_length_bounded() -> None:
    with pytest.raises(ValueError):
        TriggerCreateRequest(
            deployment_id="d",
            trigger_type=TriggerType.SCHEDULE,
            name="x" * 200,
            schedule_expression="rate(1 hour)",
        )


def test_status_enum_default() -> None:
    # The runtime config default should be ACTIVE when not specified
    from app.models.trigger_models import TriggerConfig

    t = TriggerConfig(
        trigger_id="trg-1",
        user_id="u1",
        deployment_id="d1",
        trigger_type=TriggerType.SCHEDULE,
        name="x",
    )
    assert t.status == TriggerStatus.ACTIVE
    assert t.enabled is True
    assert t.trigger_count == 0
