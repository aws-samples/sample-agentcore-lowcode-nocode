"""Pydantic models for deployment state, runtime configuration, and API request/response types.

These models support the serverless deployment orchestration via Step Functions,
deployment state persistence in DynamoDB, and the Deployment Lambda API surface.
"""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Deployment Enums
# ============================================================================


class DeploymentStatusEnum(str, Enum):
    """Status of a deployment execution tracked in the Deployment_State_Table."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DeploymentStepName(str, Enum):
    """Individual steps in the Step Functions deployment state machine."""

    VALIDATE = "validate"
    MCP_SERVER = "mcp_server"
    CODEGEN = "codegen"
    IAM = "iam"
    GATEWAY = "gateway"
    KNOWLEDGE_BASE = "knowledge_base"
    MEMORY = "memory"
    GUARDRAILS = "guardrails"
    POLICY = "policy"
    RUNTIME_CONFIGURE = "runtime_configure"
    RUNTIME_LAUNCH = "runtime_launch"
    EVALUATION = "evaluation"
    AUTH = "auth"
    STATUS_UPDATE = "status_update"


# ============================================================================
# Deployment State Model (DynamoDB persistence)
# ============================================================================


class DeploymentState(BaseModel):
    """Deployment execution state persisted in the Deployment_State_Table.

    Each record tracks a single deployment from initiation through completion,
    including the current step, runtime outputs, and error details.
    """

    deployment_id: str
    workflow_id: str
    user_id: Optional[str] = None
    execution_arn: Optional[str] = None
    status: DeploymentStatusEnum = DeploymentStatusEnum.PENDING
    current_step: Optional[DeploymentStepName] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    runtime_endpoint: Optional[str] = None
    runtime_id: Optional[str] = None
    gateway_url: Optional[str] = None
    gateway_result: Optional[dict] = None  # Full gateway deployment result for cleanup
    policy_result: Optional[dict] = None  # Policy engine result for cleanup
    knowledge_base_result: Optional[dict] = None  # KB result for cleanup
    guardrails_result: Optional[dict] = None  # Guardrails result for cleanup
    mcp_server_runtime_id: Optional[str] = None
    memory_result: Optional[dict] = None  # Memory deployment result for cleanup
    runtime_arn: Optional[str] = None  # Full ARN of the deployed runtime
    error_details: Optional[str] = None
    ttl: Optional[int] = None  # Unix epoch for DynamoDB TTL (30 days from started_at)


# ============================================================================
# Runtime Configuration Model (moved from routers/deployment.py)
# ============================================================================


class RuntimeConfig(BaseModel):
    """Runtime configuration received from the frontend.

    Uses camelCase aliases to match the frontend JSON payload while exposing
    snake_case attributes in Python. ``ConfigDict(populate_by_name=True)``
    allows construction with either naming convention.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    entrypoint: str = Field(default="agent.py")
    framework: Literal["strands_agents"] = Field(default="strands_agents")
    model: dict
    system_prompt: str = Field(
        alias="systemPrompt",
        default="You are a helpful AI assistant.",
        max_length=10000,
    )
    deployment_type: str = Field(alias="deploymentType", default="S3_CODE_DEPLOY")
    python_runtime: str = Field(alias="pythonRuntime", default="PYTHON_3_13")
    protocol: Literal["HTTP", "MCP", "A2A"] = Field(default="HTTP")
    idle_timeout: int = Field(alias="idleTimeout", ge=60, le=28800, default=900)
    max_lifetime: int = Field(alias="maxLifetime", ge=60, le=28800, default=28800)
    enable_otel: bool = Field(alias="enableOtel", default=False)
    # Strands model provider
    model_provider: Literal[
        "bedrock", "openai", "anthropic", "gemini", "litellm",
        "mistral", "ollama", "sagemaker", "writer", "llamaapi",
        "deepseek", "groq", "together",
    ] = Field(alias="modelProvider", default="bedrock")
    provider_api_key_ref: Optional[str] = Field(alias="providerApiKeyRef", default=None)
    # Multi-agent pattern
    multi_agent_pattern: str = Field(alias="multiAgentPattern", default="none")
    multi_agent_config: Optional[dict] = Field(alias="multiAgentConfig", default=None)


