"""Runtime deployment operations for AgentCore.

Uses pure boto3 APIs — no CLI dependencies.
Handles runtime creation, code upload to S3, IAM role creation,
and runtime lifecycle management.

Requirements: 5.4
"""

import io
import json
import logging
import os
import re
import time
import zipfile
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from CLI output."""
    return _ANSI_ESCAPE.sub("", text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_runtime_name(name: str) -> str:
    """Sanitize a name for agentcore requirements.

    Rules: starts with a letter, only letters/numbers/underscores, max 48 chars.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()[:48]
    if sanitized and not sanitized[0].isalpha():
        sanitized = "agent_" + sanitized
    return sanitized or "agent_default"


def _merge_deps_into_zip(target_zf: zipfile.ZipFile, bundle_bytes: bytes) -> None:
    """Extract dependency bundle contents into the target zip, excluding cache files.

    Reads *bundle_bytes* as an in-memory zip and copies every entry into
    *target_zf* **except** paths that contain ``__pycache__`` or end with
    ``.pyc``.  This keeps the final code zip free of stale bytecode that
    could conflict with the AgentCore Runtime's Python version.

    Requirements: 4.4, 4.5, 5.5
    """
    with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as bundle_zf:
        for item in bundle_zf.namelist():
            if "__pycache__" in item or item.endswith(".pyc"):
                continue
            data = bundle_zf.read(item)
            target_zf.writestr(item, data)


