"""Trigger lifecycle management.

Creates, enables/disables, and deletes AWS resources that back triggers:
  - schedule triggers   -> EventBridge Scheduler schedule
  - event triggers      -> EventBridge Rule on default bus
  - webhook triggers    -> DynamoDB-only (endpoint is a shared router lambda)

The webhook endpoint is a public API Gateway route: POST /api/webhooks/{path}.
Authentication is via HMAC signature of the request body using the
per-trigger secret stored in Secrets Manager.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets as _secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.trigger_models import (
    TriggerConfig,
    TriggerCreateRequest,
    TriggerStatus,
    TriggerType,
)
from app.services.trigger_store import TriggerStore

logger = logging.getLogger(__name__)


_WEBHOOK_PATH_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project() -> str:
    return os.environ.get("PROJECT_NAME", "agentcore-workflow")


def _env() -> str:
    return os.environ.get("ENVIRONMENT", "dev")


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _schedule_group() -> str:
    return os.environ.get("TRIGGER_SCHEDULE_GROUP", f"{_project()}-{_env()}-triggers")


def _scheduler_role_arn() -> str:
    arn = os.environ.get("TRIGGER_SCHEDULER_ROLE_ARN", "")
    if not arn:
        raise RuntimeError("TRIGGER_SCHEDULER_ROLE_ARN env var not set")
    return arn


def _router_lambda_arn() -> str:
    arn = os.environ.get("TRIGGER_ROUTER_LAMBDA_ARN", "")
    if not arn:
        raise RuntimeError("TRIGGER_ROUTER_LAMBDA_ARN env var not set")
    return arn


def _event_rule_role_arn() -> str:
    return os.environ.get("TRIGGER_EVENT_RULE_ROLE_ARN", "")


def _events_bus_name() -> str:
    return os.environ.get("TRIGGER_EVENT_BUS_NAME", "default")


def _secret_prefix() -> str:
    return os.environ.get("TRIGGER_SECRET_PREFIX", f"/agentcore/{_env()}/trigger-webhook")


class TriggerManager:
    """Create/update/delete AWS-side resources for triggers."""

    def __init__(self, store: TriggerStore) -> None:
        self._store = store
        self._scheduler = boto3.client("scheduler", region_name=_region())
        self._events = boto3.client("events", region_name=_region())
        self._secrets = boto3.client("secretsmanager", region_name=_region())
        self._lambda = boto3.client("lambda", region_name=_region())

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, user_id: str, req: TriggerCreateRequest) -> TriggerConfig:
        trigger_id = f"trg-{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        config = TriggerConfig(
            trigger_id=trigger_id,
            user_id=user_id,
            deployment_id=req.deployment_id,
            runtime_id=req.runtime_id,
            trigger_type=req.trigger_type,
            name=req.name,
            description=req.description,
            enabled=req.enabled,
            status=TriggerStatus.ACTIVE if req.enabled else TriggerStatus.DISABLED,
            schedule_expression=req.schedule_expression,
            schedule_timezone=req.schedule_timezone,
            webhook_path=req.webhook_path,
            event_pattern=req.event_pattern,
            event_bus_name=req.event_bus_name or _events_bus_name(),
            input_template=req.input_template,
            created_at=now,
            updated_at=now,
        )

        # Dispatch by type
        if req.trigger_type == TriggerType.SCHEDULE:
            self._require(req.schedule_expression, "schedule_expression required")
            self._provision_schedule(config)
        elif req.trigger_type == TriggerType.WEBHOOK:
            self._provision_webhook(config)
        elif req.trigger_type == TriggerType.EVENT:
            self._require(req.event_pattern, "event_pattern required")
            self._provision_event_rule(config)
        else:
            raise ValueError(f"Unsupported trigger_type: {req.trigger_type}")

        self._store.put(config)
        return config

    @staticmethod
    def _require(value: Any, message: str) -> None:
        if value is None:
            raise ValueError(message)
        if isinstance(value, str) and not value.strip():
            raise ValueError(message)

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------

    def _schedule_name(self, trigger_id: str) -> str:
        return f"{_project()}-{_env()}-{trigger_id}"[:64]

    def _ensure_schedule_group(self) -> None:
        group = _schedule_group()
        try:
            self._scheduler.get_schedule_group(Name=group)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                self._scheduler.create_schedule_group(Name=group)
            else:
                raise

    def _provision_schedule(self, config: TriggerConfig) -> None:
        self._ensure_schedule_group()
        name = self._schedule_name(config.trigger_id)
        payload = self._build_router_payload(config)
        target = {
            "Arn": _router_lambda_arn(),
            "RoleArn": _scheduler_role_arn(),
            "Input": json.dumps(payload),
            "RetryPolicy": {
                "MaximumRetryAttempts": 3,
                "MaximumEventAgeInSeconds": 3600,
            },
        }
        resp = self._scheduler.create_schedule(
            Name=name,
            GroupName=_schedule_group(),
            ScheduleExpression=config.schedule_expression,
            ScheduleExpressionTimezone=config.schedule_timezone or "UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED" if config.enabled else "DISABLED",
            Target=target,
            ActionAfterCompletion="NONE",
        )
        config.schedule_name = name
        config.schedule_arn = resp.get("ScheduleArn")

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    def _provision_webhook(self, config: TriggerConfig) -> None:
        path = config.webhook_path or config.trigger_id
        if not _WEBHOOK_PATH_RE.match(path):
            raise ValueError(
                "webhook_path must be 1-64 alphanumerics, underscores, or hyphens"
            )
        config.webhook_path = path
        # Generate a random secret and store in Secrets Manager
        secret_value = _secrets.token_urlsafe(32)
        secret_name = f"{_secret_prefix()}/{config.trigger_id}"
        try:
            resp = self._secrets.create_secret(
                Name=secret_name,
                SecretString=secret_value,
                Description=f"HMAC secret for trigger {config.trigger_id}",
                Tags=[
                    {"Key": "user_id", "Value": config.user_id},
                    {"Key": "deployment_id", "Value": config.deployment_id},
                ],
            )
            config.webhook_secret_arn = resp["ARN"]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ResourceExistsException":
                # Rotate by putting a new value
                self._secrets.put_secret_value(
                    SecretId=secret_name, SecretString=secret_value
                )
                meta = self._secrets.describe_secret(SecretId=secret_name)
                config.webhook_secret_arn = meta["ARN"]
            else:
                raise

    # ------------------------------------------------------------------
    # Event rule
    # ------------------------------------------------------------------

    def _rule_name(self, trigger_id: str) -> str:
        return f"{_project()}-{_env()}-{trigger_id}"[:64]

    def _provision_event_rule(self, config: TriggerConfig) -> None:
        rule_name = self._rule_name(config.trigger_id)
        bus = config.event_bus_name or _events_bus_name()
        resp = self._events.put_rule(
            Name=rule_name,
            EventPattern=json.dumps(config.event_pattern),
            State="ENABLED" if config.enabled else "DISABLED",
            EventBusName=bus,
            Description=f"Trigger {config.trigger_id} ({config.name})",
        )
        config.event_rule_name = rule_name
        config.event_rule_arn = resp["RuleArn"]
        payload = self._build_router_payload(config)
        self._events.put_targets(
            Rule=rule_name,
            EventBusName=bus,
            Targets=[
                {
                    "Id": "router",
                    "Arn": _router_lambda_arn(),
                    "Input": json.dumps(payload),
                }
            ],
        )
        # Allow this rule to invoke the router Lambda. The statement id is
        # deterministic so repeated provisioning is idempotent.
        try:
            self._lambda.add_permission(
                FunctionName=_router_lambda_arn(),
                StatementId=f"trg-{config.trigger_id[:40]}",
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=config.event_rule_arn,
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ResourceConflictException":
                raise

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def set_enabled(self, trigger: TriggerConfig, enabled: bool) -> TriggerConfig:
        if trigger.trigger_type == TriggerType.SCHEDULE and trigger.schedule_name:
            sched = self._scheduler.get_schedule(
                Name=trigger.schedule_name, GroupName=_schedule_group()
            )
            self._scheduler.update_schedule(
                Name=trigger.schedule_name,
                GroupName=_schedule_group(),
                ScheduleExpression=sched["ScheduleExpression"],
                ScheduleExpressionTimezone=sched.get("ScheduleExpressionTimezone", "UTC"),
                FlexibleTimeWindow=sched["FlexibleTimeWindow"],
                Target=sched["Target"],
                State="ENABLED" if enabled else "DISABLED",
            )
        elif trigger.trigger_type == TriggerType.EVENT and trigger.event_rule_name:
            action = self._events.enable_rule if enabled else self._events.disable_rule
            action(
                Name=trigger.event_rule_name,
                EventBusName=trigger.event_bus_name or _events_bus_name(),
            )
        trigger.enabled = enabled
        trigger.status = TriggerStatus.ACTIVE if enabled else TriggerStatus.DISABLED
        trigger.updated_at = _now_iso()
        self._store.put(trigger)
        return trigger

    def update_schedule_expression(
        self, trigger: TriggerConfig, expression: str
    ) -> TriggerConfig:
        if trigger.trigger_type != TriggerType.SCHEDULE:
            raise ValueError("schedule_expression only applies to schedule triggers")
        sched = self._scheduler.get_schedule(
            Name=trigger.schedule_name, GroupName=_schedule_group()
        )
        self._scheduler.update_schedule(
            Name=trigger.schedule_name,
            GroupName=_schedule_group(),
            ScheduleExpression=expression,
            ScheduleExpressionTimezone=trigger.schedule_timezone or "UTC",
            FlexibleTimeWindow=sched["FlexibleTimeWindow"],
            Target=sched["Target"],
            State="ENABLED" if trigger.enabled else "DISABLED",
        )
        trigger.schedule_expression = expression
        trigger.updated_at = _now_iso()
        self._store.put(trigger)
        return trigger

    def update_input_template(
        self, trigger: TriggerConfig, template: Optional[str]
    ) -> TriggerConfig:
        trigger.input_template = template
        trigger.updated_at = _now_iso()
        self._store.put(trigger)
        # Re-embed the updated template in the target payload
        payload = self._build_router_payload(trigger)
        if trigger.trigger_type == TriggerType.SCHEDULE and trigger.schedule_name:
            sched = self._scheduler.get_schedule(
                Name=trigger.schedule_name, GroupName=_schedule_group()
            )
            sched["Target"]["Input"] = json.dumps(payload)
            self._scheduler.update_schedule(
                Name=trigger.schedule_name,
                GroupName=_schedule_group(),
                ScheduleExpression=sched["ScheduleExpression"],
                ScheduleExpressionTimezone=sched.get("ScheduleExpressionTimezone", "UTC"),
                FlexibleTimeWindow=sched["FlexibleTimeWindow"],
                Target=sched["Target"],
                State=sched["State"],
            )
        elif trigger.trigger_type == TriggerType.EVENT and trigger.event_rule_name:
            self._events.put_targets(
                Rule=trigger.event_rule_name,
                EventBusName=trigger.event_bus_name or _events_bus_name(),
                Targets=[
                    {
                        "Id": "router",
                        "Arn": _router_lambda_arn(),
                        "Input": json.dumps(payload),
                    }
                ],
            )
        return trigger

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, trigger: TriggerConfig) -> None:
        if trigger.trigger_type == TriggerType.SCHEDULE and trigger.schedule_name:
            try:
                self._scheduler.delete_schedule(
                    Name=trigger.schedule_name, GroupName=_schedule_group()
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    logger.warning("delete_schedule failed: %s", e)
        if trigger.trigger_type == TriggerType.EVENT and trigger.event_rule_name:
            bus = trigger.event_bus_name or _events_bus_name()
            try:
                self._events.remove_targets(
                    Rule=trigger.event_rule_name, EventBusName=bus, Ids=["router"]
                )
            except ClientError as e:
                logger.warning("remove_targets failed: %s", e)
            try:
                self._events.delete_rule(Name=trigger.event_rule_name, EventBusName=bus)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    logger.warning("delete_rule failed: %s", e)
            try:
                self._lambda.remove_permission(
                    FunctionName=_router_lambda_arn(),
                    StatementId=f"trg-{trigger.trigger_id[:40]}",
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    logger.warning("remove_permission failed: %s", e)
        if trigger.trigger_type == TriggerType.WEBHOOK and trigger.webhook_secret_arn:
            try:
                self._secrets.delete_secret(
                    SecretId=trigger.webhook_secret_arn,
                    ForceDeleteWithoutRecovery=True,
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    logger.warning("delete_secret failed: %s", e)
        self._store.delete(trigger.trigger_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_router_payload(self, config: TriggerConfig) -> dict[str, Any]:
        return {
            "trigger_id": config.trigger_id,
            "deployment_id": config.deployment_id,
            "runtime_id": config.runtime_id,
            "user_id": config.user_id,
            "input_template": config.input_template,
            "source": config.trigger_type.value,
        }

    def get_webhook_secret(self, trigger: TriggerConfig) -> Optional[str]:
        if not trigger.webhook_secret_arn:
            return None
        try:
            resp = self._secrets.get_secret_value(SecretId=trigger.webhook_secret_arn)
            return resp.get("SecretString")
        except ClientError as e:
            logger.warning("get_secret_value failed: %s", e)
            return None
