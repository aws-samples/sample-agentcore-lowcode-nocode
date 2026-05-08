"""AgentCore Harness models (Task 11).

Pydantic models backing the ``bedrock-agentcore-control:CreateHarness`` API
surface (as of boto3 1.43.6). These ARE the real shapes — fields map 1:1 to
the ``CreateHarness`` request. See:
https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/create_harness.html
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HarnessStatus(str, Enum):
    CREATING = "CREATING"
    CREATE_FAILED = "CREATE_FAILED"
    UPDATING = "UPDATING"
    UPDATE_FAILED = "UPDATE_FAILED"
    READY = "READY"
    DELETING = "DELETING"
    DELETE_FAILED = "DELETE_FAILED"


TERMINAL_HARNESS_STATUSES = {
    HarnessStatus.READY,
    HarnessStatus.CREATE_FAILED,
    HarnessStatus.UPDATE_FAILED,
    HarnessStatus.DELETE_FAILED,
}


class ModelProvider(str, Enum):
    BEDROCK = "BEDROCK"
    OPENAI = "OPENAI"
    GEMINI = "GEMINI"


class TruncationStrategy(str, Enum):
    SLIDING_WINDOW = "sliding_window"
    SUMMARIZATION = "summarization"
    NONE = "none"


class HarnessToolType(str, Enum):
    REMOTE_MCP = "remote_mcp"
    AGENTCORE_BROWSER = "agentcore_browser"
    AGENTCORE_GATEWAY = "agentcore_gateway"
    INLINE_FUNCTION = "inline_function"
    AGENTCORE_CODE_INTERPRETER = "agentcore_code_interpreter"


# ---------------------------------------------------------------------------
# Model configs (tagged union)
# ---------------------------------------------------------------------------


class BedrockModelConfig(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=256)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=200_000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {"modelId": self.model_id}
        if self.max_tokens is not None:
            out["maxTokens"] = self.max_tokens
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.top_p is not None:
            out["topP"] = self.top_p
        return out


class OpenAiModelConfig(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=256)
    api_key_arn: str = Field(..., min_length=20, max_length=2048)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=200_000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "modelId": self.model_id,
            "apiKeyArn": self.api_key_arn,
        }
        for k, v in (
            ("maxTokens", self.max_tokens),
            ("temperature", self.temperature),
            ("topP", self.top_p),
        ):
            if v is not None:
                out[k] = v
        return out


class GeminiModelConfig(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=256)
    api_key_arn: str = Field(..., min_length=20, max_length=2048)
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "modelId": self.model_id,
            "apiKeyArn": self.api_key_arn,
        }
        for k, v in (
            ("maxTokens", self.max_tokens),
            ("temperature", self.temperature),
            ("topP", self.top_p),
            ("topK", self.top_k),
        ):
            if v is not None:
                out[k] = v
        return out


class HarnessModelConfig(BaseModel):
    """Tagged union — exactly one of the three must be set."""

    bedrock: Optional[BedrockModelConfig] = None
    openai: Optional[OpenAiModelConfig] = None
    gemini: Optional[GeminiModelConfig] = None

    def to_api(self) -> dict[str, Any]:
        if self.bedrock:
            return {"bedrockModelConfig": self.bedrock.to_api()}
        if self.openai:
            return {"openAiModelConfig": self.openai.to_api()}
        if self.gemini:
            return {"geminiModelConfig": self.gemini.to_api()}
        raise ValueError("exactly one model config must be provided")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class HarnessTool(BaseModel):
    type: HarnessToolType
    name: Optional[str] = Field(default=None, max_length=128)
    # Type-specific config — only the one matching `type` is used.
    remote_mcp_url: Optional[str] = Field(default=None, max_length=2048)
    remote_mcp_headers: Optional[dict[str, str]] = None
    gateway_arn: Optional[str] = Field(default=None, max_length=2048)
    browser_arn: Optional[str] = None
    code_interpreter_arn: Optional[str] = None
    # inline_function
    inline_description: Optional[str] = Field(default=None, max_length=1024)
    inline_input_schema: Optional[dict[str, Any]] = None

    def to_api(self) -> dict[str, Any]:
        config: dict[str, Any] = {}
        t = self.type
        if t == HarnessToolType.REMOTE_MCP:
            if not self.remote_mcp_url:
                raise ValueError("remote_mcp_url is required for remote_mcp tools")
            rm: dict[str, Any] = {"url": self.remote_mcp_url}
            if self.remote_mcp_headers:
                rm["headers"] = self.remote_mcp_headers
            config = {"remoteMcp": rm}
        elif t == HarnessToolType.AGENTCORE_GATEWAY:
            if not self.gateway_arn:
                raise ValueError("gateway_arn is required for agentcore_gateway tools")
            config = {"agentCoreGateway": {"gatewayArn": self.gateway_arn}}
        elif t == HarnessToolType.AGENTCORE_BROWSER:
            inner: dict[str, Any] = {}
            if self.browser_arn:
                inner["browserArn"] = self.browser_arn
            config = {"agentCoreBrowser": inner}
        elif t == HarnessToolType.AGENTCORE_CODE_INTERPRETER:
            inner = {}
            if self.code_interpreter_arn:
                inner["codeInterpreterArn"] = self.code_interpreter_arn
            config = {"agentCoreCodeInterpreter": inner}
        elif t == HarnessToolType.INLINE_FUNCTION:
            if not self.inline_description or self.inline_input_schema is None:
                raise ValueError(
                    "inline_description and inline_input_schema are required for inline_function"
                )
            config = {
                "inlineFunction": {
                    "description": self.inline_description,
                    "inputSchema": self.inline_input_schema,
                }
            }
        out: dict[str, Any] = {"type": t.value, "config": config}
        if self.name:
            out["name"] = self.name
        return out


# ---------------------------------------------------------------------------
# Top-level Harness request
# ---------------------------------------------------------------------------


class HarnessTruncationConfig(BaseModel):
    strategy: TruncationStrategy = TruncationStrategy.SLIDING_WINDOW
    sliding_window_messages: Optional[int] = Field(default=None, ge=1, le=1024)
    summary_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    preserve_recent_messages: Optional[int] = Field(default=None, ge=0, le=1024)
    summarization_system_prompt: Optional[str] = Field(default=None, max_length=8192)

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {"strategy": self.strategy.value}
        if self.strategy == TruncationStrategy.SLIDING_WINDOW:
            inner: dict[str, Any] = {}
            if self.sliding_window_messages is not None:
                inner["messagesCount"] = self.sliding_window_messages
            if inner:
                out["config"] = {"slidingWindow": inner}
        elif self.strategy == TruncationStrategy.SUMMARIZATION:
            inner = {}
            if self.summary_ratio is not None:
                inner["summaryRatio"] = self.summary_ratio
            if self.preserve_recent_messages is not None:
                inner["preserveRecentMessages"] = self.preserve_recent_messages
            if self.summarization_system_prompt:
                inner["summarizationSystemPrompt"] = self.summarization_system_prompt
            if inner:
                out["config"] = {"summarization": inner}
        return out


class HarnessMemoryConfig(BaseModel):
    memory_arn: str = Field(..., min_length=20, max_length=2048)
    actor_id: Optional[str] = Field(default=None, max_length=128)
    messages_count: Optional[int] = Field(default=None, ge=1, le=512)

    def to_api(self) -> dict[str, Any]:
        inner: dict[str, Any] = {"arn": self.memory_arn}
        if self.actor_id:
            inner["actorId"] = self.actor_id
        if self.messages_count is not None:
            inner["messagesCount"] = self.messages_count
        return {"agentCoreMemoryConfiguration": inner}


class HarnessCreateRequest(BaseModel):
    """API surface for POST /api/harness."""

    harness_name: str = Field(..., min_length=1, max_length=64)
    model: HarnessModelConfig
    system_prompt: Optional[str] = Field(default=None, max_length=16_384)
    tools: list[HarnessTool] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    memory: Optional[HarnessMemoryConfig] = None
    truncation: Optional[HarnessTruncationConfig] = None
    max_iterations: Optional[int] = Field(default=None, ge=1, le=500)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    timeout_seconds: Optional[int] = Field(default=None, ge=10, le=3_600)
    # Network mode: PUBLIC by default. VPC requires subnets/SGs.
    network_mode: str = Field(default="PUBLIC", pattern="^(PUBLIC|VPC)$")
    security_group_ids: list[str] = Field(default_factory=list)
    subnet_ids: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("harness_name")
    @classmethod
    def _name_rules(cls, v: str) -> str:
        # Matches AWS rule: must start with letter, alphanumeric + underscore, <= 64
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$", v):
            raise ValueError(
                "harness_name must start with a letter and contain only "
                "alphanumerics or underscores (max 64 chars)"
            )
        return v


class HarnessRecord(BaseModel):
    """Ownership-mapping record stored in our DynamoDB table (separate from
    AWS's internal harness metadata)."""

    harness_id: str
    user_id: str
    name: str
    arn: str = ""
    status: HarnessStatus = HarnessStatus.CREATING
    model_provider: ModelProvider
    model_id: str
    agent_runtime_arn: Optional[str] = None
    agent_runtime_id: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class HarnessResponse(BaseModel):
    harness: HarnessRecord
    aws_detail: Optional[dict[str, Any]] = None


class HarnessListResponse(BaseModel):
    harnesses: list[HarnessRecord]


class HarnessInvokeRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=100_000)
    session_id: Optional[str] = Field(default=None, max_length=128)


class HarnessInvokeResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
