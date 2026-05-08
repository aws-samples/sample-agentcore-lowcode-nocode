"""RBAC models and role-permission map (Task 10)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Role(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    AGENT_CREATOR = "agent_creator"
    AGENT_OPERATOR = "agent_operator"
    AGENT_TESTER = "agent_tester"
    VIEWER = "viewer"


class Permission(str, Enum):
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"
    DEPLOYMENT_CREATE = "deployment:create"
    DEPLOYMENT_READ = "deployment:read"
    DEPLOYMENT_DELETE = "deployment:delete"
    DEPLOYMENT_ROLLBACK = "deployment:rollback"
    TRIGGER_CREATE = "trigger:create"
    TRIGGER_READ = "trigger:read"
    TRIGGER_DELETE = "trigger:delete"
    APPROVAL_APPROVE = "approval:approve"
    APPROVAL_REJECT = "approval:reject"
    MARKETPLACE_PUBLISH = "marketplace:publish"
    MARKETPLACE_INSTALL = "marketplace:install"
    MARKETPLACE_APPROVE = "marketplace:approve"
    ANALYTICS_READ = "analytics:read"
    ADMIN_MANAGE_USERS = "admin:manage-users"
    ADMIN_MANAGE_ROLES = "admin:manage-roles"
    ADMIN_VIEW_AUDIT = "admin:view-audit"
    ADMIN_MANAGE_DLP = "admin:manage-dlp"


ROLE_PERMISSIONS: dict[Role, list[Permission]] = {
    Role.PLATFORM_ADMIN: list(Permission),
    Role.AGENT_CREATOR: [
        Permission.WORKFLOW_CREATE,
        Permission.WORKFLOW_READ,
        Permission.WORKFLOW_UPDATE,
        Permission.WORKFLOW_DELETE,
        Permission.DEPLOYMENT_CREATE,
        Permission.DEPLOYMENT_READ,
        Permission.DEPLOYMENT_DELETE,
        Permission.DEPLOYMENT_ROLLBACK,
        Permission.TRIGGER_CREATE,
        Permission.TRIGGER_READ,
        Permission.TRIGGER_DELETE,
        Permission.APPROVAL_APPROVE,
        Permission.APPROVAL_REJECT,
        Permission.MARKETPLACE_PUBLISH,
        Permission.MARKETPLACE_INSTALL,
        Permission.ANALYTICS_READ,
    ],
    Role.AGENT_OPERATOR: [
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_CREATE,
        Permission.DEPLOYMENT_READ,
        Permission.DEPLOYMENT_DELETE,
        Permission.DEPLOYMENT_ROLLBACK,
        Permission.TRIGGER_CREATE,
        Permission.TRIGGER_READ,
        Permission.TRIGGER_DELETE,
        Permission.APPROVAL_APPROVE,
        Permission.APPROVAL_REJECT,
        Permission.MARKETPLACE_INSTALL,
        Permission.ANALYTICS_READ,
    ],
    Role.AGENT_TESTER: [
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_READ,
        Permission.MARKETPLACE_INSTALL,
        Permission.ANALYTICS_READ,
    ],
    Role.VIEWER: [
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_READ,
        Permission.ANALYTICS_READ,
    ],
}


def role_has_permission(role: Role, permission: Permission) -> bool:
    if role == Role.PLATFORM_ADMIN:
        return True
    return permission in ROLE_PERMISSIONS.get(role, [])


class UserRoleAssignment(BaseModel):
    user_id: str
    email: str = ""
    role: Role
    assigned_by: str = ""
    assigned_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class AssignRoleRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    role: Role


class UserRoleListResponse(BaseModel):
    users: list[UserRoleAssignment]


class UserRoleResponse(BaseModel):
    user: UserRoleAssignment


class MeResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    role: Role
    permissions: list[Permission]
