"""AgentCoreClient — thin typed wrapper around the platform REST API."""

from __future__ import annotations

from typing import Any, Optional

import httpx


class AgentCoreError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AgentCoreClient:
    """Typed SDK for the AgentCore REST API.

    Authentication is a Cognito access token passed as Bearer.
    Obtain it via amplify/boto3 cognito-idp-initiate-auth.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        if not api_url:
            raise ValueError("api_url is required")
        if not token:
            raise ValueError("token is required")
        self.api_url = api_url.rstrip("/")
        self.raw = httpx.Client(
            base_url=self.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    def _req(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.raw.request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail: Any = resp.text
            try:
                body = resp.json()
                detail = body.get("detail", body) if isinstance(body, dict) else body
            except ValueError:
                pass
            raise AgentCoreError(
                f"{method} {path} -> {resp.status_code}: {detail}",
                status_code=resp.status_code,
                body=detail,
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def close(self) -> None:
        self.raw.close()

    def __enter__(self) -> "AgentCoreClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        return self._req("GET", "/health")

    # ------------------------------------------------------------------
    # Flows (workflow definitions)
    # ------------------------------------------------------------------

    def list_flows(self) -> list[dict]:
        return self._req("GET", "/api/flows").get("flows", [])

    def create_flow(self, name: str) -> dict:
        return self._req("POST", "/api/flows", json={"name": name}).get("flow", {})

    def get_flow(self, flow_id: str) -> dict:
        return self._req("GET", f"/api/flows/{flow_id}")

    def update_flow(self, flow_id: str, name: Optional[str] = None, workflow: Optional[dict] = None) -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if workflow is not None:
            body["workflow"] = workflow
        return self._req("PUT", f"/api/flows/{flow_id}", json=body).get("flow", {})

    def delete_flow(self, flow_id: str) -> None:
        self._req("DELETE", f"/api/flows/{flow_id}")

    # ------------------------------------------------------------------
    # Workflows (older resource; kept for compatibility)
    # ------------------------------------------------------------------

    def list_workflows(self) -> list[dict]:
        return self._req("GET", "/api/workflows").get("workflows", [])

    def get_workflow(self, workflow_id: str) -> dict:
        return self._req("GET", f"/api/workflows/{workflow_id}")

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------

    def list_triggers(self, deployment_id: Optional[str] = None) -> list[dict]:
        params = {"deployment_id": deployment_id} if deployment_id else None
        return self._req("GET", "/api/triggers", params=params).get("triggers", [])

    def create_schedule_trigger(
        self,
        deployment_id: str,
        runtime_id: str,
        name: str,
        schedule_expression: str,
        input_template: Optional[str] = None,
    ) -> dict:
        body = {
            "deployment_id": deployment_id,
            "runtime_id": runtime_id,
            "trigger_type": "schedule",
            "name": name,
            "schedule_expression": schedule_expression,
        }
        if input_template is not None:
            body["input_template"] = input_template
        return self._req("POST", "/api/triggers", json=body).get("trigger", {})

    def create_webhook_trigger(
        self,
        deployment_id: str,
        runtime_id: str,
        name: str,
        webhook_path: str,
    ) -> dict:
        body = {
            "deployment_id": deployment_id,
            "runtime_id": runtime_id,
            "trigger_type": "webhook",
            "name": name,
            "webhook_path": webhook_path,
        }
        return self._req("POST", "/api/triggers", json=body).get("trigger", {})

    def update_trigger(self, trigger_id: str, **fields: Any) -> dict:
        return self._req("PUT", f"/api/triggers/{trigger_id}", json=fields).get("trigger", {})

    def delete_trigger(self, trigger_id: str) -> None:
        self._req("DELETE", f"/api/triggers/{trigger_id}")

    def test_trigger(self, trigger_id: str, input_text: Optional[str] = None) -> dict:
        return self._req("POST", f"/api/triggers/{trigger_id}/test", json={"input": input_text or ""})

    def trigger_history(self, trigger_id: str) -> list[dict]:
        return self._req("GET", f"/api/triggers/{trigger_id}/history").get("invocations", [])

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def list_approvals(self, status: Optional[str] = None) -> list[dict]:
        params = {"status_filter": status} if status else None
        return self._req("GET", "/api/approvals", params=params).get("approvals", [])

    def create_approval(self, **body: Any) -> dict:
        return self._req("POST", "/api/approvals", json=body).get("approval", {})

    def resolve_approval(self, approval_id: str, decision: str, feedback: Optional[str] = None) -> dict:
        body: dict = {"decision": decision}
        if feedback is not None:
            body["feedback"] = feedback
        return self._req("POST", f"/api/approvals/{approval_id}/resolve", json=body).get("approval", {})

    def approval_stats(self) -> dict:
        return self._req("GET", "/api/approvals/stats")

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def list_versions(self, deployment_id: str) -> list[dict]:
        return self._req("GET", f"/api/deployments/{deployment_id}/versions").get("versions", [])

    def create_snapshot(self, deployment_id: str, **body: Any) -> dict:
        body["deployment_id"] = deployment_id
        return self._req("POST", f"/api/deployments/{deployment_id}/versions", json=body).get("version", {})

    def get_version(self, deployment_id: str, version: int) -> dict:
        return self._req(
            "GET", f"/api/deployments/{deployment_id}/versions/{version}"
        ).get("version", {})

    def rollback(self, deployment_id: str, target_version: int, reason: str) -> dict:
        return self._req(
            "POST",
            f"/api/deployments/{deployment_id}/versions/rollback",
            json={"target_version": target_version, "reason": reason},
        )

    def diff_versions(self, deployment_id: str, from_version: int, to_version: int) -> dict:
        return self._req(
            "GET",
            f"/api/deployments/{deployment_id}/versions/diff",
            params={"from_version": from_version, "to_version": to_version},
        )

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def analytics_summary(self, deployment_id: str, hours: int = 24) -> dict:
        return self._req(
            "GET",
            f"/api/analytics/{deployment_id}/summary",
            params={"hours": hours},
        )

    def analytics_timeseries(
        self, deployment_id: str, metric: str = "InvocationCount", hours: int = 24, stat: str = "Sum"
    ) -> dict:
        return self._req(
            "GET",
            f"/api/analytics/{deployment_id}/timeseries",
            params={"metric": metric, "hours": hours, "stat": stat},
        )

    def record_invocation(
        self,
        deployment_id: str,
        *,
        model_id: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        tool_call_count: int = 0,
        tool_call_success_rate: float = 100.0,
        is_error: bool = False,
    ) -> dict:
        return self._req(
            "POST",
            f"/api/analytics/{deployment_id}/record",
            json={
                "model_id": model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "tool_call_count": tool_call_count,
                "tool_call_success_rate": tool_call_success_rate,
                "is_error": is_error,
            },
        )

    # ------------------------------------------------------------------
    # A2A
    # ------------------------------------------------------------------

    def upsert_a2a(self, **body: Any) -> dict:
        return self._req("PUT", "/api/a2a/config", json=body).get("config", {})

    def list_a2a(self) -> list[dict]:
        return self._req("GET", "/api/a2a/config").get("configs", [])

    def delete_a2a(self, deployment_id: str) -> None:
        self._req("DELETE", f"/api/a2a/config/{deployment_id}")

    # ------------------------------------------------------------------
    # Guardrails
    # ------------------------------------------------------------------

    def list_guardrails(self) -> list[dict]:
        return self._req("GET", "/api/guardrails").get("guardrails", [])

    def create_guardrail(self, **body: Any) -> dict:
        return self._req("POST", "/api/guardrails", json=body).get("guardrail", {})

    def delete_guardrail(self, guardrail_id: str) -> None:
        self._req("DELETE", f"/api/guardrails/{guardrail_id}")

    def test_guardrail(self, guardrail_id: str, text: str, source: str = "INPUT") -> dict:
        return self._req(
            "POST",
            "/api/guardrails/test",
            json={"guardrail_id": guardrail_id, "text": text, "source": source},
        )

    # ------------------------------------------------------------------
    # Environments / promotions
    # ------------------------------------------------------------------

    def list_environments(self, deployment_id: str) -> list[dict]:
        return self._req("GET", f"/api/environments/{deployment_id}").get("bindings", [])

    def promote(
        self,
        deployment_id: str,
        source_env: str,
        target_env: str,
        change_description: str,
        source_version: Optional[int] = None,
    ) -> dict:
        body: dict = {
            "deployment_id": deployment_id,
            "source_env": source_env,
            "target_env": target_env,
            "change_description": change_description,
        }
        if source_version is not None:
            body["source_version"] = source_version
        return self._req("POST", f"/api/environments/{deployment_id}/promote", json=body).get(
            "promotion", {}
        )

    def approve_promotion(self, deployment_id: str, promotion_id: str, comment: str = "") -> dict:
        return self._req(
            "POST",
            f"/api/environments/{deployment_id}/promotions/{promotion_id}/approve",
            json={"comment": comment},
        ).get("promotion", {})

    def reject_promotion(self, deployment_id: str, promotion_id: str, reason: str) -> dict:
        return self._req(
            "POST",
            f"/api/environments/{deployment_id}/promotions/{promotion_id}/reject",
            json={"reason": reason},
        ).get("promotion", {})

    def list_promotions(self, deployment_id: str) -> list[dict]:
        return self._req("GET", f"/api/environments/{deployment_id}/promotions").get(
            "promotions", []
        )
