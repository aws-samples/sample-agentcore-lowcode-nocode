"""agentcore-cli entry point."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

import click

from agentcore_sdk import AgentCoreClient, AgentCoreError


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _mint_token_via_cognito(
    pool_id: str, client_id: str, username: str, password: str, region: str
) -> str:
    try:
        import boto3
    except ImportError as e:
        raise click.ClickException(
            "boto3 required to mint Cognito tokens; install via `pip install boto3`."
        ) from e
    client = boto3.client("cognito-idp", region_name=region)
    resp = client.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        ClientId=client_id,
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return resp["AuthenticationResult"]["AccessToken"]


def _resolve_client(api_url: Optional[str], token: Optional[str]) -> AgentCoreClient:
    api_url = api_url or os.environ.get("AGENTCORE_API_URL")
    if not api_url:
        raise click.ClickException(
            "API URL not set; pass --api-url or set AGENTCORE_API_URL"
        )
    if not token:
        token = os.environ.get("AGENTCORE_TOKEN")
    if not token:
        pool_id = os.environ.get("AGENTCORE_COGNITO_USER_POOL_ID")
        client_id = os.environ.get("AGENTCORE_COGNITO_CLIENT_ID")
        username = os.environ.get("AGENTCORE_COGNITO_USERNAME")
        password = os.environ.get("AGENTCORE_COGNITO_PASSWORD")
        region = os.environ.get("AGENTCORE_AWS_REGION", "us-east-1")
        if not (pool_id and client_id and username and password):
            raise click.ClickException(
                "No token and incomplete Cognito env vars.\n"
                "Set either AGENTCORE_TOKEN or all of: "
                "AGENTCORE_COGNITO_USER_POOL_ID, AGENTCORE_COGNITO_CLIENT_ID, "
                "AGENTCORE_COGNITO_USERNAME, AGENTCORE_COGNITO_PASSWORD"
            )
        token = _mint_token_via_cognito(pool_id, client_id, username, password, region)
    return AgentCoreClient(api_url=api_url, token=token)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _emit(obj: Any, use_json: bool, columns: Optional[list[str]] = None) -> None:
    if use_json:
        click.echo(json.dumps(obj, default=str, indent=2))
        return
    if isinstance(obj, list) and columns and obj:
        widths = {c: max(len(c), max((len(str(x.get(c, ""))) for x in obj), default=0)) for c in columns}
        header = "  ".join(c.ljust(widths[c]) for c in columns)
        click.echo(header)
        click.echo("-" * len(header))
        for row in obj:
            click.echo("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))
    elif isinstance(obj, list):
        for item in obj:
            click.echo(json.dumps(item, default=str))
    else:
        click.echo(json.dumps(obj, default=str, indent=2))


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--api-url", help="Platform API URL (or env AGENTCORE_API_URL)")
@click.option("--token", help="Bearer token (or env AGENTCORE_TOKEN)")
@click.option("--json", "use_json", is_flag=True, help="Emit JSON output")
@click.pass_context
def cli(ctx: click.Context, api_url: Optional[str], token: Optional[str], use_json: bool) -> None:
    """AgentCore platform CLI."""
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url
    ctx.obj["token"] = token
    ctx.obj["json"] = use_json


def _client(ctx: click.Context) -> AgentCoreClient:
    return _resolve_client(ctx.obj.get("api_url"), ctx.obj.get("token"))


@cli.command()
@click.pass_context
def health(ctx: click.Context) -> None:
    """Check API health."""
    try:
        _emit(_client(ctx).health(), ctx.obj["json"])
    except AgentCoreError as e:
        raise click.ClickException(str(e))


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@cli.group()
def flows() -> None:
    """Manage flows."""


@flows.command("list")
@click.pass_context
def flows_list(ctx: click.Context) -> None:
    _emit(
        _client(ctx).list_flows(),
        ctx.obj["json"],
        columns=["id", "name", "deployment_status", "updated_at"],
    )


@flows.command("create")
@click.argument("name")
@click.pass_context
def flows_create(ctx: click.Context, name: str) -> None:
    _emit(_client(ctx).create_flow(name), ctx.obj["json"])


@flows.command("delete")
@click.argument("flow_id")
@click.pass_context
def flows_delete(ctx: click.Context, flow_id: str) -> None:
    _client(ctx).delete_flow(flow_id)
    click.echo(f"deleted {flow_id}")


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


@cli.group()
def triggers() -> None:
    """Manage triggers."""


@triggers.command("list")
@click.option("--deployment", help="Filter by deployment_id")
@click.pass_context
def triggers_list(ctx: click.Context, deployment: Optional[str]) -> None:
    _emit(
        _client(ctx).list_triggers(deployment_id=deployment),
        ctx.obj["json"],
        columns=["trigger_id", "name", "trigger_type", "status", "schedule_expression"],
    )


@triggers.command("create-schedule")
@click.option("--deployment", required=True)
@click.option("--runtime", required=True)
@click.option("--name", required=True)
@click.option("--cron", "expression", required=True, help="cron(...) or rate(...)")
@click.option("--input-template", default=None)
@click.pass_context
def triggers_create_schedule(
    ctx: click.Context,
    deployment: str,
    runtime: str,
    name: str,
    expression: str,
    input_template: Optional[str],
) -> None:
    _emit(
        _client(ctx).create_schedule_trigger(
            deployment_id=deployment,
            runtime_id=runtime,
            name=name,
            schedule_expression=expression,
            input_template=input_template,
        ),
        ctx.obj["json"],
    )


@triggers.command("create-webhook")
@click.option("--deployment", required=True)
@click.option("--runtime", required=True)
@click.option("--name", required=True)
@click.option("--path", "webhook_path", required=True)
@click.pass_context
def triggers_create_webhook(
    ctx: click.Context, deployment: str, runtime: str, name: str, webhook_path: str
) -> None:
    _emit(
        _client(ctx).create_webhook_trigger(
            deployment_id=deployment, runtime_id=runtime, name=name, webhook_path=webhook_path
        ),
        ctx.obj["json"],
    )


@triggers.command("delete")
@click.argument("trigger_id")
@click.pass_context
def triggers_delete(ctx: click.Context, trigger_id: str) -> None:
    _client(ctx).delete_trigger(trigger_id)
    click.echo(f"deleted {trigger_id}")


@triggers.command("test")
@click.argument("trigger_id")
@click.option("--input", "input_text", default=None)
@click.pass_context
def triggers_test(ctx: click.Context, trigger_id: str, input_text: Optional[str]) -> None:
    _emit(_client(ctx).test_trigger(trigger_id, input_text=input_text), ctx.obj["json"])


@triggers.command("history")
@click.argument("trigger_id")
@click.pass_context
def triggers_history(ctx: click.Context, trigger_id: str) -> None:
    _emit(
        _client(ctx).trigger_history(trigger_id),
        ctx.obj["json"],
        columns=["invocation_id", "source", "status", "duration_ms", "invoked_at"],
    )


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@cli.group()
def approvals() -> None:
    """Manage approvals (HITL)."""


@approvals.command("list")
@click.option("--status", default=None)
@click.pass_context
def approvals_list(ctx: click.Context, status: Optional[str]) -> None:
    _emit(
        _client(ctx).list_approvals(status=status),
        ctx.obj["json"],
        columns=["approval_id", "title", "status", "deployment_id", "created_at"],
    )


@approvals.command("approve")
@click.argument("approval_id")
@click.option("--feedback", default=None)
@click.pass_context
def approvals_approve(ctx: click.Context, approval_id: str, feedback: Optional[str]) -> None:
    _emit(_client(ctx).resolve_approval(approval_id, "approved", feedback), ctx.obj["json"])


@approvals.command("reject")
@click.argument("approval_id")
@click.option("--feedback", default=None)
@click.pass_context
def approvals_reject(ctx: click.Context, approval_id: str, feedback: Optional[str]) -> None:
    _emit(_client(ctx).resolve_approval(approval_id, "rejected", feedback), ctx.obj["json"])


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@cli.group()
def versions() -> None:
    """Manage agent versions."""


@versions.command("list")
@click.option("--deployment", required=True)
@click.pass_context
def versions_list(ctx: click.Context, deployment: str) -> None:
    _emit(
        _client(ctx).list_versions(deployment),
        ctx.obj["json"],
        columns=["version", "status", "deployed_at", "change_description"],
    )


@versions.command("rollback")
@click.option("--deployment", required=True)
@click.option("--target-version", type=int, required=True)
@click.option("--reason", required=True)
@click.pass_context
def versions_rollback(ctx: click.Context, deployment: str, target_version: int, reason: str) -> None:
    _emit(_client(ctx).rollback(deployment, target_version, reason), ctx.obj["json"])


@versions.command("diff")
@click.option("--deployment", required=True)
@click.option("--from-version", type=int, required=True)
@click.option("--to-version", type=int, required=True)
@click.pass_context
def versions_diff(ctx: click.Context, deployment: str, from_version: int, to_version: int) -> None:
    _emit(_client(ctx).diff_versions(deployment, from_version, to_version), ctx.obj["json"])


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@cli.group()
def analytics() -> None:
    """Dashboards + metrics."""


@analytics.command("summary")
@click.option("--deployment", required=True)
@click.option("--hours", type=int, default=24)
@click.pass_context
def analytics_summary(ctx: click.Context, deployment: str, hours: int) -> None:
    _emit(_client(ctx).analytics_summary(deployment, hours=hours), ctx.obj["json"])


@analytics.command("record")
@click.option("--deployment", required=True)
@click.option("--model-id", default=None)
@click.option("--input-tokens", type=int, default=0)
@click.option("--output-tokens", type=int, default=0)
@click.option("--latency-ms", type=int, default=0)
@click.option("--is-error", is_flag=True)
@click.pass_context
def analytics_record(
    ctx: click.Context,
    deployment: str,
    model_id: Optional[str],
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    is_error: bool,
) -> None:
    _emit(
        _client(ctx).record_invocation(
            deployment,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            is_error=is_error,
        ),
        ctx.obj["json"],
    )


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


@cli.group()
def environments() -> None:
    """Environment promotions."""


@environments.command("list")
@click.option("--deployment", required=True)
@click.pass_context
def environments_list(ctx: click.Context, deployment: str) -> None:
    _emit(
        _client(ctx).list_environments(deployment),
        ctx.obj["json"],
        columns=["env", "active_version", "updated_at"],
    )


@environments.command("promote")
@click.option("--deployment", required=True)
@click.option("--source-env", required=True, type=click.Choice(["dev", "staging", "prod"]))
@click.option("--target-env", required=True, type=click.Choice(["dev", "staging", "prod"]))
@click.option("--desc", "change_description", required=True)
@click.option("--source-version", type=int, default=None)
@click.pass_context
def environments_promote(
    ctx: click.Context,
    deployment: str,
    source_env: str,
    target_env: str,
    change_description: str,
    source_version: Optional[int],
) -> None:
    _emit(
        _client(ctx).promote(
            deployment,
            source_env=source_env,
            target_env=target_env,
            change_description=change_description,
            source_version=source_version,
        ),
        ctx.obj["json"],
    )


@environments.command("approve")
@click.option("--deployment", required=True)
@click.option("--promotion-id", required=True)
@click.option("--comment", default="")
@click.pass_context
def environments_approve(
    ctx: click.Context, deployment: str, promotion_id: str, comment: str
) -> None:
    _emit(
        _client(ctx).approve_promotion(deployment, promotion_id, comment),
        ctx.obj["json"],
    )


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


@cli.group()
def guardrails() -> None:
    """Manage Bedrock Guardrails."""


@guardrails.command("list")
@click.pass_context
def guardrails_list(ctx: click.Context) -> None:
    _emit(
        _client(ctx).list_guardrails(),
        ctx.obj["json"],
        columns=["guardrail_id", "name", "version", "updated_at"],
    )


@guardrails.command("test")
@click.option("--guardrail-id", required=True)
@click.option("--text", required=True)
@click.option("--source", type=click.Choice(["INPUT", "OUTPUT"]), default="INPUT")
@click.pass_context
def guardrails_test(ctx: click.Context, guardrail_id: str, text: str, source: str) -> None:
    _emit(
        _client(ctx).test_guardrail(guardrail_id, text, source=source),
        ctx.obj["json"],
    )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
