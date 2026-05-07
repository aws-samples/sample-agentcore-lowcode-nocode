"""Unit tests for version snapshot/rollback (Task 03)."""

from __future__ import annotations

from typing import Optional

import pytest

from app.models.version_models import AgentVersion, compute_diff
from app.services.version_manager import VersionManager


class InMemoryVersionStore:
    def __init__(self) -> None:
        self.items: dict[tuple[str, int], AgentVersion] = {}

    def put(self, v: AgentVersion) -> AgentVersion:
        self.items[(v.deployment_id, v.version)] = v
        return v

    def get(self, deployment_id: str, version: int) -> Optional[AgentVersion]:
        return self.items.get((deployment_id, version))

    def list_for_deployment(self, deployment_id: str) -> list[AgentVersion]:
        return [v for (d, _), v in self.items.items() if d == deployment_id]

    def update_status(self, deployment_id, version, new_status):
        key = (deployment_id, version)
        if key in self.items:
            v = self.items[key]
            self.items[key] = v.model_copy(update={"status": new_status})


@pytest.fixture
def mgr() -> VersionManager:
    return VersionManager(InMemoryVersionStore())  # type: ignore[arg-type]


def test_snapshot_auto_increments(mgr: VersionManager) -> None:
    v1 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={"nodes": []},
        system_prompt="you are a bot",
    )
    v2 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={"nodes": [{"id": "n1"}]},
        system_prompt="you are a very good bot",
    )
    assert v1.version == 1
    assert v2.version == 2
    assert v2.status == "active"
    # v1 should be archived
    store = mgr._store
    assert store.get("d1", 1).status == "archived"  # type: ignore[union-attr]


def test_snapshot_computes_code_hash(mgr: VersionManager) -> None:
    v = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={},
        agent_code="print('hello')",
    )
    assert v.agent_code_hash is not None
    assert len(v.agent_code_hash) == 64


def test_diff_detects_prompt_change(mgr: VersionManager) -> None:
    v1 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={},
        system_prompt="old",
    )
    v2 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={},
        system_prompt="new",
    )
    _, _, changes = mgr.diff("d1", v1.version, v2.version)
    fields = {c["field"] for c in changes}
    assert "system_prompt" in fields


def test_diff_unchanged(mgr: VersionManager) -> None:
    v1 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={},
        system_prompt="same",
        tools_config=[{"name": "search"}],
    )
    v2 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={},
        system_prompt="same",
        tools_config=[{"name": "search"}],
    )
    _, _, changes = mgr.diff("d1", v1.version, v2.version)
    assert changes == []


def test_rollback_creates_new_version(mgr: VersionManager) -> None:
    v1 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={"x": 1},
        system_prompt="original",
    )
    v2 = mgr.snapshot(
        deployment_id="d1",
        user_id="u1",
        workflow_snapshot={"x": 2},
        system_prompt="broken",
    )
    r = mgr.rollback("d1", v1.version, reason="regression", actor_user_id="u1")
    assert r.new_version == 3
    assert r.restored_from_version == 1
    new = mgr._store.get("d1", r.new_version)  # type: ignore[union-attr]
    assert new.workflow_snapshot == {"x": 1}
    assert new.system_prompt == "original"
    assert new.status == "active"
    # v2 should be rolled-back
    assert mgr._store.get("d1", v2.version).status == "rolled-back"  # type: ignore[union-attr]


def test_rollback_missing_version(mgr: VersionManager) -> None:
    mgr.snapshot(deployment_id="d1", user_id="u1", workflow_snapshot={})
    with pytest.raises(ValueError):
        mgr.rollback("d1", 99, reason="x", actor_user_id="u1")


def test_compute_diff_json_fields() -> None:
    a = AgentVersion(
        deployment_id="d1",
        version=1,
        user_id="u1",
        tools_config=[{"name": "a"}, {"name": "b"}],
    )
    b = AgentVersion(
        deployment_id="d1",
        version=2,
        user_id="u1",
        tools_config=[{"name": "a"}, {"name": "c"}],
    )
    diff = compute_diff(a, b)
    assert any(c["field"] == "tools_config" for c in diff)
