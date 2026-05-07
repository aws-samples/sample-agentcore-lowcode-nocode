"""Guardrail management models (Task 06).

Thin pydantic wrappers around Bedrock Guardrails.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


FILTER_STRENGTHS = {"NONE", "LOW", "MEDIUM", "HIGH"}


class ContentFilterCategory(str, Enum):
    SEXUAL = "SEXUAL"
    VIOLENCE = "VIOLENCE"
    HATE = "HATE"
    INSULTS = "INSULTS"
    MISCONDUCT = "MISCONDUCT"
    PROMPT_ATTACK = "PROMPT_ATTACK"


class PiiAction(str, Enum):
    ANONYMIZE = "ANONYMIZE"
    BLOCK = "BLOCK"


class ContentFilter(BaseModel):
    type: ContentFilterCategory
    input_strength: str = Field(default="HIGH")
    output_strength: str = Field(default="HIGH")


class TopicFilter(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    definition: str = Field(..., min_length=1, max_length=1000)
    examples: list[str] = Field(default_factory=list)


class PiiFilter(BaseModel):
    type: str = Field(..., max_length=128)
    action: PiiAction = PiiAction.ANONYMIZE


class WordFilter(BaseModel):
    text: str = Field(..., min_length=1, max_length=100)


class GuardrailConfigRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    blocked_input_message: str = Field(
        default="I cannot process this request due to content policy.",
        max_length=500,
    )
    blocked_output_message: str = Field(
        default="I cannot provide this response due to content policy.",
        max_length=500,
    )
    content_filters: list[ContentFilter] = Field(default_factory=list)
    topic_filters: list[TopicFilter] = Field(default_factory=list)
    pii_filters: list[PiiFilter] = Field(default_factory=list)
    word_filters: list[WordFilter] = Field(default_factory=list)


class GuardrailRecord(BaseModel):
    """DynamoDB-backed pointer to a Bedrock-managed guardrail owned by a user."""

    guardrail_id: str
    user_id: str
    name: str
    description: str = ""
    version: str = "DRAFT"
    arn: str = ""
    content_filters_count: int = 0
    topic_filters_count: int = 0
    pii_filters_count: int = 0
    word_filters_count: int = 0
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class GuardrailRecordResponse(BaseModel):
    guardrail: GuardrailRecord


class GuardrailListResponse(BaseModel):
    guardrails: list[GuardrailRecord]


class TestGuardrailRequest(BaseModel):
    guardrail_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=8192)
    source: str = Field(default="INPUT", pattern="^(INPUT|OUTPUT)$")


class TestGuardrailResponse(BaseModel):
    action: str  # NONE, GUARDRAIL_INTERVENED
    blocked: bool
    outputs: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
