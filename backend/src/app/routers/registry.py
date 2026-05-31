"""Agent Registry API — Phase 2 Gap 2A.

Org-wide catalog for publishing, discovering, and cloning agents.

Endpoints:
  POST   /api/registry                  publish a deployed agent (canvas snapshot)
  GET    /api/registry?q=&tag=&scope=   search/list (visibility-filtered)
  GET    /api/registry/{slug}           fetch one entry (visibility-checked)
  POST   /api/registry/{slug}/clone     clone the canvas snapshot to the caller
  PUT    /api/registry/{slug}           update metadata/visibility (owner only)
  DELETE /api/registry/{slug}           unpublish (owner only)

Tenant model (see registry_store docstring):
  - ``private`` entries are visible only to ``owner_sub``.
  - ``org`` entries are visible to everyone in the same ``org_id``.
  - ``public`` entries are visible cross-org.
  - Mutations require ``owner_sub == caller`` (404-on-mismatch via assert_owner).

Until Gap 2E wires Cognito-group-backed orgs, every caller is in
``DEFAULT_ORG_ID`` so ``org`` ≈ "all platform users". This is called out in
the responses via the ``org_id`` field so the frontend can label it.
"""

from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.auth import assert_owner, get_caller_sub
from app.services.registry_store import (
    DEFAULT_ORG_ID,
    RegistryEntry,
    get_registry_store,
    slugify,
)

logger = logging.getLogger(__name__)


def _validate_slug(slug: str) -> str:
    if not slug or len(slug) > 128:
        raise HTTPException(status_code=400, detail="Invalid agent_slug")
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", slug):
        raise HTTPException(status_code=400, detail="Invalid agent_slug format")
    return slug


def _caller_org_id(caller_sub: str) -> str:
    # Gap 2E will derive this from a Cognito group claim. For now everyone is
    # in the default org so org-visible entries are shared platform-wide.
    return DEFAULT_ORG_ID


