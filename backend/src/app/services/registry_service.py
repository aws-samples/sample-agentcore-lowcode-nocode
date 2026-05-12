"""AWS Agent Registry service (Task 13).

Wraps the real ``bedrock-agentcore-control`` registry APIs.

Tenant model: the Registry is an org-level resource (usually one per
account). We don't put records behind per-user ownership on the AWS side —
instead we mirror an ownership map in DynamoDB so we can 404 on records a
user didn't publish. Admin users (PLATFORM_ADMIN_IDS env var) can see +
approve records across all users.

Custom metadata (owner_user_id) is stamped into each record's descriptor
``custom.inlineContent`` JSON for records we create, so we have a hint
even if our DDB mirror is pruned.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.registry_models import (
    RecordCreateRequest,
    RecordSummary,
    RegistryRecordDescriptorType,
    RegistrySetupRequest,
    RegistrySummary,
)
from app.services.dynamodb_storage import (
    _convert_decimals_to_floats,
    _convert_floats_to_decimals,
    _delete_item,
    _get_dynamodb_resource,
    _get_item,
    _get_table,
    _put_item,
    _scan_table,
)

logger = logging.getLogger(__name__)


def _region() -> str:
    return os.environ.get("APP_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _control_client() -> Any:
    return boto3.client("bedrock-agentcore-control", region_name=_region())


def _client_token(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:64]


def _platform_admin_ids() -> set[str]:
    raw = os.environ.get("RBAC_PLATFORM_ADMIN_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


# ---------------------------------------------------------------------------
# Ownership store
# ---------------------------------------------------------------------------


class RegistryOwnershipStore:
    """Maps (registry_id, record_id) -> user_id. PK=record_id."""

    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, registry_id: str, record_id: str, user_id: str, name: str) -> None:
        _put_item(
            self._table,
            {
                "record_id": record_id,
                "registry_id": registry_id,
                "user_id": user_id,
                "name": name,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def owner_of(self, record_id: str) -> Optional[str]:
        item = _get_item(self._table, {"record_id": record_id})
        if not item:
            return None
        return item.get("user_id")

    def delete(self, record_id: str) -> None:
        _delete_item(self._table, {"record_id": record_id})

    def list_for_user(self, user_id: str) -> list[dict]:
        items = _scan_table(self._table)
        return [_convert_decimals_to_floats(dict(i)) for i in items if i.get("user_id") == user_id]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RegistryService:
    def __init__(self, ownership: RegistryOwnershipStore) -> None:
        self._ownership = ownership
        self._client = _control_client()

    # Registry-level (admin only)

    def create_registry(
        self, admin_user_id: str, req: RegistrySetupRequest
    ) -> RegistrySummary:
        """Create a new registry.

        Authorization is enforced at the router layer via
        ``Depends(require_permission(Permission.REGISTRY_MANAGE))``; this
        method trusts its caller has already been gated.
        """
        params: dict[str, Any] = {
            "name": req.name,
            "clientToken": _client_token(f"registry/{req.name}"),
            "approvalConfiguration": {"autoApproval": req.auto_approval},
        }
        if req.description:
            params["description"] = req.description
        if req.authorizer_discovery_url:
            params["authorizerType"] = "CUSTOM_JWT"
            authz: dict[str, Any] = {
                "customJWTAuthorizer": {
                    "discoveryUrl": req.authorizer_discovery_url,
                }
            }
            if req.authorizer_allowed_audience:
                authz["customJWTAuthorizer"]["allowedAudience"] = req.authorizer_allowed_audience
            params["authorizerConfiguration"] = authz
        resp = self._client.create_registry(**params)
        arn = resp.get("registryArn", "")
        return RegistrySummary(
            registry_id=arn.rsplit("/", 1)[-1] if "/" in arn else arn,
            registry_arn=arn,
            name=req.name,
            description=req.description,
            status="READY",
        )

    def list_registries(self) -> list[RegistrySummary]:
        out: list[RegistrySummary] = []
        # Some preview SDKs don't expose list_registries as a pageable operation
        try:
            resp = self._client.list_registries()
        except AttributeError:
            return []
        for r in resp.get("registries", []):
            out.append(
                RegistrySummary(
                    registry_id=r.get("registryId") or r.get("registryArn", "").rsplit("/", 1)[-1],
                    registry_arn=r.get("registryArn", ""),
                    name=r.get("name", ""),
                    description=r.get("description", ""),
                    status=r.get("status", "UNKNOWN"),
                    authorizer_type=r.get("authorizerType"),
                    created_at=(
                        r["createdAt"].isoformat()
                        if r.get("createdAt") and hasattr(r["createdAt"], "isoformat")
                        else None
                    ),
                    updated_at=(
                        r["updatedAt"].isoformat()
                        if r.get("updatedAt") and hasattr(r["updatedAt"], "isoformat")
                        else None
                    ),
                )
            )
        return out

    # Record-level

    def create_record(
        self,
        user_id: str,
        user_email: str,
        req: RecordCreateRequest,
    ) -> RecordSummary:
        params: dict[str, Any] = {
            "registryId": req.registry_id,
            "name": req.name,
            "descriptorType": req.descriptor_type.value,
            "clientToken": _client_token(f"record/{req.registry_id}/{req.name}"),
        }
        if req.description:
            params["description"] = req.description
        if req.record_version:
            params["recordVersion"] = req.record_version
        if req.sync_from_url:
            params["synchronizationType"] = "FROM_URL"
            params["synchronizationConfiguration"] = {
                "fromUrl": {"url": req.sync_from_url}
            }
        elif req.descriptors:
            params["descriptors"] = req.descriptors.to_api(req.descriptor_type)
        else:
            raise ValueError("either descriptors or sync_from_url must be provided")
        resp = self._client.create_registry_record(**params)
        record_arn = resp.get("recordArn", "")
        # recordArn shape: arn:aws:...:registry/<rid>/record/<rec_id>
        record_id = record_arn.rsplit("/", 1)[-1] if "/record/" in record_arn else ""
        self._ownership.put(req.registry_id, record_id, user_id, req.name)
        return RecordSummary(
            registry_id=req.registry_id,
            registry_arn=record_arn.split("/record/")[0] if "/record/" in record_arn else "",
            record_id=record_id,
            record_arn=record_arn,
            name=req.name,
            description=req.description,
            descriptor_type=req.descriptor_type.value,
            record_version=req.record_version,
            status=resp.get("status", "DRAFT"),
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def get_record(
        self, registry_id: str, record_id: str
    ) -> dict[str, Any]:
        resp = self._client.get_registry_record(
            registryId=registry_id, recordId=record_id
        )
        return resp

    def list_records(
        self,
        registry_id: str,
        status_filter: Optional[str] = None,
        descriptor_type: Optional[str] = None,
        name_filter: Optional[str] = None,
    ) -> list[RecordSummary]:
        params: dict[str, Any] = {"registryId": registry_id}
        if status_filter:
            params["status"] = status_filter
        if descriptor_type:
            params["descriptorType"] = descriptor_type
        if name_filter:
            params["name"] = name_filter
        out: list[RecordSummary] = []
        token: Optional[str] = None
        while True:
            if token:
                params["nextToken"] = token
            resp = self._client.list_registry_records(**params)
            for r in resp.get("registryRecords", []):
                arn = r.get("recordArn", "")
                out.append(
                    RecordSummary(
                        registry_id=registry_id,
                        registry_arn=r.get("registryArn", ""),
                        record_id=r.get("recordId") or arn.rsplit("/", 1)[-1],
                        record_arn=arn,
                        name=r.get("name", ""),
                        description=r.get("description", ""),
                        descriptor_type=r.get("descriptorType", ""),
                        record_version=r.get("recordVersion"),
                        status=r.get("status", "UNKNOWN"),
                        created_at=(
                            r["createdAt"].isoformat() if r.get("createdAt") and hasattr(r["createdAt"], "isoformat") else None
                        ),
                        updated_at=(
                            r["updatedAt"].isoformat() if r.get("updatedAt") and hasattr(r["updatedAt"], "isoformat") else None
                        ),
                    )
                )
            token = resp.get("nextToken")
            if not token:
                break
        return out

    def submit_for_approval(
        self,
        user_id: str,
        registry_id: str,
        record_id: str,
        *,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Submit a draft record for approval.

        Admin callers can submit any record; non-admins can only submit
        records they own. Router-layer ``REGISTRY_SUBMIT`` permission has
        already been checked.
        """
        owner = self._ownership.owner_of(record_id)
        if owner is None:
            raise PermissionError("record not found")
        if owner != user_id and not is_admin:
            raise PermissionError("record not found")
        return self._client.submit_registry_record_for_approval(
            registryId=registry_id, recordId=record_id
        )

    def update_status(
        self,
        admin_user_id: str,
        registry_id: str,
        record_id: str,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        """Approve or reject a record — router gates on REGISTRY_APPROVE."""
        return self._client.update_registry_record_status(
            registryId=registry_id,
            recordId=record_id,
            status=status,
            statusReason=reason,
        )

    def delete_record(
        self,
        user_id: str,
        registry_id: str,
        record_id: str,
        *,
        is_admin: bool = False,
    ) -> None:
        """Delete a record. Owners can always delete their own records;
        admin can delete any. Router-layer ``REGISTRY_PUBLISH`` permission
        has already been checked for non-admins."""
        owner = self._ownership.owner_of(record_id)
        if owner is None:
            raise PermissionError("record not found")
        if owner != user_id and not is_admin:
            raise PermissionError("record not found")
        try:
            self._client.delete_registry_record(
                registryId=registry_id, recordId=record_id
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code != "ResourceNotFoundException":
                raise
        self._ownership.delete(record_id)

    # Discovery (keyword substring over name + description). AWS's list API
    # only supports exact name match + status/descriptorType filters. Keyword
    # search is implemented client-side for now; semantic search will arrive
    # when the SDK exposes it.

    def search(
        self,
        registry_id: str,
        query: str,
        descriptor_type: Optional[str] = None,
    ) -> list[RecordSummary]:
        candidates = self.list_records(
            registry_id,
            status_filter="APPROVED",
            descriptor_type=descriptor_type,
        )
        if not query:
            return candidates
        q = query.lower()
        return [
            r
            for r in candidates
            if q in (r.name or "").lower() or q in (r.description or "").lower()
        ]

    def auto_publish_for_deployment(
        self,
        user_id: str,
        user_email: str,
        registry_id: str,
        deployment_id: str,
        deployment_type: str,  # "harness" | "runtime" | "tool"
        endpoint: Optional[str],
        metadata: dict[str, Any],
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        submit_for_approval: bool = False,
    ) -> Optional[RecordSummary]:
        """Creates a DRAFT record describing a successful deployment.

        Called by the deployment flow after a deploy succeeds. Descriptor type
        is picked based on deployment_type. Always creates DRAFT — the user
        explicitly submits for approval later.
        """
        from app.models.registry_models import (
            CustomDescriptor,
            RegistryRecordDescriptors,
        )

        inline = {
            "deployment_id": deployment_id,
            "deployment_type": deployment_type,
            "endpoint": endpoint,
            "owner_user_id": user_id,
            "owner_email": user_email,
            "metadata": metadata,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        record_name = name or _normalise_record_name(
            f"deployment_{deployment_id[:48]}"
        )
        record_desc = description or (
            f"{deployment_type} deployment {deployment_id}"
        )
        req = RecordCreateRequest(
            registry_id=registry_id,
            name=record_name,
            description=record_desc,
            descriptor_type=RegistryRecordDescriptorType.CUSTOM,
            descriptors=RegistryRecordDescriptors(
                custom=CustomDescriptor(inline_content=json.dumps(inline))
            ),
        )
        try:
            rec = self.create_record(user_id, user_email, req)
        except Exception as e:  # noqa: BLE001
            logger.warning("auto-publish failed for %s: %s", deployment_id, e)
            return None
        if submit_for_approval and rec:
            try:
                self.submit_for_approval(user_id, registry_id, rec.record_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("submit-for-approval failed: %s", e)
        return rec

    def auto_publish_for_tool(
        self,
        user_id: str,
        user_email: str,
        registry_id: str,
        tool: "dict[str, Any]",
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        submit_for_approval: bool = False,
    ) -> Optional[RecordSummary]:
        """Publish a generated tool as a CUSTOM record.

        Ideally this would emit an ``MCP`` descriptor so MCP clients could
        discover the tool automatically, but AWS's ``2025-12-11`` MCP
        server schema is not publicly documented (live-tested: AWS returns
        ``Schema validation failed`` for several reasonable shapes and
        ``mcp.server is required`` for tools-only records). Until AWS
        ships the schema, we publish a ``CUSTOM`` record whose
        ``inline_content`` IS a standard JSON-RPC ``tools/list`` response
        — so a consumer that knows the contract can still parse it.

        Expected ``tool`` keys: ``display_name``, ``description``,
        ``input_schema`` (JSON schema for the tool inputs).
        """
        from app.models.registry_models import (
            CustomDescriptor,
            RegistryRecordDescriptors,
        )

        tool_name = _normalise_record_name(
            tool.get("display_name") or tool.get("name") or "unnamed_tool"
        )
        inline = {
            "resource_type": "mcp_tool",
            "protocol_version": "2024-11-05",
            "owner_user_id": user_id,
            "owner_email": user_email,
            "tools_list": {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {
                            "name": tool_name,
                            "description": tool.get("description", ""),
                            "inputSchema": tool.get("input_schema")
                            or tool.get("inputSchema")
                            or {"type": "object"},
                        }
                    ]
                },
            },
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        req = RecordCreateRequest(
            registry_id=registry_id,
            name=name or tool_name,
            description=description or tool.get("description", ""),
            descriptor_type=RegistryRecordDescriptorType.CUSTOM,
            descriptors=RegistryRecordDescriptors(
                custom=CustomDescriptor(inline_content=json.dumps(inline))
            ),
        )
        try:
            rec = self.create_record(user_id, user_email, req)
        except Exception as e:  # noqa: BLE001
            logger.warning("auto-publish tool failed for %s: %s", tool_name, e)
            return None
        if submit_for_approval and rec:
            try:
                self.submit_for_approval(user_id, registry_id, rec.record_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("submit-for-approval failed: %s", e)
        return rec

    def auto_publish_for_harness(
        self,
        user_id: str,
        user_email: str,
        registry_id: str,
        harness: "dict[str, Any]",
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        submit_for_approval: bool = False,
    ) -> Optional[RecordSummary]:
        """Publish a READY harness as a CUSTOM record.

        Captures what a consumer would need to call the harness: ARN,
        model, runtime ID, summary of tools. Uses CUSTOM descriptor
        since there's no AWS-standard schema for a harness card (yet).
        """
        from app.models.registry_models import (
            CustomDescriptor,
            RegistryRecordDescriptors,
        )

        harness_name = harness.get("name") or harness.get("harness_id", "")
        inline = {
            "resource_type": "agentcore_harness",
            "harness_id": harness.get("harness_id"),
            "harness_arn": harness.get("arn"),
            "agent_runtime_arn": harness.get("agent_runtime_arn"),
            "agent_runtime_id": harness.get("agent_runtime_id"),
            "model_provider": harness.get("model_provider"),
            "model_id": harness.get("model_id"),
            "owner_user_id": user_id,
            "owner_email": user_email,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        record_name = name or _normalise_record_name(f"harness_{harness_name}")
        req = RecordCreateRequest(
            registry_id=registry_id,
            name=record_name,
            description=description or (
                harness.get("description") or f"AgentCore Harness {harness_name}"
            ),
            descriptor_type=RegistryRecordDescriptorType.CUSTOM,
            descriptors=RegistryRecordDescriptors(
                custom=CustomDescriptor(inline_content=json.dumps(inline))
            ),
        )
        try:
            rec = self.create_record(user_id, user_email, req)
        except Exception as e:  # noqa: BLE001
            logger.warning("auto-publish harness failed for %s: %s", harness_name, e)
            return None
        if submit_for_approval and rec:
            try:
                self.submit_for_approval(user_id, registry_id, rec.record_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("submit-for-approval failed: %s", e)
        return rec


def _normalise_record_name(raw: str) -> str:
    """Registry names: letters/digits/_/- only, start with a letter.

    Deterministic so repeated auto-publish of the same source doesn't
    produce a dup with a different name.
    """
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_") or "record"
    if not cleaned[0].isalpha():
        cleaned = f"r_{cleaned}"
    return cleaned[:128]
