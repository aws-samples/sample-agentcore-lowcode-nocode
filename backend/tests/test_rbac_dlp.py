"""RBAC + DLP unit tests (Task 10)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.rbac_models import (
    Permission,
    Role,
    role_has_permission,
    ROLE_PERMISSIONS,
)
from app.services.dlp_service import DlpService


def test_platform_admin_has_all_permissions() -> None:
    for p in Permission:
        assert role_has_permission(Role.PLATFORM_ADMIN, p)


def test_viewer_read_only() -> None:
    assert role_has_permission(Role.VIEWER, Permission.WORKFLOW_READ)
    assert not role_has_permission(Role.VIEWER, Permission.WORKFLOW_CREATE)
    assert not role_has_permission(Role.VIEWER, Permission.WORKFLOW_DELETE)
    assert not role_has_permission(Role.VIEWER, Permission.ADMIN_MANAGE_USERS)


def test_agent_creator_can_create_but_not_admin() -> None:
    assert role_has_permission(Role.AGENT_CREATOR, Permission.WORKFLOW_CREATE)
    assert role_has_permission(Role.AGENT_CREATOR, Permission.DEPLOYMENT_ROLLBACK)
    assert role_has_permission(Role.AGENT_CREATOR, Permission.MARKETPLACE_PUBLISH)
    assert not role_has_permission(Role.AGENT_CREATOR, Permission.ADMIN_MANAGE_USERS)
    assert not role_has_permission(Role.AGENT_CREATOR, Permission.ADMIN_VIEW_AUDIT)
    assert not role_has_permission(Role.AGENT_CREATOR, Permission.MARKETPLACE_APPROVE)


def test_agent_operator_cannot_create_workflow() -> None:
    assert not role_has_permission(Role.AGENT_OPERATOR, Permission.WORKFLOW_CREATE)
    assert role_has_permission(Role.AGENT_OPERATOR, Permission.DEPLOYMENT_CREATE)


def test_role_permission_map_defined_for_all_roles() -> None:
    # Every non-admin role should have at least WORKFLOW_READ
    for role in [Role.AGENT_CREATOR, Role.AGENT_OPERATOR, Role.AGENT_TESTER, Role.VIEWER]:
        assert Permission.WORKFLOW_READ in ROLE_PERMISSIONS[role]


# ---------------------------------------------------------------------------
# DLP
# ---------------------------------------------------------------------------


@pytest.fixture
def dlp() -> DlpService:
    # Disable comprehend by default in unit tests
    return DlpService(policy_store=None, use_comprehend=False)


def test_dlp_regex_detects_ssn(dlp: DlpService) -> None:
    result = dlp.scan("my ssn is 123-45-6789")
    assert "SSN" in result.matched_types


def test_dlp_regex_detects_email(dlp: DlpService) -> None:
    result = dlp.scan("ping me at foo@example.com")
    assert "EMAIL" in result.matched_types


def test_dlp_regex_detects_credit_card(dlp: DlpService) -> None:
    result = dlp.scan("card 4532-1234-5678-9010")
    assert "CREDIT_CARD" in result.matched_types


def test_dlp_regex_detects_aws_key(dlp: DlpService) -> None:
    result = dlp.scan("AKIAIOSFODNN7EXAMPLE is the key")
    assert "AWS_ACCESS_KEY" in result.matched_types


def test_dlp_mask_action(dlp: DlpService) -> None:
    result = dlp.scan("ssn 111-22-3333 email a@b.com", action="mask")
    assert result.action == "masked"
    assert "111-22-3333" not in (result.masked_text or "")
    assert "[REDACTED-SSN]" in (result.masked_text or "")
    assert "[REDACTED-EMAIL]" in (result.masked_text or "")


def test_dlp_block_action_with_match(dlp: DlpService) -> None:
    result = dlp.scan("ssn 111-22-3333", action="block")
    assert result.action == "blocked"
    assert result.masked_text is None


def test_dlp_none_action_passes_through(dlp: DlpService) -> None:
    result = dlp.scan("ssn 111-22-3333", action="none")
    assert result.action == "none"
    assert result.match_count == 1


def test_dlp_safe_text_no_matches(dlp: DlpService) -> None:
    result = dlp.scan("hello world, just a friendly message")
    assert result.match_count == 0
    assert result.action == "none"
    assert result.matched_types == []