# ============================================================================
# API Request / Response Models
# ============================================================================


class IdentityConfig(BaseModel):
    """Identity provider configuration from the frontend Identity node."""

    model_config = ConfigDict(populate_by_name=True)

    provider: str = "cognito"
    client_id: str = Field(alias="clientId", default="")
    client_secret_ref: str = Field(alias="clientSecretRef", default="")
    discovery_url: str = Field(alias="discoveryUrl", default="")
    scopes: list[str] = Field(default_factory=list)
    audience: Optional[str] = None


class CustomToolDefinition(BaseModel):
    """A custom AI-generated tool to deploy as a Lambda Gateway Target."""

    model_config = ConfigDict(populate_by_name=True)

    tool_name: str = Field(alias="toolName", min_length=1, max_length=64)
    display_name: str = Field(alias="displayName", default="", max_length=128)
    description: str = Field(default="", max_length=1000)
    lambda_code: str = Field(alias="lambdaCode", max_length=50000)
    input_schema: dict = Field(alias="inputSchema", default_factory=dict)


class DeployRequest(BaseModel):
    """Request body for POST /api/deploy."""

    model_config = ConfigDict(populate_by_name=True)

    node_id: str = Field(alias="nodeId", max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    config: RuntimeConfig
    connected_tools: Optional[list] = Field(alias="connectedTools", default=None, max_length=20)
    gateway_config: Optional[dict] = Field(alias="gatewayConfig", default=None)
    gateway_tools: Optional[list] = Field(alias="gatewayTools", default=None, max_length=20)
    template_id: Optional[str] = Field(alias="templateId", default=None, max_length=128)
    identity_config: Optional[IdentityConfig] = Field(alias="identityConfig", default=None)
    custom_tools: Optional[list[CustomToolDefinition]] = Field(alias="customTools", default=None)
    memory_config: Optional[dict] = Field(alias="memoryConfig", default=None)
    evaluation_config: Optional[dict] = Field(alias="evaluationConfig", default=None)
    policy_config: Optional[dict] = Field(alias="policyConfig", default=None)
    mcp_server_config: Optional[dict] = Field(alias="mcpServerConfig", default=None)
    knowledge_base_config: Optional[dict] = Field(alias="knowledgeBaseConfig", default=None)
    guardrails_config: Optional[dict] = Field(alias="guardrailsConfig", default=None)


class DeployResponse(BaseModel):
    """Response body for POST /api/deploy (202 Accepted)."""

    model_config = ConfigDict(populate_by_name=True)

    deployment_id: str = Field(alias="deploymentId")
    execution_arn: Optional[str] = Field(alias="executionArn", default=None)
    status: DeploymentStatusEnum = DeploymentStatusEnum.PENDING
    message: str = "Deployment started"


class TestRequest(BaseModel):
    """Request body for POST /api/test-runtime."""

    model_config = ConfigDict(populate_by_name=True)

    endpoint: Optional[str] = None
    input: str = Field(max_length=10000)
    simulated: bool = False
    runtime_id: Optional[str] = Field(alias="runtimeId", default=None, max_length=256)
    session_id: Optional[str] = Field(alias="sessionId", default=None, max_length=256)
    history: Optional[list] = Field(default=None, max_length=50)


class TestResponse(BaseModel):
    """Response body for POST /api/test-runtime."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    session_id: Optional[str] = Field(alias="sessionId", default=None)
    request_id: Optional[str] = Field(alias="requestId", default=None)
    arn: Optional[str] = None
    logs: Optional[str] = None


class DeleteResponse(BaseModel):
    """Response body for DELETE /api/runtime/{runtime_id}."""

    success: bool
    message: str
