"""AgentCore Harness lifecycle management (Task 11).

Wraps the real ``bedrock-agentcore-control:*Harness*`` API surface:
  - create_harness (idempotent via name-based lookup)
  - get_harness (polling)
  - list_harnesses
  - update_harness
  - delete_harness

Tenant isolation: AWS's CreateHarness has no user dimension. We mirror
ownership in the HarnessTable (PK=harness_id) and enforce it at the
router layer. AWS tags include ``owner`` so we can cross-check.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.harness_models import (
    HarnessCreateRequest,
    HarnessRecord,
    HarnessStatus,
    ModelProvider,
    TERMINAL_HARNESS_STATUSES,
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

POLL_ATTEMPTS = 24  # 24 * 5s = 2 min budget
POLL_INTERVAL = 5.0


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _control_client() -> Any:
    return boto3.client("bedrock-agentcore-control", region_name=_region())


class HarnessStore:
    """Ownership mapping for harnesses (PK harness_id)."""

    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, r: HarnessRecord) -> HarnessRecord:
        _put_item(self._table, _convert_floats_to_decimals(r.model_dump(mode="json")))
        return r

    def get(self, harness_id: str) -> Optional[HarnessRecord]:
        item = _get_item(self._table, {"harness_id": harness_id})
        if not item:
            return None
        return HarnessRecord.model_validate(_convert_decimals_to_floats(dict(item)))

    def delete(self, harness_id: str) -> None:
        _delete_item(self._table, {"harness_id": harness_id})

    def list_for_user(self, user_id: str) -> list[HarnessRecord]:
        items = _scan_table(self._table)
        return sorted(
            [
                HarnessRecord.model_validate(_convert_decimals_to_floats(dict(i)))
                for i in items
                if i.get("user_id") == user_id
            ],
            key=lambda r: r.created_at,
            reverse=True,
        )


class HarnessDeployer:
    def __init__(self, store: HarnessStore) -> None:
        self._store = store
        self._client = _control_client()

    # ------------------------------------------------------------------
    # Build request
    # ------------------------------------------------------------------

    def _build_create_params(
        self, req: HarnessCreateRequest, *, execution_role_arn: str, user_id: str
    ) -> dict[str, Any]:
        """Build the CreateHarness params.

        Shape verified live against boto3 1.43.6 ``CreateHarness`` input
        model in us-east-1. Top-level fields AWS accepts today:
          harnessName, clientToken, executionRoleArn, environment,
          environmentVariables, authorizerConfiguration, model, systemPrompt,
          tools, skills, allowedTools, memory, truncation, maxIterations,
          maxTokens, timeoutSeconds, tags.

        Fields we accept at the API surface but cannot forward to AWS yet
        (they appear in AWS documentation but are not in the current SDK
        model): ``description``, ``guardrail``, ``knowledge_base``,
        ``observability``, Bedrock ``top_k``, Bedrock ``stop_sequences``.
        We still capture ``description`` locally in HarnessRecord for UI
        purposes; the rest are accepted-but-ignored with a warning.
        """
        params: dict[str, Any] = {
            "harnessName": req.harness_name,
            "executionRoleArn": execution_role_arn,
            "model": req.model.to_api(),
        }
        if req.system_prompt:
            params["systemPrompt"] = [{"text": req.system_prompt}]
        if req.tools:
            params["tools"] = [t.to_api() for t in req.tools]
        if req.allowed_tools:
            params["allowedTools"] = req.allowed_tools
        if req.skills:
            params["skills"] = [{"skillArn": s} for s in req.skills]
        if req.memory:
            params["memory"] = req.memory.to_api()
        if req.truncation:
            params["truncation"] = req.truncation.to_api()
        if req.max_iterations is not None:
            params["maxIterations"] = req.max_iterations
        if req.max_tokens is not None:
            params["maxTokens"] = req.max_tokens
        if req.timeout_seconds is not None:
            params["timeoutSeconds"] = req.timeout_seconds
        # Warn the caller when they requested a feature the SDK doesn't support
        # yet so the UI surfaces why it wasn't applied.
        for unsupported, present in (
            ("guardrail", bool(req.guardrail)),
            ("knowledge_base", bool(req.knowledge_base)),
            ("observability", bool(req.observability)),
        ):
            if present:
                logger.warning(
                    "Harness field %r is accepted at the API but not yet "
                    "supported by boto3 bedrock-agentcore-control CreateHarness; "
                    "dropping from the call.",
                    unsupported,
                )
        # Environment (network mode is required within agentCoreRuntimeEnvironment)
        env: dict[str, Any] = {"networkConfiguration": {"networkMode": req.network_mode}}
        if req.network_mode == "VPC":
            if not req.security_group_ids or not req.subnet_ids:
                raise ValueError("VPC network_mode requires security_group_ids and subnet_ids")
            env["networkConfiguration"]["networkModeConfig"] = {
                "securityGroups": req.security_group_ids,
                "subnets": req.subnet_ids,
            }
        if req.lifecycle:
            env["lifecycleConfiguration"] = req.lifecycle.to_api()
        params["environment"] = {"agentCoreRuntimeEnvironment": env}
        # Tags (owner tag for cross-check)
        tags = {"owner": user_id, **{k: v for k, v in req.tags.items() if k != "owner"}}
        params["tags"] = tags
        return params

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        user_id: str,
        req: HarnessCreateRequest,
        execution_role_arn: str,
    ) -> HarnessRecord:
        params = self._build_create_params(
            req, execution_role_arn=execution_role_arn, user_id=user_id
        )
        # Deterministic clientToken keyed by user+name lets retries be idempotent.
        # AWS validates against [a-zA-Z0-9](-*[a-zA-Z0-9]){0,256} — so we use a
        # SHA-256 hex digest (alphanumeric) of the stable key.
        import hashlib as _hashlib

        token_seed = f"{user_id}/{req.harness_name}".encode()
        params["clientToken"] = _hashlib.sha256(token_seed).hexdigest()[:64]

        try:
            resp = self._client.create_harness(**params)
            harness = resp.get("harness") or resp
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ConflictException":
                # Name already taken — find it
                existing = self._find_by_name(req.harness_name)
                if existing is None:
                    raise
                harness = existing
            else:
                raise

        harness_id = harness.get("harnessId") or harness.get("id") or f"h-{uuid.uuid4().hex[:12]}"
        provider = self._provider_of(req)
        model_id = (
            (req.model.bedrock and req.model.bedrock.model_id)
            or (req.model.openai and req.model.openai.model_id)
            or (req.model.gemini and req.model.gemini.model_id)
            or ""
        )
        runtime_arn, runtime_id = self._extract_runtime_ids(harness)
        rec = HarnessRecord(
            harness_id=harness_id,
            user_id=user_id,
            name=req.harness_name,
            description=req.description,
            arn=harness.get("arn") or harness.get("harnessArn") or "",
            status=HarnessStatus(harness.get("status", HarnessStatus.CREATING.value)),
            model_provider=provider,
            model_id=model_id,
            agent_runtime_arn=runtime_arn,
            agent_runtime_id=runtime_id,
        )
        return self._store.put(rec)

    @staticmethod
    def _provider_of(req: HarnessCreateRequest) -> ModelProvider:
        if req.model.bedrock:
            return ModelProvider.BEDROCK
        if req.model.openai:
            return ModelProvider.OPENAI
        if req.model.gemini:
            return ModelProvider.GEMINI
        raise ValueError("no model provider specified")

    @staticmethod
    def _extract_runtime_ids(harness: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        env = harness.get("environment") or {}
        rt = env.get("agentCoreRuntimeEnvironment") or {}
        return rt.get("agentRuntimeArn"), rt.get("agentRuntimeId")

    def _find_by_name(self, name: str) -> Optional[dict[str, Any]]:
        try:
            resp = self._client.list_harnesses(maxResults=100)
            for h in resp.get("harnesses", []):
                if h.get("harnessName") == name or h.get("name") == name:
                    return h
        except ClientError as e:
            logger.warning("list_harnesses failed during conflict resolve: %s", e)
        return None

    # ------------------------------------------------------------------
    # Poll until terminal
    # ------------------------------------------------------------------

    def poll_until_terminal(
        self, harness_id: str, attempts: int = POLL_ATTEMPTS
    ) -> HarnessRecord:
        rec = self._store.get(harness_id)
        if rec is None:
            raise ValueError("harness not found")
        for _ in range(attempts):
            aws = self._get_aws(harness_id)
            if aws is None:
                rec.status = HarnessStatus.DELETE_FAILED
                rec.failure_reason = "Harness missing on AWS"
                self._store.put(rec)
                return rec
            status_str = aws.get("status", "CREATING")
            try:
                rec.status = HarnessStatus(status_str)
            except ValueError:
                # Unknown status: don't treat as terminal
                logger.warning("unknown harness status %s — continuing to poll", status_str)
                rec.status = HarnessStatus.CREATING
            rec.failure_reason = aws.get("failureReason")
            rec.updated_at = datetime.now(timezone.utc).isoformat()
            rt_arn, rt_id = self._extract_runtime_ids(aws)
            if rt_arn:
                rec.agent_runtime_arn = rt_arn
            if rt_id:
                rec.agent_runtime_id = rt_id
            self._store.put(rec)
            if rec.status in TERMINAL_HARNESS_STATUSES:
                return rec
            time.sleep(POLL_INTERVAL)
        return rec  # Timeout — caller can see rec.status is non-terminal

    # ------------------------------------------------------------------
    # Get / Delete
    # ------------------------------------------------------------------

    def _get_aws(self, harness_id: str) -> Optional[dict[str, Any]]:
        try:
            resp = self._client.get_harness(harnessId=harness_id)
            return resp.get("harness") or resp
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ResourceNotFoundException":
                return None
            raise

    def refresh(self, rec: HarnessRecord) -> HarnessRecord:
        aws = self._get_aws(rec.harness_id)
        if aws is None:
            rec.status = HarnessStatus.DELETE_FAILED
            return self._store.put(rec)
        try:
            rec.status = HarnessStatus(aws.get("status", rec.status.value))
        except ValueError:
            pass
        rec.failure_reason = aws.get("failureReason")
        rt_arn, rt_id = self._extract_runtime_ids(aws)
        if rt_arn:
            rec.agent_runtime_arn = rt_arn
        if rt_id:
            rec.agent_runtime_id = rt_id
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        return self._store.put(rec)

    def delete(self, rec: HarnessRecord) -> None:
        try:
            self._client.delete_harness(harnessId=rec.harness_id)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code != "ResourceNotFoundException":
                logger.warning("delete_harness failed: %s", e)
        self._store.delete(rec.harness_id)
