"""AgentCore Optimization service (Task 12).

Wraps real boto3 1.43.6 ``bedrock-agentcore-control`` APIs for:
  - configuration bundles (versioned agent config)
  - evaluators (built-in + custom)
  - online evaluation configs (continuous evaluation sampling)
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.optimization_models import (
    ConfigurationBundleRecord,
    ConfigurationBundleRequest,
    ConfigurationBundleUpdateRequest,
    EvaluatorSummary,
    OnlineEvaluationConfigRecord,
    OnlineEvaluationConfigRequest,
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


# ---------------------------------------------------------------------------
# Ownership stores (DDB)
# ---------------------------------------------------------------------------


class BundleStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, r: ConfigurationBundleRecord) -> ConfigurationBundleRecord:
        _put_item(self._table, _convert_floats_to_decimals(r.model_dump(mode="json")))
        return r

    def get(self, bundle_id: str) -> Optional[ConfigurationBundleRecord]:
        item = _get_item(self._table, {"bundle_id": bundle_id})
        if not item:
            return None
        return ConfigurationBundleRecord.model_validate(_convert_decimals_to_floats(dict(item)))

    def delete(self, bundle_id: str) -> None:
        _delete_item(self._table, {"bundle_id": bundle_id})

    def list_for_user(self, user_id: str) -> list[ConfigurationBundleRecord]:
        return sorted(
            [
                ConfigurationBundleRecord.model_validate(_convert_decimals_to_floats(dict(i)))
                for i in _scan_table(self._table)
                if i.get("user_id") == user_id
            ],
            key=lambda r: r.created_at,
            reverse=True,
        )


class OnlineEvalStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = _get_table(_get_dynamodb_resource(region), table_name)

    def put(self, r: OnlineEvaluationConfigRecord) -> OnlineEvaluationConfigRecord:
        _put_item(self._table, _convert_floats_to_decimals(r.model_dump(mode="json")))
        return r

    def get(self, config_id: str) -> Optional[OnlineEvaluationConfigRecord]:
        item = _get_item(self._table, {"config_id": config_id})
        if not item:
            return None
        return OnlineEvaluationConfigRecord.model_validate(_convert_decimals_to_floats(dict(item)))

    def delete(self, config_id: str) -> None:
        _delete_item(self._table, {"config_id": config_id})

    def list_for_user(self, user_id: str) -> list[OnlineEvaluationConfigRecord]:
        return sorted(
            [
                OnlineEvaluationConfigRecord.model_validate(_convert_decimals_to_floats(dict(i)))
                for i in _scan_table(self._table)
                if i.get("user_id") == user_id
            ],
            key=lambda r: r.created_at,
            reverse=True,
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OptimizationService:
    def __init__(
        self,
        bundle_store: BundleStore,
        online_eval_store: OnlineEvalStore,
    ) -> None:
        self._bundles = bundle_store
        self._online_evals = online_eval_store
        self._client = _control_client()

    # ------------------------------------------------------------------
    # Configuration bundles
    # ------------------------------------------------------------------

    def create_bundle(
        self,
        user_id: str,
        user_email: str,
        req: ConfigurationBundleRequest,
    ) -> ConfigurationBundleRecord:
        components_map = {
            c.resource_arn: {"configuration": c.configuration} for c in req.components
        }
        params: dict[str, Any] = {
            "bundleName": req.bundle_name,
            "components": components_map,
            "clientToken": _client_token(f"{user_id}/{req.bundle_name}"),
        }
        if req.description:
            params["description"] = req.description
        if req.branch_name:
            params["branchName"] = req.branch_name
        if req.commit_message:
            params["commitMessage"] = req.commit_message
        params["createdBy"] = {"name": user_email or user_id}
        resp = self._client.create_configuration_bundle(**params)
        rec = ConfigurationBundleRecord(
            bundle_id=resp["bundleId"],
            user_id=user_id,
            bundle_name=req.bundle_name,
            description=req.description,
            bundle_arn=resp.get("bundleArn", ""),
            latest_version_id=resp.get("versionId"),
        )
        return self._bundles.put(rec)

    def update_bundle(
        self,
        user_id: str,
        user_email: str,
        bundle_id: str,
        req: ConfigurationBundleUpdateRequest,
    ) -> ConfigurationBundleRecord:
        rec = self._bundles.get(bundle_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("bundle not found")
        params: dict[str, Any] = {
            "bundleId": bundle_id,
            "clientToken": _client_token(
                f"{user_id}/{bundle_id}/{datetime.now(timezone.utc).isoformat()}"
            ),
        }
        if req.components:
            params["components"] = {
                c.resource_arn: {"configuration": c.configuration} for c in req.components
            }
        if req.branch_name:
            params["branchName"] = req.branch_name
        if req.commit_message:
            params["commitMessage"] = req.commit_message
        # AWS requires parentVersionIds when updating components. If the
        # caller didn't provide them, default to the bundle's current latest
        # so consecutive updates form a linear version chain.
        if req.parent_version_ids:
            params["parentVersionIds"] = req.parent_version_ids
        elif req.components and rec.latest_version_id:
            params["parentVersionIds"] = [rec.latest_version_id]
        if req.description is not None:
            params["description"] = req.description
        params["createdBy"] = {"name": user_email or user_id}
        resp = self._client.update_configuration_bundle(**params)
        rec.latest_version_id = resp.get("versionId")
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        if req.description is not None:
            rec.description = req.description
        return self._bundles.put(rec)

    def get_bundle(
        self, user_id: str, bundle_id: str, version_id: Optional[str] = None
    ) -> tuple[ConfigurationBundleRecord, dict[str, Any]]:
        rec = self._bundles.get(bundle_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("bundle not found")
        if version_id:
            detail = self._client.get_configuration_bundle_version(
                bundleId=bundle_id, versionId=version_id
            )
        else:
            detail = self._client.get_configuration_bundle(bundleId=bundle_id)
        return rec, detail

    def list_bundles(self, user_id: str) -> list[ConfigurationBundleRecord]:
        return self._bundles.list_for_user(user_id)

    def list_versions(self, user_id: str, bundle_id: str) -> list[dict[str, Any]]:
        rec = self._bundles.get(bundle_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("bundle not found")
        resp = self._client.list_configuration_bundle_versions(bundleId=bundle_id)
        return resp.get("versions", [])

    def delete_bundle(self, user_id: str, bundle_id: str) -> None:
        rec = self._bundles.get(bundle_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("bundle not found")
        try:
            self._client.delete_configuration_bundle(bundleId=bundle_id)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code != "ResourceNotFoundException":
                raise
        self._bundles.delete(bundle_id)

    # ------------------------------------------------------------------
    # Evaluators (list-only — builtins are AWS-provided)
    # ------------------------------------------------------------------

    def list_evaluators(self) -> list[EvaluatorSummary]:
        out: list[EvaluatorSummary] = []
        token: Optional[str] = None
        while True:
            params: dict[str, Any] = {"maxResults": 50}
            if token:
                params["nextToken"] = token
            resp = self._client.list_evaluators(**params)
            for e in resp.get("evaluators", []):
                out.append(
                    EvaluatorSummary(
                        evaluator_id=e["evaluatorId"],
                        evaluator_name=e.get("evaluatorName", e["evaluatorId"]),
                        evaluator_arn=e["evaluatorArn"],
                        evaluator_type=e.get("evaluatorType", "Builtin"),
                        level=e.get("level"),
                        description=e.get("description"),
                        status=e.get("status"),
                        locked_for_modification=bool(e.get("lockedForModification", False)),
                    )
                )
            token = resp.get("nextToken")
            if not token:
                break
        return out

    # ------------------------------------------------------------------
    # Online evaluation configs
    # ------------------------------------------------------------------

    def create_online_eval(
        self, user_id: str, req: OnlineEvaluationConfigRequest
    ) -> OnlineEvaluationConfigRecord:
        params: dict[str, Any] = {
            "onlineEvaluationConfigName": req.name,
            "rule": {
                "samplingConfig": {"samplingPercentage": req.sampling.sampling_percentage},
                "sessionConfig": {"sessionTimeoutMinutes": req.sampling.session_timeout_minutes},
            },
            "dataSourceConfig": {
                "cloudWatchLogs": {
                    "logGroupNames": req.data_source.log_group_names,
                    "serviceNames": req.data_source.service_names,
                }
            },
            "evaluators": [{"evaluatorId": eid} for eid in req.evaluator_ids],
            "evaluationExecutionRoleArn": req.execution_role_arn,
            "enableOnCreate": req.enable_on_create,
            "clientToken": _client_token(f"{user_id}/{req.name}"),
        }
        if req.description:
            params["description"] = req.description
        resp = self._client.create_online_evaluation_config(**params)
        rec = OnlineEvaluationConfigRecord(
            config_id=resp["onlineEvaluationConfigId"],
            user_id=user_id,
            name=req.name,
            description=req.description,
            arn=resp.get("onlineEvaluationConfigArn", ""),
            status=resp.get("status", "UNKNOWN"),
            execution_status=resp.get("executionStatus", "UNKNOWN"),
            failure_reason=resp.get("failureReason"),
            sampling_percentage=req.sampling.sampling_percentage,
            evaluator_ids=req.evaluator_ids,
        )
        return self._online_evals.put(rec)

    def get_online_eval(
        self, user_id: str, config_id: str
    ) -> tuple[OnlineEvaluationConfigRecord, dict[str, Any]]:
        rec = self._online_evals.get(config_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("config not found")
        detail = self._client.get_online_evaluation_config(
            onlineEvaluationConfigId=config_id
        )
        # Sync status fields
        rec.status = detail.get("status", rec.status)
        rec.execution_status = detail.get("executionStatus", rec.execution_status)
        rec.failure_reason = detail.get("failureReason")
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        self._online_evals.put(rec)
        return rec, detail

    def list_online_evals(self, user_id: str) -> list[OnlineEvaluationConfigRecord]:
        return self._online_evals.list_for_user(user_id)

    def delete_online_eval(self, user_id: str, config_id: str) -> None:
        rec = self._online_evals.get(config_id)
        if rec is None or rec.user_id != user_id:
            raise PermissionError("config not found")
        try:
            self._client.delete_online_evaluation_config(
                onlineEvaluationConfigId=config_id
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code != "ResourceNotFoundException":
                raise
        self._online_evals.delete(config_id)
