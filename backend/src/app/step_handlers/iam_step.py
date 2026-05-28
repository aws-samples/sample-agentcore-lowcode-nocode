"""Step handler: Create IAM execution role for the runtime.

Requirements: 3.4
"""

# Platform OTEL bootstrap — MUST be first import. See lambda_handler.py.
import app.services._otel_platform  # noqa: F401

import logging
import os

import boto3

from app.models.deployment_models import DeploymentStatusEnum, DeploymentStepName
from app.services.deployment_state_store import DeploymentStateStore
from app.services.observability import (
    _validate_user_otel_secret_arn,
    get_platform_observability_defaults,
)
from app.services.runtime_deployer import create_runtime_iam_role, sanitize_runtime_name

logger = logging.getLogger(__name__)


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_deployment_store() -> DeploymentStateStore:
    return DeploymentStateStore(
        table_name=_get_env("DEPLOYMENT_TABLE_NAME", "DeploymentState"),
        region=_get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1")),
    )


def handler(event: dict, context) -> dict:
    deployment_id = event.get("deployment_id", "")

    try:
        store = _get_deployment_store()
        store.update_step(deployment_id, DeploymentStepName.IAM, DeploymentStatusEnum.IN_PROGRESS)

        config = event.get("config", {})
        connected_tools = event.get("connected_tools") or []
        region = _get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1"))

        runtime_name = sanitize_runtime_name(config.get("name", "agent"))

        # Bug 60 fix: prefer the platform's stable shared runtime role created
        # at CDK stack init. AgentCore's IAM cache for fresh per-deploy roles
        # took 17-20 minutes to propagate in some accounts, causing every
        # deploy to fail with `ValidationException: Access denied when trying
        # to retrieve zip file from S3`. The shared role had its IAM cache
        # propagated during stack creation, so user-deploys see no race.
        shared_role_arn = _get_env("SHARED_RUNTIME_ROLE_ARN", "").strip()
        if shared_role_arn:
            logger.info("Using shared runtime exec role %s (Bug 60)", shared_role_arn)
            shared_role_name = shared_role_arn.rsplit("/", 1)[-1]
            return {
                **event,
                "role_name": shared_role_name,
                "role_arn": shared_role_arn,
                "iam_result": {
                    "success": True,
                    "message": f"Using shared runtime role {shared_role_name}",
                },
            }

        # Legacy per-deploy role path (kept for backward compat with stacks
        # that don't have SHARED_RUNTIME_ROLE_ARN injected).
        role_name = f"AgentCoreRuntime-{runtime_name}"
        iam_client = boto3.client("iam")
        account_id = boto3.client("sts").get_caller_identity()["Account"]

        # Pass through the OTEL auth secret ARN so the role can resolve
        # OTLP headers at agent boot via secretsmanager:GetSecretValue.
        platform_defaults = get_platform_observability_defaults()
        if platform_defaults and platform_defaults.get("auth_header_secret_arn"):
            otel_secret_arn = platform_defaults["auth_header_secret_arn"]
        else:
            obs_cfg = event.get("observability_config") or {}
            otel_secret_arn = obs_cfg.get("auth_header_secret_arn") \
                or obs_cfg.get("authHeaderSecretArn")
            # Critic Finding 1 (BLOCKER): never grant secretsmanager:GetSecretValue
            # on a tenant-supplied ARN that escapes the agentcore-otel/ namespace.
            # If the canvas tries to slip in another tenant's secret ARN, drop it
            # silently (warn-and-disable) rather than failing the deploy — OTEL
            # is best-effort and we don't want a malformed config blocking the
            # runtime.
            if otel_secret_arn:
                try:
                    _validate_user_otel_secret_arn(otel_secret_arn)
                except ValueError as e:
                    logger.warning(
                        "Per-canvas OTEL secret ARN rejected (%s); disabling "
                        "OTEL auth for this runtime.",
                        e,
                    )
                    otel_secret_arn = None

        role_arn = create_runtime_iam_role(
            iam_client=iam_client,
            role_name=role_name,
            account_id=account_id,
            region=region,
            connected_tools=connected_tools,
            otel_secret_arn=otel_secret_arn,
        )

        return {
            **event,
            "role_name": role_name,
            "role_arn": role_arn,
            "iam_result": {"success": True, "message": f"Role {role_name} ready"},
        }

    except Exception:
        logger.exception("IAM step failed for deployment %s", deployment_id)
        raise
