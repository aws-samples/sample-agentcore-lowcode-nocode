"""Admin analytics API (Phase 5 — Loom-inspired audit dashboard).

Exposes the action-audit log for super-admins: action counts, per-actor
activity, and a recent-events timeline. Requires the ``admin`` scope (Phase 1),
so only super-admins (g-admins-super / org-admin) can read the org's audit trail.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.services.auth import get_caller_sub
from app.services.rbac import require_scopes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit", dependencies=[Depends(require_scopes("admin"))])
async def get_audit(
    limit: int = Query(default=200, ge=1, le=1000),
    _caller_sub: str = Depends(get_caller_sub),
) -> dict:
    """Return {total, by_action, by_actor, events[]} over recent audit events.

    Best-effort: if the audit table is unavailable (fresh stack) return an empty
    summary rather than 500 — the dashboard renders an empty state.
    """
    try:
        from app.services.audit_store import get_audit_store

        return get_audit_store().summarize("default", limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit summarize failed (returning empty): %s", exc)
        return {"total": 0, "by_action": {}, "by_actor": {}, "events": []}
