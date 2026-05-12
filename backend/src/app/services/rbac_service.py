"""RBAC service: resolve user roles + enforce permissions (Task 10)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from app.models.rbac_models import (
    COGNITO_GROUP_TO_ROLE,
    Permission,
    Role,
    ROLE_PERMISSIONS,
    UserRoleAssignment,
    role_has_permission,
)
from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _get_dynamodb_resource,
    _get_item,
    _get_table,
    _put_item,
    _scan_table,
)
from app.shared.auth import get_user_email, get_user_groups, require_user

logger = logging.getLogger(__name__)


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _default_role() -> Role:
    """Role assigned to users with no explicit binding."""
    raw = os.environ.get("RBAC_DEFAULT_ROLE", Role.AGENT_CREATOR.value)
    try:
        return Role(raw)
    except ValueError:
        return Role.AGENT_CREATOR


def _platform_admin_ids() -> set[str]:
    raw = os.environ.get("RBAC_PLATFORM_ADMIN_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


class RbacStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, a: UserRoleAssignment) -> UserRoleAssignment:
        _put_item(self._table, _convert_floats_to_decimals(a.model_dump(mode="json")))
        return a

    def get(self, user_id: str) -> Optional[UserRoleAssignment]:
        item = _get_item(self._table, {"user_id": user_id})
        if not item:
            return None
        return UserRoleAssignment.model_validate(_convert_decimals_to_floats(dict(item)))

    def list(self) -> list[UserRoleAssignment]:
        return [
            UserRoleAssignment.model_validate(_convert_decimals_to_floats(dict(i)))
            for i in _scan_table(self._table)
        ]


def _role_from_groups(groups: list[str]) -> Optional[Role]:
    """Pick the highest-privilege Role implied by a caller's Cognito groups.

    Priority order: platform-admin > registry-publisher > registry-consumer
    so that a user who is (somehow) in multiple groups lands on the role
    with the broadest permission set.
    """
    ordered = [Role.PLATFORM_ADMIN, Role.REGISTRY_PUBLISHER, Role.REGISTRY_CONSUMER]
    mapped = {COGNITO_GROUP_TO_ROLE[g] for g in groups if g in COGNITO_GROUP_TO_ROLE}
    for r in ordered:
        if r in mapped:
            return r
    return None


class RbacService:
    def __init__(self, store: RbacStore) -> None:
        self._store = store

    def resolve_role(
        self, user_id: str, groups: Optional[list[str]] = None
    ) -> Role:
        """Resolve the caller's Role.

        Priority:
          1. Cognito user-pool group membership (source of truth once
             deployed — see ``COGNITO_GROUP_TO_ROLE``)
          2. ``RBAC_PLATFORM_ADMIN_IDS`` env-var seed (bootstrap)
          3. DynamoDB RBAC table entry (admin-assigned)
          4. ``RBAC_DEFAULT_ROLE`` env var or ``AGENT_CREATOR`` fallback
        """
        if groups:
            r = _role_from_groups(groups)
            if r is not None:
                return r
        if user_id in _platform_admin_ids():
            return Role.PLATFORM_ADMIN
        rec = self._store.get(user_id)
        return rec.role if rec else _default_role()

    def effective_permissions(self, role: Role) -> list[Permission]:
        return list(ROLE_PERMISSIONS.get(role, []))

    def has(
        self,
        user_id: str,
        permission: Permission,
        groups: Optional[list[str]] = None,
    ) -> bool:
        return role_has_permission(
            self.resolve_role(user_id, groups=groups), permission
        )

    def assign(
        self,
        admin_user_id: str,
        user_id: str,
        role: Role,
        email: str = "",
        groups: Optional[list[str]] = None,
    ) -> UserRoleAssignment:
        if not self.has(
            admin_user_id, Permission.ADMIN_MANAGE_ROLES, groups=groups
        ):
            raise PermissionError("insufficient permission")
        existing = self._store.get(user_id)
        rec = UserRoleAssignment(
            user_id=user_id,
            email=email or (existing.email if existing else ""),
            role=role,
            assigned_by=admin_user_id,
            assigned_at=existing.assigned_at if existing else datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return self._store.put(rec)

    def list_users(
        self, admin_user_id: str, groups: Optional[list[str]] = None
    ) -> list[UserRoleAssignment]:
        if not self.has(
            admin_user_id, Permission.ADMIN_MANAGE_USERS, groups=groups
        ):
            raise PermissionError("insufficient permission")
        return self._store.list()


def _singleton_service() -> RbacService:
    table_name = os.environ.get("RBAC_TABLE_NAME")
    if not table_name:
        raise RuntimeError("RBAC_TABLE_NAME env var required")
    return RbacService(RbacStore(table_name=table_name, region=_region()))


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def require_permission(permission: Permission):
    """FastAPI dependency factory: gate a route on a specific Permission."""

    def _dep(request: Request, user_id: str = Depends(require_user)) -> str:
        svc = _singleton_service()
        groups = get_user_groups(request)
        if not svc.has(user_id, permission, groups=groups):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: {permission.value}",
            )
        return user_id

    return _dep
