"""Step handler: Write final deployment status.

Receives deployment_id + results, writes final state (succeeded/failed)
to the Deployment_State_Table.

Requirements: 3.6
"""

import logging
import os
from datetime import datetime, timezone

from app.models.deployment_models import DeploymentStatusEnum, DeploymentStepName
from app.services.deployment_state_store import DeploymentStateStore

logger = logging.getLogger(__name__)


def _get_env(name: str, default: str = "") -> str:
    """Read an environment variable with a fallback."""
    return os.environ.get(name, default)


def _get_deployment_store() -> DeploymentStateStore:
    """Create a DeploymentStateStore from environment variables."""
    return DeploymentStateStore(
        table_name=_get_env("DEPLOYMENT_TABLE_NAME", "DeploymentState"),
        region=_get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1")),
    )


def handler(event: dict, context) -> dict:
    """Lambda handler for the final status update step.

    Writes the terminal deployment state (succeeded or failed) to DynamoDB,
    including runtime outputs and error details.

    Args:
        event: Step Functions event with ``deployment_id``, ``runtime_id``,
            ``runtime_endpoint``, ``gateway_result``, and optionally
            ``error`` for failure cases.
        context: Lambda context (unused).

    Returns:
        Dict with ``status`` and ``deployment_id``.
    """
    deployment_id = event.get("deployment_id", "")

    try:
        store = _get_deployment_store()
        store.update_step(
            deployment_id,
            DeploymentStepName.STATUS_UPDATE,
            DeploymentStatusEnum.IN_PROGRESS,
        )

        # Detect errors from both direct invocation ("error" key) and
        # Step Functions Catch handler ("error_info" key with Error/Cause).
        error_details = event.get("error")
        error_info = event.get("error_info")
        if not error_details and error_info:
            if isinstance(error_info, dict):
                error_details = error_info.get("Cause") or error_info.get("Error") or str(error_info)
            else:
                error_details = str(error_info)
        now = datetime.now(timezone.utc)

        # Collect outputs from previous steps (available even on partial failure)
        runtime_id = event.get("runtime_id")
        runtime_arn = event.get("runtime_arn")
        runtime_endpoint = event.get("runtime_endpoint")
        gateway_result = event.get("gateway_result") or {}
        gateway_url = gateway_result.get("gateway_url")
        policy_result = event.get("policy_result") or {}
        memory_result = event.get("memory_result") or {}
        knowledge_base_result = event.get("knowledge_base_result") or {}
        guardrails_result = event.get("guardrails_result") or {}
        mcp_server_runtime_id = event.get("mcp_server_runtime_id")

        if error_details:
            # Save partial results so delete handler can clean up
            store.update_status(
                deployment_id,
                DeploymentStatusEnum.FAILED,
                completed_at=now,
                error_details=str(error_details),
                runtime_id=runtime_id,
                runtime_arn=runtime_arn,
                gateway_result=gateway_result if gateway_result else None,
                policy_result=policy_result if policy_result else None,
                memory_result=memory_result if memory_result else None,
                knowledge_base_result=knowledge_base_result if knowledge_base_result else None,
                guardrails_result=guardrails_result if guardrails_result else None,
                mcp_server_runtime_id=mcp_server_runtime_id,
            )
            return {
                "deployment_id": deployment_id,
                "status": DeploymentStatusEnum.FAILED.value,
                "error_details": str(error_details),
            }

        store.update_status(
            deployment_id,
            DeploymentStatusEnum.SUCCEEDED,
            completed_at=now,
            runtime_endpoint=runtime_endpoint,
            runtime_id=runtime_id,
            runtime_arn=runtime_arn,
            gateway_url=gateway_url,
            gateway_result=gateway_result if gateway_result else None,
            policy_result=policy_result if policy_result else None,
            memory_result=memory_result if memory_result else None,
            knowledge_base_result=knowledge_base_result if knowledge_base_result else None,
            mcp_server_runtime_id=mcp_server_runtime_id,
        )

        return {
            "deployment_id": deployment_id,
            "status": DeploymentStatusEnum.SUCCEEDED.value,
            "runtime_id": runtime_id,
            "runtime_endpoint": runtime_endpoint,
            "gateway_url": gateway_url,
        }

    except Exception as exc:
        logger.exception("Status update step failed for deployment %s", deployment_id)
        # Last-resort: try to mark as failed
        try:
            store = _get_deployment_store()
            store.update_status(
                deployment_id,
                DeploymentStatusEnum.FAILED,
                completed_at=datetime.now(timezone.utc),
                error_details=f"Status update step error: {exc}",
            )
        except Exception:
            logger.exception("Failed to write error state for deployment %s", deployment_id)

        return {
            "deployment_id": deployment_id,
            "status": DeploymentStatusEnum.FAILED.value,
            "error_details": str(exc),
        }
