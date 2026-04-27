"""Direct deployment router for AgentCore.

This router provides a direct deployment endpoint that doesn't require
a saved workflow - it accepts runtime config directly and deploys.

Endpoint:
- POST /api/deploy - Deploy directly from config
- DELETE /api/runtime/{runtime_id} - Delete a runtime
- POST /api/test-runtime - Test a deployed runtime
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models import (
    AgentCoreComponentType,
    AgentFramework,
    AgentServerProtocol,
    ComponentNode,
    DeploymentConfig,
    GatewayConfiguration,
    GatewayTargetType,
    ModelConfiguration,
    ModelProvider,
    RuntimeConfiguration,
    WorkflowDefinition,
)
from app.services.deployment import WorkflowExecutor

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request Models
# ============================================================================


class ModelConfig(BaseModel):
    """Model configuration from frontend."""

    provider: str
    modelId: str
    temperature: float = 0.7
    topP: float = 0.9


class RuntimeConfig(BaseModel):
    """Runtime configuration from frontend."""

    name: str
    entrypoint: str = "agent.py"
    framework: str
    model: ModelConfig
    systemPrompt: str = "You are a helpful assistant."
    deploymentType: str = "direct_code_deploy"
    pythonRuntime: str = "PYTHON_3_13"
    protocol: str = "HTTP"
    idleTimeout: int = 300
    maxLifetime: int = 3600
    enableOtel: bool = True
    executionRoleArn: Optional[str] = None


class GatewayConfig(BaseModel):
    """Gateway configuration from frontend."""

    name: str
    targetType: str = "lambda"
    targetConfig: dict = Field(default_factory=lambda: {"type": "lambda"})
    enableSemanticSearch: bool = True


class DirectDeployRequest(BaseModel):
    """Request body for direct deployment."""

    nodeId: str
    config: RuntimeConfig
    connectedTools: list[str] = Field(default_factory=list)
    gatewayConfig: Optional[GatewayConfig] = None
    gatewayTools: list[str] = Field(default_factory=list)
    templateId: Optional[str] = None
    region: Optional[str] = None
    identityConfig: Optional[dict] = None
    customTools: Optional[list[dict]] = None
    memoryConfig: Optional[dict] = None
    evaluationConfig: Optional[dict] = None
    policyConfig: Optional[dict] = None
    mcpServerConfig: Optional[dict] = None
    knowledgeBaseConfig: Optional[dict] = None
    guardrailsConfig: Optional[dict] = None


class DirectDeployResponse(BaseModel):
    """Response for direct deployment."""

    success: bool
    message: str
    endpoint: Optional[str] = None
    runtimeId: Optional[str] = None
    gatewayUrl: Optional[str] = None
    simulated: bool = False


class TestRuntimeRequest(BaseModel):
    """Request to test a runtime."""

    endpoint: str
    input: str
    simulated: bool = False
    runtimeId: Optional[str] = None
    sessionId: Optional[str] = None
    history: list[dict] = Field(default_factory=list)


class TestRuntimeResponse(BaseModel):
    """Response from testing a runtime."""

    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    sessionId: Optional[str] = None
    requestId: Optional[str] = None
    arn: Optional[str] = None
    logs: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/deploy", response_model=DirectDeployResponse)
async def direct_deploy(request: DirectDeployRequest) -> DirectDeployResponse:
    """Deploy directly from config without saving a workflow.

    This endpoint creates a temporary workflow and deploys it directly.
    """
    try:
        # Convert frontend config to backend models
        framework_map = {
            "strands_agents": AgentFramework.STRANDS_AGENTS,
        }

        provider_map = {
            "anthropic": ModelProvider.ANTHROPIC,
            "bedrock": ModelProvider.BEDROCK,
            "openai": ModelProvider.OPENAI,
        }

        protocol_map = {
            "HTTP": AgentServerProtocol.HTTP,
            "MCP": AgentServerProtocol.MCP,
            "A2A": AgentServerProtocol.A2A,
        }

        # Build model config
        model_config = ModelConfiguration(
            provider=provider_map.get(request.config.model.provider, ModelProvider.ANTHROPIC),
            model_id=request.config.model.modelId,
            temperature=request.config.model.temperature,
            top_p=request.config.model.topP,
        )

        # Build runtime config
        runtime_config = RuntimeConfiguration(
            name=request.config.name,
            entrypoint=request.config.entrypoint,
            framework=framework_map.get(request.config.framework, AgentFramework.STRANDS_AGENTS),
            model=model_config,
            system_prompt=request.config.systemPrompt,
            protocol=protocol_map.get(request.config.protocol, AgentServerProtocol.HTTP),
            enable_otel=request.config.enableOtel,
            execution_role_arn=request.config.executionRoleArn,
        )

        # Build nodes list
        nodes = [
            ComponentNode(
                id=request.nodeId,
                type=AgentCoreComponentType.RUNTIME,
                position={"x": 200, "y": 200},
                data=runtime_config,
            )
        ]

        # Add gateway node if provided
        if request.gatewayConfig:
            target_type_map = {
                "openapi": GatewayTargetType.OPENAPI,
                "lambda": GatewayTargetType.LAMBDA,
                "smithy": GatewayTargetType.SMITHY,
                "api_gateway": GatewayTargetType.API_GATEWAY,
                "prebuilt": GatewayTargetType.PREBUILT,
            }

            gateway_config = GatewayConfiguration(
                name=request.gatewayConfig.name,
                target_type=target_type_map.get(request.gatewayConfig.targetType, GatewayTargetType.LAMBDA),
                target_config=request.gatewayConfig.targetConfig,
                enable_semantic_search=request.gatewayConfig.enableSemanticSearch,
            )

            nodes.append(
                ComponentNode(
                    id=f"{request.nodeId}-gateway",
                    type=AgentCoreComponentType.GATEWAY,
                    position={"x": 400, "y": 200},
                    data=gateway_config,
                )
            )

        # Determine region: use request, env var, or default
        region = request.region or os.getenv("APP_AWS_REGION") or os.getenv("AWS_REGION", "us-east-1")

        # Create temporary workflow with all required fields
        from app.models.workflow import Viewport, WorkflowMetadata

        now = datetime.now(timezone.utc)

        workflow = WorkflowDefinition(
            id=str(uuid.uuid4()),
            name=f"Direct Deploy - {request.config.name}",
            description="Direct deployment workflow",
            version="1.0.0",
            nodes=nodes,
            edges=[],
            viewport=Viewport(x=0, y=0, zoom=1.0),
            metadata=WorkflowMetadata(
                author="direct-deploy",
                aws_region=region,
            ),
            created_at=now,
            updated_at=now,
        )

        # Create deployment config
        deployment_config = DeploymentConfig(aws_region=region)

        # Deploy — pass template_id, connected_tools, gateway_tools, and
        # custom_tools so WorkflowExecutor can deploy Gateway targets
        executor = WorkflowExecutor(region=region)
        result = await executor.deploy(
            workflow,
            deployment_config,
            template_id=request.templateId,
            connected_tools=request.connectedTools,
            gateway_tools=request.gatewayTools,
            custom_tools=request.customTools or [],
            identity_config=request.identityConfig,
            mcp_server_config=request.mcpServerConfig,
            memory_config=request.memoryConfig,
            evaluation_config=request.evaluationConfig,
            policy_config=request.policyConfig,
            guardrails_config=request.guardrailsConfig,
            knowledge_base_config=request.knowledgeBaseConfig,
        )

        if result.status == "success":
            # Extract gateway URL from deployment result if gateway was deployed
            gateway_url = None
            if hasattr(result, "created_resources") and result.created_resources:
                for resource in result.created_resources:
                    if resource.startswith("gateway:"):
                        gateway_url = resource.split(":", 1)[1] if ":" in resource else None

            return DirectDeployResponse(
                success=True,
                message="Deployed successfully to AWS AgentCore!",
                endpoint=result.endpoint_url,
                runtimeId=result.runtime_id or request.config.name,
                gatewayUrl=gateway_url,
                simulated=False,
            )
        else:
            return DirectDeployResponse(
                success=False,
                message=result.error_message or "Deployment failed",
                simulated=False,
            )

    except Exception as e:
        logger.error(f"Direct deployment failed: {e}")
        return DirectDeployResponse(
            success=False,
            message=str(e),
            simulated=False,
        )


@router.delete("/runtime/{runtime_id}")
async def delete_runtime(runtime_id: str) -> dict:
    """Delete a deployed runtime."""
    try:
        from app.services.runtime_deployer import (
            destroy_runtime as boto3_destroy_runtime,
        )

        region = os.getenv("APP_AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))
        result = boto3_destroy_runtime(runtime_id, region)
        return result

    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test-runtime", response_model=TestRuntimeResponse)
async def test_runtime(request: TestRuntimeRequest) -> TestRuntimeResponse:
    """Test a deployed runtime by sending a message."""
    try:
        if request.simulated:
            # Return simulated response
            return TestRuntimeResponse(
                success=True,
                response=f"[Simulated] Response to: {request.input}",
                sessionId=request.sessionId or str(uuid.uuid4())[:8],
                requestId=str(uuid.uuid4())[:8],
            )

        # Use boto3 to invoke the AgentCore runtime
        import boto3
        import json as _json

        from botocore.config import Config

        region = os.getenv("APP_AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))
        # Set read_timeout to 18s so Lambda returns well before API Gateway's 29s hard limit.
        # Lambda cold start + boto3 init takes ~3-5s overhead.
        # The frontend has retry logic for cold start timeouts.
        client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(read_timeout=18, connect_timeout=5, retries={"max_attempts": 0}),
        )

        session_id = request.sessionId or str(uuid.uuid4())[:8]

        # Build the runtime ARN from the endpoint or runtimeId
        runtime_arn = request.endpoint or ""
        if not runtime_arn and request.runtimeId:
            # Construct ARN from runtime ID
            account_id = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
            runtime_arn = f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{request.runtimeId}"

        # Strip /runtime-endpoint/DEFAULT suffix if present (invoke uses runtime ARN, not endpoint ARN)
        if "/runtime-endpoint/" in runtime_arn:
            runtime_arn = runtime_arn.split("/runtime-endpoint/")[0]

        payload = _json.dumps({"prompt": request.input})

        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            payload=payload,
        )

        # Read response body — try "response" key first (AgentCore data-plane API),
        # then fall back to "body" for legacy compatibility
        body = response.get("response") or response.get("body", b"")
        if hasattr(body, "read"):
            body = body.read()
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")

        # Try to parse JSON response
        try:
            parsed = _json.loads(body)
            full_response = parsed.get("response", body)
        except (_json.JSONDecodeError, TypeError):
            full_response = body

        return TestRuntimeResponse(
            success=True,
            response=str(full_response) or "No response received",
            sessionId=session_id,
            requestId=response.get("ResponseMetadata", {}).get("RequestId"),
            arn=runtime_arn,
        )

    except Exception as e:
        logger.error(f"Test runtime failed: {e}")
        return TestRuntimeResponse(
            success=False,
            error=str(e),
        )
