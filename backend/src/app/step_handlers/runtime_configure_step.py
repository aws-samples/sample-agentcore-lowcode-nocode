"""Step handler: Create AgentCore runtime via boto3 API.

Requirements: 3.5
"""

# Platform OTEL bootstrap — MUST be first import. See lambda_handler.py.
import app.services._otel_platform  # noqa: F401

import logging
import os
import re

import boto3

from app.models.deployment_models import (
    DeploymentStatusEnum,
    DeploymentStepName,
    RuntimeConfig,
)
from app.services.deployment_state_store import DeploymentStateStore
from app.services.observability import build_otel_env_vars, get_platform_observability_defaults
from app.services.runtime_deployer import create_agent_runtime, sanitize_runtime_name

logger = logging.getLogger(__name__)


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _to_cross_region_model_id(model_id: str) -> str:
    """Ensure model ID uses cross-region inference profile format with version suffix."""
    if not model_id:
        return model_id
    if not model_id.startswith(("us.", "global.", "eu.", "ap.")):
        model_id = f"us.{model_id}"
    # Bedrock inference profiles require a version suffix like -v1:0
    if "anthropic." in model_id and not re.search(r"-v\d+:\d+$", model_id):
        model_id = f"{model_id}-v1:0"
    return model_id


def _get_deployment_store() -> DeploymentStateStore:
    return DeploymentStateStore(
        table_name=_get_env("DEPLOYMENT_TABLE_NAME", "DeploymentState"),
        region=_get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1")),
    )


def handler(event: dict, context) -> dict:
    deployment_id = event.get("deployment_id", "")

    try:
        store = _get_deployment_store()
        store.update_step(
            deployment_id,
            DeploymentStepName.RUNTIME_CONFIGURE,
            DeploymentStatusEnum.IN_PROGRESS,
        )

        config_dict = event.get("config", {})
        config = RuntimeConfig.model_validate(config_dict)
        region = _get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1"))

        runtime_name = sanitize_runtime_name(config.name)
        role_arn = event.get("role_arn", "")
        s3_bucket = event.get("s3_bucket", "")
        s3_key = event.get("s3_key", "")
        entrypoint = event.get("entrypoint", config.entrypoint or "agent.py")

        if not role_arn:
            raise RuntimeError("No role_arn provided from IAM step")
        if not s3_bucket:
            raise RuntimeError("No s3_bucket provided from codegen step")

        agentcore_ctrl = boto3.client("bedrock-agentcore-control", region_name=region)

        # Build environment variables for the runtime
        env_vars = {}
        model_cfg = config.model
        if model_cfg:
            # model_cfg may be a Pydantic model or a plain dict depending on serialization
            if hasattr(model_cfg, "modelId"):
                raw_model_id = model_cfg.modelId or ""
            elif isinstance(model_cfg, dict):
                raw_model_id = model_cfg.get("modelId", model_cfg.get("model_id", ""))
            else:
                raw_model_id = ""
            env_vars["MODEL_ID"] = _to_cross_region_model_id(raw_model_id)

        gateway_result = event.get("gateway_result") or {}
        memory_result = event.get("memory_result") or {}
        guardrails_result = event.get("guardrails_result") or {}
        if guardrails_result.get("guardrail_id"):
            env_vars["GUARDRAIL_ID"] = guardrails_result["guardrail_id"]
            env_vars["GUARDRAIL_VERSION"] = guardrails_result.get("guardrail_version", "DRAFT")
        if gateway_result.get("gateway_url"):
            env_vars["GATEWAY_URL"] = gateway_result["gateway_url"]
        if memory_result.get("memory_id"):
            env_vars["MEMORY_ID"] = memory_result["memory_id"]

        # Inject knowledge base id so the agent's retrieve_from_kb tool can
        # call bedrock-agent-runtime:Retrieve. See tasks/lessons.md Bug 87.
        kb_result = event.get("knowledge_base_result") or {}
        if kb_result.get("knowledge_base_id"):
            env_vars["KB_ID"] = kb_result["knowledge_base_id"]
        elif kb_result.get("kb_id"):
            env_vars["KB_ID"] = kb_result["kb_id"]
        client_info = gateway_result.get("client_info") or {}
        idp_provider = client_info.get("provider", "cognito")

        if idp_provider == "cognito" or not idp_provider:
            # Cognito env vars (existing behavior)
            if client_info.get("client_id"):
                env_vars["COGNITO_CLIENT_ID"] = client_info["client_id"]
            if client_info.get("client_secret"):
                env_vars["COGNITO_CLIENT_SECRET"] = client_info["client_secret"]
            if client_info.get("token_endpoint"):
                env_vars["COGNITO_TOKEN_ENDPOINT"] = client_info["token_endpoint"]
            if client_info.get("scope"):
                env_vars["COGNITO_SCOPE"] = client_info["scope"]
        else:
            # External IDP env vars (Okta, Azure AD, Auth0, custom)
            env_vars["AUTH_PROVIDER"] = idp_provider
            if client_info.get("client_id"):
                env_vars["OAUTH_CLIENT_ID"] = client_info["client_id"]
            if client_info.get("client_secret"):
                env_vars["OAUTH_CLIENT_SECRET"] = client_info["client_secret"]
            if client_info.get("token_endpoint"):
                env_vars["OAUTH_TOKEN_ENDPOINT"] = client_info["token_endpoint"]
            if client_info.get("scope"):
                env_vars["OAUTH_SCOPE"] = client_info["scope"]

        # Inject OTLP observability env vars. Single source of truth shared
        # with the direct-deploy and CFN paths. When platform-level OTEL is
        # configured (SSM /agentcore-workflow/{env}/otel/*), per-canvas values
        # for endpoint/secret/sample are dropped and platform values win.
        otel_env = build_otel_env_vars(
            event.get("observability_config") or (
                config.observability.model_dump() if getattr(config, "observability", None) else None
            ),
            runtime_name=runtime_name,
            deployment_id=deployment_id,
            enable_otel_legacy=bool(getattr(config, "enable_otel", False)),
            platform_defaults=get_platform_observability_defaults(),
        )
        env_vars.update(otel_env)

        runtime_result = create_agent_runtime(
            agentcore_ctrl=agentcore_ctrl,
            runtime_name=runtime_name,
            role_arn=role_arn,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            entrypoint=entrypoint,
            python_runtime=config.python_runtime or "PYTHON_3_13",
            protocol=config.protocol or "HTTP",
            env_vars=env_vars if env_vars else None,
        )

        return {
            **event,
            "runtime_id": runtime_result["runtime_id"],
            "runtime_arn": runtime_result.get("arn", ""),
            "configure_result": {
                "success": True,
                "runtime_id": runtime_result["runtime_id"],
            },
        }

    except Exception:
        logger.exception("Runtime configure step failed for deployment %s", deployment_id)
        raise
