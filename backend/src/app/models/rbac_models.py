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
    # AWS Agent Registry personas (mirror of the official tutorial's IAM
    # persona roles: admin / publisher / consumer). The platform admin
    # above plays the admin persona for the registry; these two roles are
    # for non-admin users operating inside the registry scope only.
    REGISTRY_PUBLISHER = "registry_publisher"
    REGISTRY_CONSUMER = "registry_consumer"


# Map Cognito user-pool group names (what the ID token carries in
# ``cognito:groups``) to our internal Role enum. Cognito groups are the
# authoritative source of truth once deployed; the DynamoDB assignment
# table and the env-var seed are fall-backs for bootstrap + local dev.
COGNITO_GROUP_TO_ROLE: dict[str, "Role"] = {
    "platform-admin": Role.PLATFORM_ADMIN,
    "registry-publisher": Role.REGISTRY_PUBLISHER,
    "registry-consumer": Role.REGISTRY_CONSUMER,
}


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
    # AWS Agent Registry — granular permissions mirroring the personas
    # tutorial (admin / publisher / consumer).
    REGISTRY_MANAGE = "registry:manage"  # create/update/delete registry
    REGISTRY_VIEW = "registry:view"  # list/get registry metadata
    REGISTRY_PUBLISH = "registry:publish"  # create/update/delete own records
    REGISTRY_SUBMIT = "registry:submit"  # submit record for approval
    REGISTRY_APPROVE = "registry:approve"  # approve/reject records
    REGISTRY_SEARCH = "registry:search"  # semantic search approved records


ROLE_PERMISSIONS: dict[Role, list[Permission]] = {
    # Admin gets every permission — this covers both the platform admin
    # and the Agent Registry admin-persona role in one.
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
        # Creators can publish their work to the registry too
        Permission.REGISTRY_VIEW,
        Permission.REGISTRY_PUBLISH,
        Permission.REGISTRY_SUBMIT,
        Permission.REGISTRY_SEARCH,
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
        Permission.REGISTRY_VIEW,
        Permission.REGISTRY_SEARCH,
    ],
    Role.AGENT_TESTER: [
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_READ,
        Permission.MARKETPLACE_INSTALL,
        Permission.ANALYTICS_READ,
        Permission.REGISTRY_VIEW,
        Permission.REGISTRY_SEARCH,
    ],
    Role.VIEWER: [
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_READ,
        Permission.ANALYTICS_READ,
    ],
    # AWS Agent Registry personas — scoped to registry actions only.
    Role.REGISTRY_PUBLISHER: [
        Permission.REGISTRY_VIEW,
        Permission.REGISTRY_PUBLISH,
        Permission.REGISTRY_SUBMIT,
        Permission.REGISTRY_SEARCH,
        # Publishers need to see existing deployments and tools so they
        # can pick what to publish; they can't create new ones though.
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_READ,
    ],
    Role.REGISTRY_CONSUMER: [
        Permission.REGISTRY_VIEW,
        Permission.REGISTRY_SEARCH,
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