def _create_code_zip(
    agent_code: str,
    requirements_txt: str,
    entrypoint: str,
    deps_bundle: Optional[bytes] = None,
) -> bytes:
    """Create in-memory zip with agent code and optionally bundled deps.

    If *deps_bundle* is provided its contents are merged into the zip root
    via ``_merge_deps_into_zip``, giving the AgentCore Runtime all
    dependencies without a ``pip install`` phase.

    ``requirements.txt`` is only written when *requirements_txt* contains
    non-whitespace content.

    Requirements: 5.1, 5.2, 5.3, 5.4
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(entrypoint, agent_code)
        if requirements_txt.strip():
            zf.writestr("requirements.txt", requirements_txt)
        if deps_bundle:
            _merge_deps_into_zip(zf, deps_bundle)
    buf.seek(0)
    return buf.read()


def upload_code_to_s3(
    s3_client,
    bucket: str,
    key: str,
    agent_code: str,
    requirements_txt: str,
    entrypoint: str = "agent.py",
    deps_bundle: Optional[bytes] = None,
) -> str:
    """Upload agent code zip to S3, optionally with bundled dependencies.

    Returns the S3 URI.
    """
    zip_bytes = _create_code_zip(agent_code, requirements_txt, entrypoint, deps_bundle)
    s3_client.put_object(Bucket=bucket, Key=key, Body=zip_bytes)
    logger.info("Uploaded code to s3://%s/%s (%d bytes)", bucket, key, len(zip_bytes))
    return f"s3://{bucket}/{key}"


def create_runtime_iam_role(
    iam_client,
    role_name: str,
    account_id: str,
    region: str,
    connected_tools: Optional[list] = None,
    otel_secret_arn: Optional[str] = None,
) -> str:
    """Create or reuse an IAM execution role for an AgentCore runtime.

    Returns the role ARN.
    """
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    try:
        resp = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"Execution role for AgentCore runtime {role_name}",
        )
        role_arn = resp["Role"]["Arn"]
        logger.info("Created runtime IAM role: %s", role_arn)
    except iam_client.exceptions.EntityAlreadyExistsException:
        role_arn = iam_client.get_role(RoleName=role_name)["Role"]["Arn"]
        logger.info("Reusing existing runtime IAM role: %s", role_arn)

    # Attach core permissions
    # SECURITY: Scope S3 access to the specific artifacts bucket rather than "*".
    # Bedrock model access uses "*" because model ARNs are dynamic and vary
    # by region/account. CloudWatch Logs uses "*" as log group ARNs are
    # created dynamically by the runtime.
    artifacts_bucket = os.environ.get("ARTIFACTS_BUCKET_NAME", "")
    s3_resources = (
        [
            f"arn:aws:s3:::{artifacts_bucket}",
            f"arn:aws:s3:::{artifacts_bucket}/*",
        ]
        if artifacts_bucket
        else ["*"]
    )  # Fallback to wildcard only if bucket name unavailable

    core_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockModelAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": "*",
            },
            {
                "Sid": "S3CodeAccess",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": s3_resources,
            },
            {
                "Sid": "CloudWatchLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "*",
            },
        ],
    }

    # Add tool-specific permissions
    tools = connected_tools or []
    for tool in tools:
        if tool == "gateway":
            core_policy["Statement"].append(
                {
                    "Sid": "GatewayAccess",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:InvokeGateway",
                        "bedrock-agentcore:ListGateways",
                        "bedrock-agentcore:GetGateway",
                    ],
                    "Resource": "*",
                }
            )
        elif tool == "browser":
            core_policy["Statement"].append(
                {
                    "Sid": "BrowserAccess",
                    "Effect": "Allow",
                    "Action": ["bedrock-agentcore:*Browser*"],
                    "Resource": "*",
                }
            )
        elif tool == "code_interpreter":
            core_policy["Statement"].append(
                {
                    "Sid": "CodeInterpreterAccess",
                    "Effect": "Allow",
                    "Action": ["bedrock-agentcore:*CodeInterpreter*"],
                    "Resource": "*",
                }
            )
        elif tool == "guardrails":
            core_policy["Statement"].append(
                {
                    "Sid": "GuardrailsAccess",
                    "Effect": "Allow",
                    "Action": ["bedrock:ApplyGuardrail", "bedrock:GetGuardrail"],
                    "Resource": "*",
                }
            )
        elif tool == "memory":
            core_policy["Statement"].append(
                {
                    "Sid": "MemoryAccess",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:*Memory*",
                        "bedrock-agentcore:CreateEvent",
                        "bedrock-agentcore:GetLastKTurns",
                        "bedrock-agentcore:RetrieveMemories",
                        "bedrock-agentcore:ListSessions",
                        "bedrock-agentcore:ListActors",
                        "bedrock-agentcore:ListEvents",
                        "bedrock-agentcore-control:GetMemory",
                        "bedrock-agentcore-control:ListMemories",
                    ],
                    "Resource": "*",
                }
            )
        elif tool in ("evaluation", "observability"):
            core_policy["Statement"].append(
                {
                    "Sid": "EvaluationAccess",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:Evaluate",
                        "bedrock-agentcore-control:CreateOnlineEvaluationConfig",
                        "bedrock-agentcore-control:GetOnlineEvaluationConfig",
                        "bedrock-agentcore-control:ListOnlineEvaluationConfigs",
                        "bedrock-agentcore-control:ListEvaluators",
                        "bedrock-agentcore-control:GetEvaluator",
                        "logs:StartQuery",
                        "logs:GetQueryResults",
                    ],
                    "Resource": "*",
                }
            )
        elif tool == "policy":
            core_policy["Statement"].append(
                {
                    "Sid": "PolicyAccess",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore-control:CreatePolicyEngine",
                        "bedrock-agentcore-control:GetPolicyEngine",
                        "bedrock-agentcore-control:ListPolicyEngines",
                        "bedrock-agentcore-control:CreatePolicy",
                        "bedrock-agentcore-control:GetPolicy",
                        "bedrock-agentcore-control:ListPolicies",
                        "bedrock-agentcore-control:UpdateGateway",
                    ],
                    "Resource": "*",
                }
            )

    # Scoped Secrets Manager access for OTLP auth header (Langfuse,
    # Honeycomb, etc.). Bug 9 reminder: keep this in sync with the SFN path.
    if otel_secret_arn:
        core_policy["Statement"].append(
            {
                "Sid": "OtelAuthHeaderSecret",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [otel_secret_arn],
            }
        )

    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName="AgentCoreRuntimePolicy",
        PolicyDocument=json.dumps(core_policy),
    )

    # Wait for IAM propagation. AgentCore's service-side IAM cache for the
    # role's S3 access check needs ~60s — a shorter sleep caused every fresh
    # deploy to fail with `ValidationException: Access denied when trying to
    # retrieve zip file from S3`. Verified live 2026-05-16. See lessons Bug 52.
    # The downstream create_agent_runtime() also retries on this specific
    # error so we're double-belted; this sleep keeps the happy path one-shot.
    time.sleep(15)
    return role_arn


def create_agent_runtime(
    agentcore_ctrl,
    runtime_name: str,
    role_arn: str,
    s3_bucket: str,
    s3_key: str,
    entrypoint: str = "agent.py",
    python_runtime: str = "PYTHON_3_13",
    protocol: str = "HTTP",
    env_vars: Optional[dict] = None,
    authorizer_config: Optional[dict] = None,
) -> dict:
    """Create an AgentCore runtime using the boto3 control API.

    Returns dict with runtime_id, arn, status.
    """
    create_params = {
        "agentRuntimeName": runtime_name,
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "code": {
                    "s3": {
                        "bucket": s3_bucket,
                        "prefix": s3_key,
                    }
                },
                "runtime": python_runtime,
                "entryPoint": [entrypoint],
            }
        },
        "roleArn": role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": protocol},
    }

    if env_vars:
        create_params["environmentVariables"] = env_vars

    if authorizer_config:
        create_params["authorizerConfiguration"] = authorizer_config

    def _create_with_transient_retry():
        """Retry create_agent_runtime on two known transient ValidationExceptions.

        Two distinct failure modes share the same outer exception type:

        1. **S3 region redirect (Bug 63 root cause).** AgentCore's service-side
           S3 client returns `S3 operation failed: Moved Permanently (Status
           Code: 301)` on the FIRST call to a bucket whose region it hasn't
           cached. The 301 response itself warms the cache — a retry within
           seconds succeeds. Verified live 2026-05-18 with a controlled
           diagnostic: identical (role, bucket, key) failed on call 1 with
           301 and succeeded on call 2 ~30s later.

        2. **IAM-propagation race.** Service-side IAM cache for the runtime
           role's S3 read permission can lag the IAM control plane after
           `put_role_policy`. Surfaces as `Access denied when trying to
           retrieve zip file from S3`. Less common now that we pre-create
           the shared role at stack init (Bug 60), but kept as a safety net.

        Budget: 8 × 5s = 40s. The 301 case resolves in <1s; we just need a
        few retry slots. Way under the SFN 240s ceiling.
        """
        retryable_markers = (
            "Access denied when trying to retrieve",  # IAM-propagation race
            "Moved Permanently",                       # S3 region cache miss
            "Status Code: 301",                        # S3 region cache miss
        )
        last_err = None
        attempts = 8
        for attempt in range(attempts):
            try:
                return agentcore_ctrl.create_agent_runtime(**create_params)
            except Exception as e:
                err_str = str(e)
                if "ValidationException" in err_str and any(
                    m in err_str for m in retryable_markers
                ):
                    last_err = e
                    logger.info(
                        "create_agent_runtime transient (attempt %d/%d): %s",
                        attempt + 1, attempts, err_str[:200],
                    )
                    time.sleep(5)
                    continue
                raise
        raise last_err if last_err else RuntimeError("create_agent_runtime failed")

    try:
        resp = _create_with_transient_retry()
    except Exception as e:
        if "ConflictException" in str(e) or "already exists" in str(e):
            # Find existing runtime by paginating through all runtimes
            logger.info("Runtime '%s' already exists, searching to update...", runtime_name)
            found_id = None
            found_arn = ""
            next_token = None
            for _ in range(20):  # max 20 pages
                list_kwargs = {}
                if next_token:
                    list_kwargs["nextToken"] = next_token
                try:
                    existing = agentcore_ctrl.list_agent_runtimes(**list_kwargs)
                except Exception:
                    # Fallback: try with maxResults
                    list_kwargs["maxResults"] = 100
                    existing = agentcore_ctrl.list_agent_runtimes(**list_kwargs)

                runtimes = existing.get("agentRuntimeSummaries", existing.get("agentRuntimes", []))
                for rt in runtimes:
                    if rt.get("agentRuntimeName") == runtime_name:
                        found_id = rt.get("agentRuntimeId", "")
                        found_arn = rt.get("agentRuntimeArn", "")
                        break
                if found_id:
                    break
                next_token = existing.get("nextToken")
                if not next_token:
                    break

            if found_id:
                logger.info("Found existing runtime: %s, updating...", found_id)
                try:
                    update_params = {
                        "agentRuntimeId": found_id,
                        "agentRuntimeArtifact": create_params["agentRuntimeArtifact"],
                        "roleArn": role_arn,
                        "networkConfiguration": create_params["networkConfiguration"],
                        "protocolConfiguration": create_params["protocolConfiguration"],
                    }
                    if env_vars:
                        update_params["environmentVariables"] = env_vars
                    agentcore_ctrl.update_agent_runtime(**update_params)
                except Exception as update_err:
                    logger.warning("Update failed: %s. Returning existing runtime.", update_err)
                return {
                    "runtime_id": found_id,
                    "arn": found_arn,
                    "status": "UPDATING",
                }
            else:
                logger.error("Could not find existing runtime '%s' in list", runtime_name)
                raise
        else:
            raise

    runtime_id = resp.get("agentRuntimeId", "")
    arn = resp.get("agentRuntimeArn", "")
    logger.info("Created runtime: id=%s, arn=%s", runtime_id, arn)

    return {
        "runtime_id": runtime_id,
        "arn": arn,
        "status": resp.get("status", "CREATING"),
    }


def wait_for_runtime_ready(agentcore_ctrl, runtime_id: str, timeout: int = 600) -> dict:
    """Poll until runtime is READY/ACTIVE or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = agentcore_ctrl.get_agent_runtime(agentRuntimeId=runtime_id)
            status = resp.get("status", "")
            logger.info("Runtime %s status: %s", runtime_id, status)

            if status in ("READY", "ACTIVE"):
                return {
                    "success": True,
                    "runtime_id": runtime_id,
                    "arn": resp.get("agentRuntimeArn", ""),
                    "status": status,
                }
            if "FAILED" in status:
                return {
                    "success": False,
                    "runtime_id": runtime_id,
                    "status": status,
                    "error": f"Runtime entered {status}",
                }
        except Exception as e:
            logger.warning("Error checking runtime status: %s", e)

        time.sleep(15)

    return {
        "success": False,
        "runtime_id": runtime_id,
        "error": f"Runtime did not become READY within {timeout}s",
    }


