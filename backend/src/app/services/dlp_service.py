"""DLP service (Task 10).

Two-layer PII detection:
  1. Regex patterns (deterministic, fast, low-cost) for common PII types
  2. Amazon Comprehend detect_pii_entities() for coverage beyond regex

Actions:
  - NONE:   allow through
  - MASK:   replace each match with "[REDACTED-<TYPE>]"
  - BLOCK:  reject the content entirely
  - ALERT:  allow but log an audit event

Policies are configured per-deployment in DlpPolicies DDB.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _get_dynamodb_resource,
    _get_item,
    _get_table,
    _put_item,
)

logger = logging.getLogger(__name__)


# Deterministic patterns
_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    "PHONE_US": re.compile(
        r"\b(?:\+?1[-.\s]?)?\(?([2-9]\d{2})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})\b"
    ),
    "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "AWS_ACCESS_KEY": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
}


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


@dataclass
class DlpMatch:
    type: str
    start: int
    end: int
    text: str


@dataclass
class DlpResult:
    action: str  # "none" | "masked" | "blocked" | "alerted"
    matched_types: list[str]
    match_count: int
    masked_text: Optional[str] = None
    error: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


class DlpPolicyStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, policy: dict) -> dict:
        _put_item(self._table, _convert_floats_to_decimals(dict(policy)))
        return policy

    def get(self, deployment_id: str) -> Optional[dict]:
        item = _get_item(self._table, {"deployment_id": deployment_id})
        if not item:
            return None
        return _convert_decimals_to_floats(dict(item))


class DlpService:
    def __init__(
        self,
        policy_store: Optional[DlpPolicyStore] = None,
        use_comprehend: bool = True,
    ) -> None:
        self._policy_store = policy_store
        self._use_comprehend = use_comprehend
        self._comprehend: Optional[Any] = None

    def _comprehend_client(self) -> Any:
        if self._comprehend is None:
            self._comprehend = boto3.client("comprehend", region_name=_region())
        return self._comprehend

    def scan(
        self,
        text: str,
        *,
        action: str = "mask",
        use_comprehend: Optional[bool] = None,
    ) -> DlpResult:
        """Scan text; return masked/blocked/none based on `action`."""
        if use_comprehend is None:
            use_comprehend = self._use_comprehend
        matches = self._regex_scan(text)
        if use_comprehend and len(text) <= 5000:
            try:
                matches.extend(self._comprehend_scan(text))
            except Exception as e:
                logger.warning("comprehend detect_pii failed: %s", e)
        # De-dupe by (start,end)
        seen = set()
        deduped: list[DlpMatch] = []
        for m in matches:
            key = (m.start, m.end)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(m)
        matched_types = sorted({m.type for m in deduped})

        if action == "block":
            if deduped:
                return DlpResult(
                    action="blocked",
                    matched_types=matched_types,
                    match_count=len(deduped),
                )
            return DlpResult(action="none", matched_types=[], match_count=0)

        if action == "mask":
            masked = self._mask(text, deduped)
            return DlpResult(
                action="masked" if deduped else "none",
                matched_types=matched_types,
                match_count=len(deduped),
                masked_text=masked,
            )

        if action == "alert":
            return DlpResult(
                action="alerted" if deduped else "none",
                matched_types=matched_types,
                match_count=len(deduped),
            )

        # "none" — just report
        return DlpResult(
            action="none",
            matched_types=matched_types,
            match_count=len(deduped),
        )

    def save_policy(
        self,
        deployment_id: str,
        user_id: str,
        action: str,
        use_comprehend: bool = True,
    ) -> dict:
        if self._policy_store is None:
            raise RuntimeError("policy_store not configured")
        rec = {
            "deployment_id": deployment_id,
            "user_id": user_id,
            "action": action,
            "use_comprehend": use_comprehend,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self._policy_store.put(rec)

    def get_policy(self, deployment_id: str) -> Optional[dict]:
        if self._policy_store is None:
            return None
        return self._policy_store.get(deployment_id)

    # ------------------------------------------------------------------

    def _regex_scan(self, text: str) -> list[DlpMatch]:
        out: list[DlpMatch] = []
        for label, pat in _PATTERNS.items():
            for m in pat.finditer(text):
                out.append(DlpMatch(type=label, start=m.start(), end=m.end(), text=m.group(0)))
        return out

    def _comprehend_scan(self, text: str) -> list[DlpMatch]:
        client = self._comprehend_client()
        resp = client.detect_pii_entities(Text=text, LanguageCode="en")
        out: list[DlpMatch] = []
        for e in resp.get("Entities", []):
            out.append(
                DlpMatch(
                    type=str(e.get("Type", "PII")),
                    start=int(e.get("BeginOffset", 0)),
                    end=int(e.get("EndOffset", 0)),
                    text=text[int(e.get("BeginOffset", 0)) : int(e.get("EndOffset", 0))],
                )
            )
        return out

    @staticmethod
    def _mask(text: str, matches: list[DlpMatch]) -> str:
        if not matches:
            return text
        # Sort by start desc so replacements don't shift indexes
        ms = sorted(matches, key=lambda m: m.start, reverse=True)
        result = text
        for m in ms:
            replacement = f"[REDACTED-{m.type}]"
            result = result[: m.start] + replacement + result[m.end :]
        return result
