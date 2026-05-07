"""Environment promotion service (Task 07).

Manages logical dev/staging/prod environments and audits promotions
between them. Promotion execution re-uses the version snapshot primitive
from Task 03 — target env gets a new snapshot whose content is the
source env's active version.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models.environment_models import (
    NEXT_ENVIRONMENT,
    Environment,
    EnvironmentBinding,
    PromotionRecord,
    PromotionRequest,
    PromotionStatus,
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
from app.services.version_manager import VersionManager
from app.services.version_store import VersionStore

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


class EnvironmentBindingStore:
    """Stores (deployment_id, env) -> active_version mappings."""

    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    @staticmethod
    def _key(deployment_id: str, env: Environment) -> dict:
        return {"deployment_id": deployment_id, "env": env.value}

    def put(self, b: EnvironmentBinding) -> EnvironmentBinding:
        _put_item(self._table, _convert_floats_to_decimals(b.model_dump(mode="json")))
        return b

    def get(self, deployment_id: str, env: Environment) -> Optional[EnvironmentBinding]:
        item = _get_item(self._table, self._key(deployment_id, env))
        if not item:
            return None
        return EnvironmentBinding.model_validate(_convert_decimals_to_floats(dict(item)))

    def list_for_deployment(self, deployment_id: str) -> list[EnvironmentBinding]:
        resp = self._table.query(
            KeyConditionExpression="deployment_id = :d",
            ExpressionAttributeValues={":d": deployment_id},
        )
        return [
            EnvironmentBinding.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in resp.get("Items", [])
        ]

    def delete(self, deployment_id: str, env: Environment) -> None:
        _delete_item(self._table, self._key(deployment_id, env))


class PromotionStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, p: PromotionRecord) -> PromotionRecord:
        _put_item(self._table, _convert_floats_to_decimals(p.model_dump(mode="json")))
        return p

    def get(self, promotion_id: str) -> Optional[PromotionRecord]:
        item = _get_item(self._table, {"promotion_id": promotion_id})
        if not item:
            return None
        return PromotionRecord.model_validate(_convert_decimals_to_floats(dict(item)))

    def list_for_deployment(self, deployment_id: str) -> list[PromotionRecord]:
        items = _scan_table(self._table)
        out = [
            PromotionRecord.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in items
            if i.get("deployment_id") == deployment_id
        ]
        return sorted(out, key=lambda p: p.requested_at, reverse=True)


class PromotionService:
    def __init__(
        self,
        env_store: EnvironmentBindingStore,
        promo_store: PromotionStore,
        version_store: VersionStore,
    ) -> None:
        self._envs = env_store
        self._promos = promo_store
        self._versions = version_store

    def ensure_binding(
        self, deployment_id: str, env: Environment, user_id: str
    ) -> EnvironmentBinding:
        existing = self._envs.get(deployment_id, env)
        if existing:
            return existing
        binding = EnvironmentBinding(
            deployment_id=deployment_id,
            env=env,
            user_id=user_id,
            active_version=None,
        )
        return self._envs.put(binding)

    def list_bindings(self, deployment_id: str) -> list[EnvironmentBinding]:
        return self._envs.list_for_deployment(deployment_id)

    def update_overrides(
        self,
        deployment_id: str,
        env: Environment,
        overrides: dict,
        user_id: str,
    ) -> EnvironmentBinding:
        binding = self._envs.get(deployment_id, env)
        if binding is None:
            binding = self.ensure_binding(deployment_id, env, user_id)
        if binding.user_id != user_id:
            raise PermissionError("not your deployment")
        binding.config_overrides = overrides
        binding.updated_at = _now()
        return self._envs.put(binding)

    # ------------------------------------------------------------------
    # Promotion lifecycle
    # ------------------------------------------------------------------

    def request(
        self, user_id: str, req: PromotionRequest
    ) -> PromotionRecord:
        if NEXT_ENVIRONMENT.get(req.source_env) != req.target_env:
            raise ValueError(
                f"cannot promote {req.source_env.value} -> {req.target_env.value}"
            )
        # Resolve source version
        source_binding = self._envs.get(req.deployment_id, req.source_env)
        if req.source_version is not None:
            source_version = req.source_version
        elif source_binding and source_binding.active_version is not None:
            source_version = source_binding.active_version
        else:
            raise ValueError(
                f"no active version on {req.source_env.value}; specify source_version"
            )
        # Verify source version exists and caller owns it
        source = self._versions.get(req.deployment_id, source_version)
        if source is None:
            raise ValueError(f"version {source_version} not found")
        if source.user_id != user_id:
            raise PermissionError("not your deployment")
        # Ensure source binding exists (auto-create at first promotion)
        if source_binding is None:
            source_binding = EnvironmentBinding(
                deployment_id=req.deployment_id,
                env=req.source_env,
                user_id=user_id,
                active_version=source_version,
            )
            self._envs.put(source_binding)
        record = PromotionRecord(
            promotion_id=f"pr-{uuid.uuid4().hex[:16]}",
            deployment_id=req.deployment_id,
            user_id=user_id,
            source_env=req.source_env,
            target_env=req.target_env,
            source_version=source_version,
            status=PromotionStatus.PENDING_APPROVAL
            if req.target_env == Environment.PROD
            else PromotionStatus.APPROVED,
            change_description=req.change_description,
            requested_by=user_id,
        )
        self._promos.put(record)
        if record.status == PromotionStatus.APPROVED:
            record = self._execute(record)
        return record

    def approve(
        self, user_id: str, promotion_id: str, comment: str = ""
    ) -> PromotionRecord:
        record = self._promos.get(promotion_id)
        if record is None or record.user_id != user_id:
            raise PermissionError("not found")
        if record.status != PromotionStatus.PENDING_APPROVAL:
            raise ValueError(f"cannot approve: status is {record.status.value}")
        record.status = PromotionStatus.APPROVED
        record.approved_by = user_id
        record.approved_at = _now()
        self._promos.put(record)
        return self._execute(record)

    def reject(
        self, user_id: str, promotion_id: str, reason: str
    ) -> PromotionRecord:
        record = self._promos.get(promotion_id)
        if record is None or record.user_id != user_id:
            raise PermissionError("not found")
        if record.status != PromotionStatus.PENDING_APPROVAL:
            raise ValueError(f"cannot reject: status is {record.status.value}")
        record.status = PromotionStatus.REJECTED
        record.rejected_by = user_id
        record.rejected_at = _now()
        record.rejection_reason = reason
        self._promos.put(record)
        return record

    def list_for_deployment(self, deployment_id: str) -> list[PromotionRecord]:
        return self._promos.list_for_deployment(deployment_id)

    def get(self, promotion_id: str) -> Optional[PromotionRecord]:
        return self._promos.get(promotion_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute(self, record: PromotionRecord) -> PromotionRecord:
        record.status = PromotionStatus.PROMOTING
        self._promos.put(record)
        try:
            source = self._versions.get(record.deployment_id, record.source_version)
            if source is None:
                raise RuntimeError("source version disappeared")
            mgr = VersionManager(self._versions)
            new_version = mgr.snapshot(
                deployment_id=record.deployment_id,
                user_id=record.user_id,
                workflow_snapshot=source.workflow_snapshot,
                agent_code=source.agent_code,
                model_config_snapshot=source.model_config_snapshot,
                tools_config=source.tools_config,
                system_prompt=source.system_prompt,
                memory_config=source.memory_config,
                policy_config=source.policy_config,
                guardrails_config=source.guardrails_config,
                knowledge_base_config=source.knowledge_base_config,
                runtime_arn=source.runtime_arn,
                runtime_id=source.runtime_id,
                change_description=(
                    f"Promoted from {record.source_env.value} v{record.source_version}"
                    f" to {record.target_env.value}: {record.change_description}"
                ),
                deployed_by=record.user_id,
            )
            # Update target env binding
            binding = self._envs.get(record.deployment_id, record.target_env)
            if binding is None:
                binding = EnvironmentBinding(
                    deployment_id=record.deployment_id,
                    env=record.target_env,
                    user_id=record.user_id,
                    active_version=new_version.version,
                )
            else:
                binding.active_version = new_version.version
                binding.updated_at = _now()
            self._envs.put(binding)
            record.status = PromotionStatus.COMPLETED
            record.target_version = new_version.version
            record.completed_at = _now()
        except Exception as e:  # noqa: BLE001
            logger.exception("promotion %s failed", record.promotion_id)
            record.status = PromotionStatus.FAILED
            record.error = str(e)[:512]
        self._promos.put(record)
        return record
