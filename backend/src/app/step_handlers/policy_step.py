"""Step handler: Create AgentCore Policy Engine and attach to Gateway.

Creates a Cedar policy engine and attaches it to the gateway in ENFORCE mode.
Runs AFTER gateway creation since it needs the gateway ID.

References:
- https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/01-tutorials/08-AgentCore-policy
- https://github.com/aws/bedrock-agentcore-starter-toolkit (operations/policy/client.py)
"""

import logging
import os
import re
import time

import boto3

from app.models.deployment_models import DeploymentStatusEnum, DeploymentStepName
from app.services.deployment_state_store import DeploymentStateStore

logger = logging.getLogger(__name__)


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_deployment_store() -> DeploymentStateStore:
    return DeploymentStateStore(
        table_name=_get_env("DEPLOYMENT_TABLE_NAME", "DeploymentState"),
        region=_get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1")),
    )


def _wait_for_policy_engine(client, engine_id: str, timeout: int = 60) -> dict:
    """Poll until policy engine is ACTIVE/READY or timeout."""
    for _ in range(timeout // 5):
        resp = client.get_policy_engine(policyEngineId=engine_id)
        status = resp.get("status", "")
        if status in ("ACTIVE", "READY"):
            return resp
        if "FAILED" in status:
            raise RuntimeError(f"Policy engine entered {status}")
        time.sleep(5)
    raise RuntimeError(f"Policy engine {engine_id} did not become ACTIVE in {timeout}s")


def handler(event: dict, context) -> dict:
    deployment_id = event.get("deployment_id", "")

    try:
        store = _get_deployment_store()
        store.update_step(deployment_id, DeploymentStepName.POLICY, DeploymentStatusEnum.IN_PROGRESS)

        policy_config = event.get("policy_config") or {}
        region = _get_env("APP_AWS_REGION", _get_env("AWS_REGION", "us-east-1"))
        gateway_result = event.get("gateway_result") or {}

        if not policy_config.get("enabled", True):
            return {
                **event,
                "policy_result": {
                    "success": True,
                    "message": "Policy disabled, skipping",
                },
            }

        gateway_id = gateway_result.get("gateway_id", "")
        gateway_arn = gateway_result.get("gateway_arn", "")

        if not gateway_id:
            return {
                **event,
                "policy_result": {
                    "success": False,
                    "message": "No gateway_id available for policy attachment",
                },
            }

        agentcore_ctrl = boto3.client("bedrock-agentcore-control", region_name=region)

        raw_engine_name = policy_config.get("name", f"PolicyEngine_{gateway_id[:16]}")
        # Engine names must match [A-Za-z][A-Za-z0-9_]* — no hyphens
        engine_name = re.sub(r"[^A-Za-z0-9_]", "_", raw_engine_name)

        # Create or reuse policy engine
        engine_id = None
        engine_arn = None

        try:
            existing = agentcore_ctrl.list_policy_engines(maxResults=100)
            for pe in existing.get("policyEngines", existing.get("items", [])):
                if pe.get("name") == engine_name:
                    engine_id = pe.get("policyEngineId")
                    engine_arn = pe.get("policyEngineArn")
                    logger.info("Reusing existing policy engine: %s", engine_id)
                    break
        except Exception as e:
            logger.warning("Could not list policy engines: %s", e)

        if not engine_id:
            resp = agentcore_ctrl.create_policy_engine(
                name=engine_name,
                description=f"Policy engine for gateway {gateway_id}",
            )
            engine_id = resp.get("policyEngineId", "")
            engine_arn = resp.get("policyEngineArn", "")
            logger.info("Created policy engine: %s", engine_id)

            # Wait for it to be ready
            _wait_for_policy_engine(agentcore_ctrl, engine_id)

        # Create default permit-all policy so the gateway isn't blocked
        # (Empty policy engine in ENFORCE mode = deny all)
        policies = policy_config.get("policies", [])
        if not policies:
            # Default: permit all tools on this gateway
            # Cedar requires a `when` clause — unconditioned permits are rejected
            if gateway_arn:
                default_statement = f'permit(principal, action, resource == AgentCore::Gateway::"{gateway_arn}")\nwhen {{ true }};'
            else:
                default_statement = 'permit(principal, action, resource is AgentCore::Gateway)\nwhen { true };'

            policies = [
                {
                    "name": "default_permit_all",
                    "description": "Default permit-all policy for gateway tools",
                    "statement": default_statement,
                }
            ]

        for pol in policies:
            pol_name = re.sub(r"[^A-Za-z0-9_]", "_", pol.get("name", "default_policy"))
            try:
                agentcore_ctrl.create_policy(
                    policyEngineId=engine_id,
                    name=pol_name,
                    description=pol.get("description", ""),
                    definition={"cedar": {"statement": pol.get("statement", "permit(principal, action, resource);")}},
                )
                logger.info("Created policy: %s", pol_name)
            except Exception as e:
                if "ConflictException" in str(e) or "already exists" in str(e):
                    logger.info("Policy '%s' already exists, skipping", pol_name)
                else:
                    logger.warning("Could not create policy '%s': %s", pol_name, e)

        # Attach policy engine to gateway
        mode = policy_config.get("mode", "ENFORCE")
        # Get current gateway config to preserve existing fields
        gw_detail = agentcore_ctrl.get_gateway(gatewayIdentifier=gateway_id)

        update_params = {
            "gatewayIdentifier": gateway_id,
            "name": gw_detail.get("name", ""),
            "roleArn": gw_detail.get("roleArn", ""),
            "protocolType": gw_detail.get("protocolType", "MCP"),
            "policyEngineConfiguration": {"arn": engine_arn, "mode": mode},
        }
        # Preserve optional fields if present
        for optional_field in (
            "description",
            "authorizerType",
            "authorizerConfiguration",
            "protocolConfiguration",
            "kmsKeyArn",
        ):
            if gw_detail.get(optional_field):
                update_params[optional_field] = gw_detail[optional_field]

        agentcore_ctrl.update_gateway(**update_params)
        logger.info(
            "Attached policy engine %s to gateway %s in %s mode",
            engine_id,
            gateway_id,
            mode,
        )

        # Wait for gateway to be ready again
        for _ in range(24):
            gw = agentcore_ctrl.get_gateway(gatewayIdentifier=gateway_id)
            if gw.get("status") == "READY":
                break
            time.sleep(5)

        return {
            **event,
            "policy_result": {
                "success": True,
                "engine_id": engine_id,
                "engine_arn": engine_arn,
                "engine_name": engine_name,
                "mode": mode,
            },
        }

    except Exception:
        logger.exception("Policy step failed for deployment %s", deployment_id)
        raise
