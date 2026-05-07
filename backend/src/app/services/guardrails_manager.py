"""Bedrock Guardrails management service (Task 06).

Creates/updates/deletes Bedrock Guardrails resources and maps them to a
per-user ownership record in DynamoDB so we can enforce tenant isolation
(CreateGuardrail by itself has no user dimension).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.guardrail_models import (
    FILTER_STRENGTHS,
    GuardrailConfigRequest,
    GuardrailRecord,
    PiiAction,
)
from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _delete_item,
    _get_dynamodb_resource,
    _get_item,
    _get_table,
    _put_item,
    _scan_table,
)

logger = logging.getLogger(__name__)


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class GuardrailStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, r: GuardrailRecord) -> GuardrailRecord:
        _put_item(self._table, _convert_floats_to_decimals(r.model_dump(mode="json")))
        return r

    def get(self, guardrail_id: str) -> Optional[GuardrailRecord]:
        item = _get_item(self._table, {"guardrail_id": guardrail_id})
        if not item:
            return None
        return GuardrailRecord.model_validate(_convert_decimals_to_floats(dict(item)))

    def delete(self, guardrail_id: str) -> bool:
        if not self.get(guardrail_id):
            return False
        _delete_item(self._table, {"guardrail_id": guardrail_id})
        return True

    def list_for_user(self, user_id: str) -> list[GuardrailRecord]:
        items = _scan_table(self._table)
        return [
            GuardrailRecord.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in items
            if i.get("user_id") == user_id
        ]


class GuardrailsManager:
    def __init__(self, store: GuardrailStore) -> None:
        self._store = store
        self._bedrock = boto3.client("bedrock", region_name=_region())
        self._bedrock_runtime = boto3.client(
            "bedrock-runtime", region_name=_region()
        )

    def create(
        self, user_id: str, req: GuardrailConfigRequest
    ) -> GuardrailRecord:
        params = self._build_params(req)
        resp = self._bedrock.create_guardrail(**params)
        guardrail_id = resp["guardrailId"]
        arn = resp["guardrailArn"]
        record = GuardrailRecord(
            guardrail_id=guardrail_id,
            user_id=user_id,
            name=req.name,
            description=req.description,
            version=resp.get("version", "DRAFT"),
            arn=arn,
            content_filters_count=len(req.content_filters),
            topic_filters_count=len(req.topic_filters),
            pii_filters_count=len(req.pii_filters),
            word_filters_count=len(req.word_filters),
        )
        return self._store.put(record)

    def update(
        self,
        user_id: str,
        guardrail_id: str,
        req: GuardrailConfigRequest,
    ) -> GuardrailRecord:
        rec = self._store.get(guardrail_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("not found")
        params = self._build_params(req)
        params["guardrailIdentifier"] = guardrail_id
        self._bedrock.update_guardrail(**params)
        rec = rec.model_copy(
            update={
                "name": req.name,
                "description": req.description,
                "content_filters_count": len(req.content_filters),
                "topic_filters_count": len(req.topic_filters),
                "pii_filters_count": len(req.pii_filters),
                "word_filters_count": len(req.word_filters),
            }
        )
        return self._store.put(rec)

    def delete(self, user_id: str, guardrail_id: str) -> bool:
        rec = self._store.get(guardrail_id)
        if rec is None:
            return False
        if rec.user_id != user_id:
            raise PermissionError("not found")
        try:
            self._bedrock.delete_guardrail(guardrailIdentifier=guardrail_id)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                logger.warning("bedrock delete_guardrail failed: %s", e)
        return self._store.delete(guardrail_id)

    def test(
        self, user_id: str, guardrail_id: str, text: str, source: str
    ) -> dict[str, Any]:
        rec = self._store.get(guardrail_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("not found")
        try:
            resp = self._bedrock_runtime.apply_guardrail(
                guardrailIdentifier=guardrail_id,
                guardrailVersion=rec.version,
                source=source,
                content=[{"text": {"text": text}}],
            )
        except ClientError as e:
            raise RuntimeError(f"apply_guardrail: {e}")
        return resp

    # ------------------------------------------------------------------

    def _build_params(self, req: GuardrailConfigRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "name": req.name,
            "description": req.description,
            "blockedInputMessaging": req.blocked_input_message,
            "blockedOutputsMessaging": req.blocked_output_message,
        }
        if req.content_filters:
            params["contentPolicyConfig"] = {
                "filtersConfig": [
                    {
                        "type": f.type.value,
                        "inputStrength": f.input_strength if f.input_strength in FILTER_STRENGTHS else "HIGH",
                        "outputStrength": f.output_strength if f.output_strength in FILTER_STRENGTHS else "HIGH",
                    }
                    for f in req.content_filters
                ]
            }
        if req.topic_filters:
            params["topicPolicyConfig"] = {
                "topicsConfig": [
                    {
                        "name": t.name,
                        "definition": t.definition,
                        "examples": t.examples or [t.definition],
                        "type": "DENY",
                    }
                    for t in req.topic_filters
                ]
            }
        if req.pii_filters:
            params["sensitiveInformationPolicyConfig"] = {
                "piiEntitiesConfig": [
                    {
                        "type": p.type,
                        "action": p.action.value if isinstance(p.action, PiiAction) else p.action,
                    }
                    for p in req.pii_filters
                ]
            }
        if req.word_filters:
            params["wordPolicyConfig"] = {
                "wordsConfig": [{"text": w.text} for w in req.word_filters]
            }
        return params