router = APIRouter(prefix="/api/registry", tags=["registry"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class PublishRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    visibility: Literal["private", "org", "public"] = "org"
    canvas_snapshot: dict
    source_runtime_name: Optional[str] = None
    latest_version_id: Optional[str] = None


class UpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    visibility: Optional[Literal["private", "org", "public"]] = None


class RegistryEntryResponse(BaseModel):
    org_id: str
    agent_slug: str
    display_name: str
    description: str
    tags: list[str]
    visibility: str
    latest_version_id: Optional[str] = None
    usage_count: int
    source_runtime_name: Optional[str] = None
    created_at: str
    updated_at: str
    is_owner: bool = False

    @classmethod
    def from_entry(cls, e: RegistryEntry, caller_sub: str) -> "RegistryEntryResponse":
        return cls(
            org_id=e.org_id,
            agent_slug=e.agent_slug,
            display_name=e.display_name,
            description=e.description,
            tags=e.tags,
            visibility=e.visibility,
            latest_version_id=e.latest_version_id,
            usage_count=e.usage_count,
            source_runtime_name=e.source_runtime_name,
            created_at=e.created_at,
            updated_at=e.updated_at,
            is_owner=(e.owner_sub == caller_sub),
        )


class CloneResponse(BaseModel):
    agent_slug: str
    display_name: str
    canvas_snapshot: dict


# ---------------------------------------------------------------------------
# Visibility helper
# ---------------------------------------------------------------------------


def _visible_to(entry: RegistryEntry, caller_sub: str, caller_org: str) -> bool:
    if entry.owner_sub == caller_sub:
        return True
    if entry.visibility == "public":
        return True
    if entry.visibility == "org" and entry.org_id == caller_org:
        return True
    return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=RegistryEntryResponse)
async def publish(
    body: PublishRequest,
    caller_sub: str = Depends(get_caller_sub),
) -> RegistryEntryResponse:
    """Publish an agent to the registry.

    The slug is derived from display_name. If a different owner already holds
    that slug in this org, we suffix a short disambiguator so publishing never
    silently overwrites another tenant's entry (the same class of bug as
    Bug 122 — never let a tenant-supplied name collide across owners).
    """
    org_id = _caller_org_id(caller_sub)
    store = get_registry_store()
    base_slug = slugify(body.display_name)
    slug = base_slug

    existing = store.get(org_id, slug)
    if existing is not None and existing.owner_sub != caller_sub:
        # Collision with another owner — disambiguate with a sub-derived suffix.
        slug = f"{base_slug}-{caller_sub[:6]}"[:128]

    entry = RegistryEntry(
        org_id=org_id,
        agent_slug=slug,
        owner_sub=caller_sub,
        display_name=body.display_name,
        description=body.description,
        tags=body.tags,
        visibility=body.visibility,
        latest_version_id=body.latest_version_id,
        canvas_snapshot=body.canvas_snapshot,
        source_runtime_name=body.source_runtime_name,
        usage_count=(existing.usage_count if existing and existing.owner_sub == caller_sub else 0),
    )
    store.put(entry)
    return RegistryEntryResponse.from_entry(entry, caller_sub)


@router.get("", response_model=list[RegistryEntryResponse])
async def search(
    q: Optional[str] = Query(default=None, max_length=200),
    tag: Optional[str] = Query(default=None, max_length=64),
    scope: Literal["all", "mine", "public"] = Query(default="all"),
    caller_sub: str = Depends(get_caller_sub),
) -> list[RegistryEntryResponse]:
    """List/search registry entries visible to the caller."""
    org_id = _caller_org_id(caller_sub)
    store = get_registry_store()

    if scope == "mine":
        entries = store.list_for_owner(caller_sub)
    elif scope == "public":
        entries = store.list_public()
    else:
        # "all" = everything in the caller's org + the caller's own private
        # entries (which are already in-org). list_for_org returns the org
        # rows; we then visibility-filter.
        entries = store.list_for_org(org_id)

    visible = [e for e in entries if _visible_to(e, caller_sub, org_id)]

    if q:
        ql = q.lower()
        visible = [
            e
            for e in visible
            if ql in e.display_name.lower() or ql in e.description.lower()
        ]
    if tag:
        visible = [e for e in visible if tag in e.tags]

    # Newest-updated first.
    visible.sort(key=lambda e: e.updated_at, reverse=True)
    return [RegistryEntryResponse.from_entry(e, caller_sub) for e in visible]


@router.get("/{slug}", response_model=RegistryEntryResponse)
async def get_entry(
    slug: str,
    caller_sub: str = Depends(get_caller_sub),
) -> RegistryEntryResponse:
    slug = _validate_slug(slug)
    org_id = _caller_org_id(caller_sub)
    entry = get_registry_store().get(org_id, slug)
    if entry is None or not _visible_to(entry, caller_sub, org_id):
        # 404 (not 403) — don't disclose existence of entries the caller
        # can't see. Same rule as services/auth.assert_owner.
        raise HTTPException(status_code=404, detail="Not found")
    return RegistryEntryResponse.from_entry(entry, caller_sub)


@router.post("/{slug}/clone", response_model=CloneResponse)
async def clone(
    slug: str,
    caller_sub: str = Depends(get_caller_sub),
) -> CloneResponse:
    """Return the canvas snapshot for the caller to drop onto their canvas.

    Increments usage_count on the source entry. Does NOT mutate the registry
    entry's ownership — the clone lives entirely in the caller's own canvas/
    workflow storage once they save it.
    """
    slug = _validate_slug(slug)
    org_id = _caller_org_id(caller_sub)
    store = get_registry_store()
    entry = store.get(org_id, slug)
    if entry is None or not _visible_to(entry, caller_sub, org_id):
        raise HTTPException(status_code=404, detail="Not found")
    store.increment_usage(org_id, slug)
    return CloneResponse(
        agent_slug=entry.agent_slug,
        display_name=entry.display_name,
        canvas_snapshot=entry.canvas_snapshot,
    )


@router.put("/{slug}", response_model=RegistryEntryResponse)
async def update_entry(
    slug: str,
    body: UpdateRequest,
    caller_sub: str = Depends(get_caller_sub),
) -> RegistryEntryResponse:
    slug = _validate_slug(slug)
    org_id = _caller_org_id(caller_sub)
    store = get_registry_store()
    entry = store.get(org_id, slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not found")
    assert_owner(entry.owner_sub, caller_sub)  # 404 on mismatch

    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        return RegistryEntryResponse.from_entry(entry, caller_sub)
    updated = store.update(org_id, slug, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="Not found")
    return RegistryEntryResponse.from_entry(updated, caller_sub)


@router.delete("/{slug}")
async def delete_entry(
    slug: str,
    caller_sub: str = Depends(get_caller_sub),
) -> dict:
    slug = _validate_slug(slug)
    org_id = _caller_org_id(caller_sub)
    store = get_registry_store()
    entry = store.get(org_id, slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not found")
    assert_owner(entry.owner_sub, caller_sub)  # 404 on mismatch
    ok = store.delete(org_id, slug)
    return {"success": ok, "agent_slug": slug}
