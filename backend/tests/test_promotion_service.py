"""Unit tests for environment promotion (Task 07)."""

from __future__ import annotations

from typing import Optional

import pytest

from app.models.environment_models import (
    Environment,
    EnvironmentBinding,
    PromotionRecord,
    PromotionRequest,
    PromotionStatus,
)
from app.models.version_models import AgentVersion
from app.services.promotion_service import (
    EnvironmentBindingStore,
    PromotionService,
    PromotionStore,
)


class InMemoryVersionStore:
    def __init__(self) -> None:
        self.items: dict[tuple[str, int], AgentVersion] = {}

    def put(self, v: AgentVersion) -> AgentVersion:
        self.items[(v.deployment_id, v.version)] = v
        return v

    def get(self, dep: str, version: int) -> Optional[AgentVersion]:
        return self.items.get((dep, version))

    def list_for_deployment(self, dep: str) -> list[AgentVersion]:
        return [v for (d, _), v in self.items.items() if d == dep]

    def update_status(self, dep, version, new_status):
        k = (dep, version)
        if k in self.items:
            self.items[k] = self.items[k].model_copy(update={"status": new_status})


class InMemoryBindingStore:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], EnvironmentBinding] = {}

    def put(self, b: EnvironmentBinding) -> EnvironmentBinding:
        self.items[(b.deployment_id, b.env.value)] = b
        return b

    def get(self, dep: str, env: Environment) -> Optional[EnvironmentBinding]:
        return self.items.get((dep, env.value))

    def list_for_deployment(self, dep: str) -> list[EnvironmentBinding]:
        return [v for (d, _), v in self.items.items() if d == dep]

    def delete(self, dep: str, env: Environment) -> None:
        self.items.pop((dep, env.value), None)


class InMemoryPromoStore:
    def __init__(self) -> None:
        self.items: dict[str, PromotionRecord] = {}

    def put(self, p: PromotionRecord) -> PromotionRecord:
        self.items[p.promotion_id] = p
        return p

    def get(self, pid: str) -> Optional[PromotionRecord]:
        return self.items.get(pid)

    def list_for_deployment(self, dep: str) -> list[PromotionRecord]:
        return [p for p in self.items.values() if p.deployment_id == dep]


@pytest.fixture
def svc() -> PromotionService:
    vs = InMemoryVersionStore()
    # Seed a v1 owned by u1 on d1
    vs.put(
        AgentVersion(
            deployment_id="d1",
            version=1,
            user_id="u1",
            workflow_snapshot={"x": 1},
            system_prompt="hello",
        )
    )
    # Pre-bind dev to v1
    bs = InMemoryBindingStore()
    bs.put(
        EnvironmentBinding(
            deployment_id="d1", env=Environment.DEV, user_id="u1", active_version=1
        )
    )
    return PromotionService(bs, InMemoryPromoStore(), vs)  # type: ignore[arg-type]


def test_promote_dev_to_staging_auto_executes(svc: PromotionService) -> None:
    record = svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.DEV,
            target_env=Environment.STAGING,
            change_description="ready for test",
        ),
    )
    assert record.status == PromotionStatus.COMPLETED
    assert record.target_version is not None
    # Staging binding now points to the new version
    staging = svc._envs.get("d1", Environment.STAGING)
    assert staging is not None
    assert staging.active_version == record.target_version


def test_promote_staging_to_prod_requires_approval(svc: PromotionService) -> None:
    # First promote dev -> staging
    svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.DEV,
            target_env=Environment.STAGING,
            change_description="ready",
        ),
    )
    # Now staging -> prod
    record = svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.STAGING,
            target_env=Environment.PROD,
            change_description="ship it",
        ),
    )
    assert record.status == PromotionStatus.PENDING_APPROVAL
    prod = svc._envs.get("d1", Environment.PROD)
    assert prod is None or prod.active_version is None


def test_approve_prod_promotion(svc: PromotionService) -> None:
    svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.DEV,
            target_env=Environment.STAGING,
            change_description="ok",
        ),
    )
    rec = svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.STAGING,
            target_env=Environment.PROD,
            change_description="ship",
        ),
    )
    approved = svc.approve("u1", rec.promotion_id, "lgtm")
    assert approved.status == PromotionStatus.COMPLETED
    assert approved.approved_by == "u1"


def test_reject_prod_promotion(svc: PromotionService) -> None:
    svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.DEV,
            target_env=Environment.STAGING,
            change_description="ok",
        ),
    )
    rec = svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.STAGING,
            target_env=Environment.PROD,
            change_description="ship",
        ),
    )
    rejected = svc.reject("u1", rec.promotion_id, "regression")
    assert rejected.status == PromotionStatus.REJECTED
    # Prod binding should still be unset
    prod = svc._envs.get("d1", Environment.PROD)
    assert prod is None or prod.active_version is None


def test_invalid_promotion_order(svc: PromotionService) -> None:
    with pytest.raises(ValueError):
        svc.request(
            "u1",
            PromotionRequest(
                deployment_id="d1",
                source_env=Environment.DEV,
                target_env=Environment.PROD,  # skipping staging
                change_description="x",
            ),
        )


def test_cannot_promote_someone_elses_version(svc: PromotionService) -> None:
    # Seed a version owned by u2
    svc._versions.put(  # type: ignore[attr-defined]
        AgentVersion(
            deployment_id="d-other",
            version=1,
            user_id="u2",
            workflow_snapshot={},
        )
    )
    with pytest.raises(PermissionError):
        svc.request(
            "u1",
            PromotionRequest(
                deployment_id="d-other",
                source_env=Environment.DEV,
                target_env=Environment.STAGING,
                change_description="hack",
                source_version=1,
            ),
        )


def test_cannot_approve_nonpending(svc: PromotionService) -> None:
    rec = svc.request(
        "u1",
        PromotionRequest(
            deployment_id="d1",
            source_env=Environment.DEV,
            target_env=Environment.STAGING,
            change_description="ok",
        ),
    )
    # Auto-approved and completed
    assert rec.status == PromotionStatus.COMPLETED
    with pytest.raises(ValueError):
        svc.approve("u1", rec.promotion_id, "")
