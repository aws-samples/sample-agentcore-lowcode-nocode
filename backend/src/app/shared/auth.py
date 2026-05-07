"""Shared auth helpers for FastAPI routers.

The API Gateway HTTP API is fronted by a Cognito JWT authorizer. The JWT claims
are forwarded to Lambda via `event.requestContext.authorizer.jwt.claims`. Mangum
exposes the raw event on `request.scope["aws.event"]`.

All market-gap routers use `require_user()` to scope reads/writes to the calling
user. Missing claim => 401 (API Gateway should have rejected earlier; this is a
defence-in-depth check for local-dev and tests where the authorizer is bypassed).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Request, status


def get_claims(request: Request) -> dict[str, Any]:
    event = request.scope.get("aws.event") or {}
    ctx = event.get("requestContext") or {}
    authz = ctx.get("authorizer") or {}
    jwt = authz.get("jwt") or {}
    claims = jwt.get("claims") or {}
    return claims if isinstance(claims, dict) else {}


def get_user_id(request: Request) -> Optional[str]:
    """Return the Cognito sub for the caller, or None."""
    claims = get_claims(request)
    sub = claims.get("sub")
    return sub if isinstance(sub, str) and sub else None


def get_user_email(request: Request) -> Optional[str]:
    claims = get_claims(request)
    email = claims.get("email")
    return email if isinstance(email, str) and email else None


def require_user(request: Request) -> str:
    """FastAPI dependency: require an authenticated user, return their sub."""
    sub = get_user_id(request)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication",
        )
    return sub
