"""Version snapshot/rollback business logic (Task 03)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.version_models import (
    AgentVersion,
    RollbackResult,
    compute_diff,
)
from app.services.version_store import VersionStore

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VersionManager:
    def __init__(self, store: VersionStore) -> None:
        self._store = store

    def snapshot(
        self,
        *,
        deployment_id: str,
        user_id: str,
        workflow_snapshot: dict[str, Any],
        agent_code: Optional[str] = None,
        model_config_snapshot: Optional[dict[str, Any]] = None,
        tools_config: Optional[list[dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        memory_config: Optional[dict[str, Any]] = None,
        policy_config: Optional[dict[str, Any]] = None,
        guardrails_config: Optional[dict[str, Any]] = None,
        knowledge_base_config: Optional[dict[str, Any]] = None,
        runtime_arn: Optional[str] = None,
        runtime_id: Optional[str] = None,
        change_description: str = "",
        deployed_by: Optional[str] = None,
    ) -> AgentVersion:
        """Create a new version snapshot.

        Sets prior active version to 'archived' (one active per deployment).
        """
        prior = self._store.list_for_deployment(deployment_id)
        for p in prior:
            if p.status == "active":
                try:
                    self._store.update_status(deployment_id, p.version, "archived")
                except Exception as e:
                    logger.warning("failed to archive prior version: %s", e)
        next_version = max((p.version for p in prior), default=0) + 1
        agent_code_hash = AgentVersion.compute_hash(agent_code)
        v = AgentVersion(
            deployment_id=deployment_id,
            version=next_version,
            user_id=user_id,
            workflow_snapshot=workflow_snapshot,
            agent_code=agent_code,
            agent_code_hash=agent_code_hash,
            model_config_snapshot=model_config_snapshot or {},
            tools_config=tools_config or [],
            system_prompt=system_prompt,
            memory_config=memory_config,
            policy_config=policy_config,
            guardrails_config=guardrails_config,
            knowledge_base_config=knowledge_base_config,
            runtime_arn=runtime_arn,
            runtime_id=runtime_id,
            change_description=change_description,
            deployed_by=deployed_by or user_id,
            deployed_at=_now(),
            status="active",
        )
        return self._store.put(v)

    def diff(
        self, deployment_id: str, from_version: int, to_version: int
    ) -> tuple[AgentVersion, AgentVersion, list[dict[str, Any]]]:
        a = self._store.get(deployment_id, from_version)
        b = self._store.get(deployment_id, to_version)
        if a is None or b is None:
            raise ValueError("version not found")
        return a, b, compute_diff(a, b)

    def rollback(
        self,
        deployment_id: str,
        target_version: int,
        reason: str,
        actor_user_id: str,
    ) -> RollbackResult:
        """Create a new version whose content is identical to `target_version`.

        The resulting snapshot becomes the new 'active' version. The frontend
        is expected to re-run the deploy with `workflow_snapshot` to actually
        re-provision infrastructure. This is documented behaviour.
        """
        target = self._store.get(deployment_id, target_version)
        if target is None:
            raise ValueError(f"version {target_version} not found")
        existing = self._store.list_for_deployment(deployment_id)
        next_version = max((v.version for v in existing), default=0) + 1
        # Archive any active
        for p in existing:
            if p.status == "active":
                try:
                    self._store.update_status(deployment_id, p.version, "rolled-back")
                except Exception:
                    pass
        new_version = AgentVersion(
            deployment_id=deployment_id,
            version=next_version,
            user_id=target.user_id,
            workflow_snapshot=target.workflow_snapshot,
            agent_code=target.agent_code,
            agent_code_hash=target.agent_code_hash,
            model_config_snapshot=target.model_config_snapshot,
            tools_config=target.tools_config,
            system_prompt=target.system_prompt,
            memory_config=target.memory_config,
            policy_config=target.policy_config,
            guardrails_config=target.guardrails_config,
            knowledge_base_config=target.knowledge_base_config,
            runtime_arn=target.runtime_arn,
            runtime_id=target.runtime_id,
            change_description=(
                f"Rollback to v{target_version}: {reason}"
            ),
            deployed_by=actor_user_id,
            deployed_at=_now(),
            status="active",
        )
        self._store.put(new_version)
        return RollbackResult(
            deployment_id=deployment_id,
            new_version=new_version.version,
            restored_from_version=target_version,
            workflow_snapshot=target.workflow_snapshot,
        )
