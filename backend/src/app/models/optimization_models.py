"""AgentCore Optimization models (Task 12).

Wraps three real API families available in boto3 1.43.6:
  - Configuration Bundles (create/update/get/get_version/list/list_versions/delete)
  - Evaluators (15 built-in + user-defined LLM-as-a-judge / code-based)
  - Online Evaluation Configs (sampling + evaluator binding + data source)

API surface references:
  https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/create_configuration_bundle.html
  https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/create_online_evaluation_config.html
  https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/list_evaluators.html

Recommendations API + explicit A/B Test API are NOT in boto3 1.43.6 as of
this commit; the router exposes them as 501 Not Implemented.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BundleComponent(BaseModel):
    """One component of a configuration bundle.

    The AWS API stores components as a ``map<string, structure>`` keyed by
    resource ARN. Each structure has a single required field: ``configuration``.
    """

    resource_arn: str = Field(..., min_length=20, max_length=2048)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ConfigurationBundleRequest(BaseModel):
    bundle_name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    components: list[BundleComponent] = Field(default_factory=list)
    branch_name: Optional[str] = Field(default="mainline", max_length=128)
    commit_message: Optional[str] = Field(default=None, max_length=512)

    @field_validator("bundle_name")
    @classmethod
    def _bundle_name_rules(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,127}$", v):
            raise ValueError(
                "bundle_name must start with a letter, contain only "
                "alphanumerics/_/- (max 128 chars)"
            )
        return v


class ConfigurationBundleUpdateRequest(BaseModel):
    components: list[BundleComponent] = Field(default_factory=list)
    branch_name: Optional[str] = Field(default=None, max_length=128)
    commit_message: Optional[str] = Field(default=None, max_length=512)
    parent_version_ids: Optional[list[str]] = None
    description: Optional[str] = Field(default=None, max_length=512)


class ConfigurationBundleRecord(BaseModel):
    """Ownership-mapping row (DynamoDB)."""

    bundle_id: str
    user_id: str
    bundle_name: str
    description: str = ""
    bundle_arn: str = ""
    latest_version_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class ConfigurationBundleResponse(BaseModel):
    bundle: ConfigurationBundleRecord
    detail: Optional[dict[str, Any]] = None


class ConfigurationBundleListResponse(BaseModel):
    bundles: list[ConfigurationBundleRecord]


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------


class EvaluatorType(str, Enum):
    BUILTIN = "Builtin"
    CUSTOM = "Custom"


class EvaluatorSummary(BaseModel):
    evaluator_id: str
    evaluator_name: str
    evaluator_arn: str
    evaluator_type: str  # "Builtin" | "Custom"
    level: Optional[str] = None  # TRACE | SESSION | TOOL_CALL
    description: Optional[str] = None
    status: Optional[str] = None
    locked_for_modification: bool = False


class EvaluatorListResponse(BaseModel):
    evaluators: list[EvaluatorSummary]


# ---------------------------------------------------------------------------
# Online evaluation configs
# ---------------------------------------------------------------------------


class SamplingConfigInput(BaseModel):
    sampling_percentage: float = Field(..., ge=0.0, le=100.0)
    session_timeout_minutes: int = Field(default=15, ge=1, le=1440)


class CloudWatchDataSourceInput(BaseModel):
    log_group_names: list[str] = Field(..., min_length=1, max_length=10)
    service_names: list[str] = Field(..., min_length=1, max_length=10)


class OnlineEvaluationConfigRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    sampling: SamplingConfigInput
    data_source: CloudWatchDataSourceInput
    evaluator_ids: list[str] = Field(..., min_length=1, max_length=20)
    execution_role_arn: str = Field(..., min_length=20, max_length=2048)
    enable_on_create: bool = True

    @field_validator("name")
    @classmethod
    def _name_rules(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,127}$", v):
            raise ValueError(
                "name must start with a letter and contain only "
                "alphanumerics/_/- (max 128 chars)"
            )
        return v


class OnlineEvaluationConfigRecord(BaseModel):
    """Ownership-mapping row (DynamoDB)."""

    config_id: str
    user_id: str
    name: str
    description: str = ""
    arn: str = ""
    status: str = "UNKNOWN"
    execution_status: str = "UNKNOWN"
    failure_reason: Optional[str] = None
    sampling_percentage: float = 0.0
    evaluator_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class OnlineEvaluationConfigResponse(BaseModel):
    config: OnlineEvaluationConfigRecord
    detail: Optional[dict[str, Any]] = None


class OnlineEvaluationConfigListResponse(BaseModel):
    configs: list[OnlineEvaluationConfigRecord]
