"""Step handler: Create IAM execution role for the runtime.

Requirements: 3.4
"""

import logging
import os

import boto3

from app.models.deployment_models import DeploymentStatusEnum, DeploymentStepName
from app.services.deployment_state_store import DeploymentStateStore
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
        role_name = f"AgentCoreRuntime-{runtime_name}"

        iam_client = boto3.client("iam")
        account_id = boto3.client("sts").get_caller_identity()["Account"]

        role_arn = create_runtime_iam_role(
            iam_client=iam_client,
            role_name=role_name,
            account_id=account_id,
            region=region,
            connected_tools=connected_tools,
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