def _resolve_runtime_identifier(agentcore_ctrl, identifier: str) -> str:
    """Convert a runtime NAME (or already-an-id) to the canonical agentRuntimeId.

    AgentCore distinguishes the human-readable runtime name (e.g.
    `my_agent_v1`) from the canonical id (e.g. `my_agent_v1-AbCdEfGh01`).
    `delete_agent_runtime`/`get_agent_runtime` accept ONLY the canonical id —
    passing the friendly name returns AccessDeniedException (not 404),
    masking the real cause. See tasks/lessons.md Bug 50.

    Heuristic: if the input looks like the canonical id (has `-` followed by
    a 10-char hash) it's used as-is. Otherwise we list and match by name.
    """
    if not identifier:
        return identifier
    # Canonical id pattern: <name>-<10 hash chars>. Anchored on both ends and
    # restricted to the AgentCore-permitted name alphabet so the regex stays
    # linear (no `.+` polynomial backtracking on adversarial input).
    if re.match(r"^[A-Za-z0-9_-]+-[A-Za-z0-9]{10}$", identifier):
        return identifier
    # Name lookup — paginate list_agent_runtimes
    try:
        next_token = None
        for _ in range(20):  # max 20 pages
            kwargs = {}
            if next_token:
                kwargs["nextToken"] = next_token
            try:
                resp = agentcore_ctrl.list_agent_runtimes(**kwargs)
            except Exception:
                kwargs["maxResults"] = 100
                resp = agentcore_ctrl.list_agent_runtimes(**kwargs)
            runtimes = resp.get("agentRuntimeSummaries", resp.get("agentRuntimes", []))
            for rt in runtimes:
                if rt.get("agentRuntimeName") == identifier:
                    return rt.get("agentRuntimeId", identifier)
            next_token = resp.get("nextToken")
            if not next_token:
                break
    except Exception as e:
        logger.warning("Could not resolve runtime name %s to id: %s", identifier, e)
    return identifier  # fall through; caller will see ResourceNotFound and treat as no-op


