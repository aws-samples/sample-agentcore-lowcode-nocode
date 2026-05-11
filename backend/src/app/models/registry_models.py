"""AWS Agent Registry models (Task 13).

Wraps real boto3 1.43.6 ``bedrock-agentcore-control`` APIs:
  CreateRegistry / GetRegistry / ListRegistries / UpdateRegistry / DeleteRegistry
  CreateRegistryRecord / GetRegistryRecord / UpdateRegistryRecord
  ListRegistryRecords / DeleteRegistryRecord / UpdateRegistryRecordStatus /
  SubmitRegistryRecordForApproval

Descriptor types (per the API model): MCP, A2A, CUSTOM, AGENT_SKILLS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RegistryRecordDescriptorType(str, Enum):
    MCP = "MCP"
    A2A = "A2A"
    CUSTOM = "CUSTOM"
    AGENT_SKILLS = "AGENT_SKILLS"


class RegistryRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


# Descriptor payloads (tagged union)


class McpServerDescriptor(BaseModel):
    # AWS requires date-based schema versions like "2025-12-11". Default to
    # the value observed on workshop-registry's existing records; callers can
    # override if AWS publishes a newer version.
    schema_version: Optional[str] = "2025-12-11"
    inline_content: str = Field(..., min_length=1, max_length=262_144)


class McpToolsDescriptor(BaseModel):
    # AWS expects MCP protocol date ("2024-11-05" observed live).
    protocol_version: Optional[str] = "2024-11-05"
    inline_content: str = Field(..., min_length=1, max_length=262_144)


class McpDescriptor(BaseModel):
    server: Optional[McpServerDescriptor] = None
    tools: Optional[McpToolsDescriptor] = None


class A2AAgentCardDescriptor(BaseModel):
    # A2A schema versions: AWS validates against an internal allowlist that's
    # not exposed in the SDK model. The accepted value at the time of this
    # commit is unknown — the 4 candidates "0.2", "1.0", "2024-11-05",
    # "2025-06-01", "2025-12-11" all return ValidationException. Leave as
    # None by default; callers must supply a value AWS accepts for their
    # account/region.
    schema_version: Optional[str] = None
    inline_content: str = Field(..., min_length=1, max_length=262_144)


class A2ADescriptor(BaseModel):
    agent_card: A2AAgentCardDescriptor


class CustomDescriptor(BaseModel):
    inline_content: str = Field(..., min_length=1, max_length=262_144)


class AgentSkillMdDescriptor(BaseModel):
    inline_content: str = Field(..., min_length=1, max_length=262_144)


class AgentSkillDefinitionDescriptor(BaseModel):
    schema_version: Optional[str] = "1.0"
    inline_content: str = Field(..., min_length=1, max_length=262_144)


class AgentSkillsDescriptor(BaseModel):
    skill_md: Optional[AgentSkillMdDescriptor] = None
    skill_definition: Optional[AgentSkillDefinitionDescriptor] = None


class RegistryRecordDescriptors(BaseModel):
    """Tagged union — populate exactly the one matching descriptor_type."""

    mcp: Optional[McpDescriptor] = None
    a2a: Optional[A2ADescriptor] = None
    custom: Optional[CustomDescriptor] = None
    agent_skills: Optional[AgentSkillsDescriptor] = None

    def to_api(self, descriptor_type: RegistryRecordDescriptorType) -> dict[str, Any]:
        t = descriptor_type
        if t == RegistryRecordDescriptorType.MCP and self.mcp:
            out: dict[str, Any] = {}
            inner: dict[str, Any] = {}
            if self.mcp.server:
                inner["server"] = {
                    "inlineContent": self.mcp.server.inline_content,
                }
                if self.mcp.server.schema_version:
                    inner["server"]["schemaVersion"] = self.mcp.server.schema_version
            if self.mcp.tools:
                inner["tools"] = {
                    "inlineContent": self.mcp.tools.inline_content,
                }
                if self.mcp.tools.protocol_version:
                    inner["tools"]["protocolVersion"] = self.mcp.tools.protocol_version
            if inner:
                out["mcp"] = inner
            return out
        if t == RegistryRecordDescriptorType.A2A and self.a2a:
            card = self.a2a.agent_card
            return {
                "a2a": {
                    "agentCard": {
                        "inlineContent": card.inline_content,
                        **({"schemaVersion": card.schema_version} if card.schema_version else {}),
                    }
                }
            }
        if t == RegistryRecordDescriptorType.CUSTOM and self.custom:
            return {"custom": {"inlineContent": self.custom.inline_content}}
        if t == RegistryRecordDescriptorType.AGENT_SKILLS and self.agent_skills:
            inner = {}
            if self.agent_skills.skill_md:
                inner["skillMd"] = {
                    "inlineContent": self.agent_skills.skill_md.inline_content
                }
            if self.agent_skills.skill_definition:
                sd = self.agent_skills.skill_definition
                inner["skillDefinition"] = {
                    "inlineContent": sd.inline_content,
                    **({"schemaVersion": sd.schema_version} if sd.schema_version else {}),
                }
            return {"agentSkills": inner} if inner else {}
        raise ValueError(
            f"descriptor for {descriptor_type.value} missing or malformed"
        )


# Registry (top-level) request/response models


class RegistrySetupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    # Optional JWT discovery URL for custom JWT authorizer. Defaults to Cognito.
    authorizer_discovery_url: Optional[str] = Field(default=None, max_length=2048)
    authorizer_allowed_audience: list[str] = Field(default_factory=list)
    auto_approval: bool = False

    @field_validator("name")
    @classmethod
    def _name_rule(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,127}$", v):
            raise ValueError(
                "name must start with a letter and contain alphanumerics/_/- (max 128)"
            )
        return v


class RegistrySummary(BaseModel):
    registry_id: str
    registry_arn: str
    name: str
    description: str = ""
    status: str = "UNKNOWN"
    authorizer_type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RegistryListResponse(BaseModel):
    registries: list[RegistrySummary]


class RegistryResponse(BaseModel):
    registry: RegistrySummary


# Record request/response


class RecordCreateRequest(BaseModel):
    registry_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    descriptor_type: RegistryRecordDescriptorType
    descriptors: Optional[RegistryRecordDescriptors] = None
    record_version: Optional[str] = Field(default="1.0.0", max_length=32)
    # Or: synchronize from a remote URL (registry pulls metadata)
    sync_from_url: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("name")
    @classmethod
    def _name_rule(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,127}$", v):
            raise ValueError(
                "record name must start with a letter and contain alphanumerics/_/- (max 128)"
            )
        return v

    @field_validator("sync_from_url")
    @classmethod
    def _https_only(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        # SSRF defense-in-depth: reject non-HTTPS and obvious internal IPs.
        if not v.startswith("https://"):
            raise ValueError("sync_from_url must use https://")
        # Quick-check internal IP patterns (AWS metadata, loopback, RFC1918)
        import re

        host = re.match(r"https://([^/:]+)", v)
        if host:
            h = host.group(1).lower()
            if (
                h in ("localhost", "127.0.0.1", "169.254.169.254", "0.0.0.0")
                or h.startswith("10.")
                or h.startswith("192.168.")
                or h.startswith("169.254.")
                or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", h)
            ):
                raise ValueError(f"sync_from_url host {h} is not allowed")
        return v


class RecordSummary(BaseModel):
    registry_id: str
    registry_arn: str
    record_id: str
    record_arn: str
    name: str
    description: str = ""
    descriptor_type: str
    record_version: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RecordListResponse(BaseModel):
    records: list[RecordSummary]


class RecordResponse(BaseModel):
    record: RecordSummary
    detail: Optional[dict[str, Any]] = None


class RecordApprovalRequest(BaseModel):
    status_reason: str = Field(default="", max_length=512)


class RecordRejectRequest(BaseModel):
    status_reason: str = Field(..., min_length=1, max_length=512)


class AutoPublishSourceType(str, Enum):
    DEPLOYMENT = "deployment"
    TOOL = "tool"
    HARNESS = "harness"


class AutoPublishRequest(BaseModel):
    """Publish an entity the user just created as a registry record.

    ``source_id`` identifies the source entity (deployment ID, tool ID,
    harness ID). The server fetches the entity's own record (from our
    DynamoDB tables) to build the descriptor — so the user never hand-
    types any of this.
    """

    source_type: AutoPublishSourceType
    source_id: str = Field(..., min_length=1, max_length=256)
    registry_id: str = Field(..., min_length=1, max_length=128)
    name: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    submit_for_approval: bool = False
    # Tool-specific: callers can provide the generated tool's metadata
    # directly if we can't load it from a store (e.g. test-only tools).
    tool_payload: Optional[dict[str, Any]] = None