def destroy_runtime(runtime_id: str, region: str) -> dict:
    """Delete an AgentCore runtime AND its execution role.

    Order of operations matters: capture roleArn via get-agent-runtime BEFORE
    delete-agent-runtime — after deletion the get fails and the role is orphaned
    (verified live 2026-05-16 — the API DELETE path leaked roles before this
    fix; see tasks/lessons.md Bug 25 / Bug 27 — drift between cleanup.sh and
    runtime_deployer.destroy_runtime).

    The `runtime_id` arg may be either the canonical agentRuntimeId or the
    friendly agentRuntimeName — we resolve it (Bug 50).

    Idempotent on already-deleted runtimes/roles.
    """
    agentcore_ctrl = boto3.client("bedrock-agentcore-control", region_name=region)
    canonical_id = _resolve_runtime_identifier(agentcore_ctrl, runtime_id)

    # AgentCore returns AccessDeniedException (NOT ResourceNotFound) when the
    # runtime ID doesn't exist. Treat both as "runtime is gone" so DELETE on a
    # never-created runtime still proceeds to IAM-role cleanup. See lessons Bug 55.
    def _is_runtime_gone(err: Exception) -> bool:
        s = str(err)
        return "ResourceNotFound" in s or "AccessDeniedException" in s

    # Capture roleArn first so we can also delete the IAM role.
    role_arn = ""
    try:
        rt = agentcore_ctrl.get_agent_runtime(agentRuntimeId=canonical_id)
        role_arn = rt.get("roleArn", "") or ""
    except Exception as e:
        if not _is_runtime_gone(e):
            logger.warning("Could not get-agent-runtime before delete: %s", e)

    try:
        agentcore_ctrl.delete_agent_runtime(agentRuntimeId=canonical_id)
        logger.info("Deleted runtime: %s", canonical_id)
    except Exception as e:
        if not _is_runtime_gone(e):
            return {"success": False, "message": f"Runtime destroy error: {e}"}
        logger.info("Runtime %s already deleted (or never existed)", canonical_id)

    # Best-effort: delete the matched IAM execution role(s) too.
    # When the runtime never existed, role_arn is empty (get_agent_runtime
    # returned AccessDenied); fall back to the conventional names used by
    # the SFN IAM step (`AgentCoreRuntime-{name}`) and the direct-deploy path
    # (`{name}-role`). See lessons Bug 57.
    candidate_role_names: list[str] = []
    if role_arn:
        # roleArn format: arn:aws:iam::<acct>:role/<RoleName>
        candidate_role_names.append(role_arn.rsplit("/", 1)[-1])
    # Use the original argument as the runtime "name" component for the
    # convention-based fallback. canonical_id may include a `-XxXxXxXxXx`
    # suffix; strip that to recover the runtime name.
    name_for_role = re.sub(r"-[A-Za-z0-9]{10}$", "", runtime_id)
    for role_name in (
        f"AgentCoreRuntime-{name_for_role}",
        f"{name_for_role}-role",
    ):
        if role_name not in candidate_role_names:
            candidate_role_names.append(role_name)

    # Bug 60 introduced a stack-managed shared role. Bug 62: never delete
    # that role — every DELETE /api/runtime would nuke it, breaking every
    # other runtime in the stack (and DemoTriage). Compare role NAME (not
    # ARN) so this still works when the cleanup is via the name fallback.
    shared_role_arn = os.environ.get("SHARED_RUNTIME_ROLE_ARN", "")
    shared_role_name = (
        shared_role_arn.rsplit("/", 1)[-1] if shared_role_arn else ""
    )

    iam = boto3.client("iam")
    deleted_any_role = False
    for role_name in candidate_role_names:
        if not role_name:
            continue
        # Skip stack-managed shared roles. Match exact (Bug 60's role) or any
        # role with `-shared` suffix as defense in depth against future shared
        # roles. See tasks/lessons.md Bug 62.
        if role_name == shared_role_name or role_name.endswith("-shared"):
            logger.info("Skipping shared role %s (Bug 62 guard)", role_name)
            continue
        try:
            # Detach managed policies
            for p in iam.list_attached_role_policies(RoleName=role_name).get(
                "AttachedPolicies", []
            ):
                try:
                    iam.detach_role_policy(RoleName=role_name, PolicyArn=p["PolicyArn"])
                except Exception as e:
                    logger.warning("detach_role_policy %s: %s", p.get("PolicyArn"), e)
            # Delete inline policies
            for pn in iam.list_role_policies(RoleName=role_name).get(
                "PolicyNames", []
            ):
                try:
                    iam.delete_role_policy(RoleName=role_name, PolicyName=pn)
                except Exception as e:
                    logger.warning("delete_role_policy %s: %s", pn, e)
            iam.delete_role(RoleName=role_name)
            logger.info("Deleted runtime execution role: %s", role_name)
            deleted_any_role = True
        except iam.exceptions.NoSuchEntityException:
            # Role doesn't exist for this candidate — try the next.
            continue
        except Exception as e:
            # Don't fail the whole delete because of role cleanup issues.
            logger.warning("Runtime %s role cleanup (%s) failed: %s", runtime_id, role_name, e)

    if deleted_any_role:
        return {"success": True, "message": f"Runtime {runtime_id} and execution role deleted"}
    return {"success": True, "message": f"Runtime {runtime_id} deleted"}
