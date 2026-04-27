"""Custom Resource Lambda for AgentCore CloudFormation stacks.

Handles two Custom Resource types:

1. Custom::AgentCodePackage
   Merges pre-generated agent code with a pre-built dependency bundle
   (strands-mcp.zip or base.zip) into a single code.zip and uploads to S3.

   Properties:
       ArtifactsBucket  — S3 bucket for all artifacts
       AgentCodeKey     — S3 key of the agent code zip (contains agent.py)
       DependencyBundleKey — S3 key of the dependency bundle
       OutputKey        — S3 key for the merged output code.zip
   Returns:
       CodeZipPrefix    — S3 key prefix of the assembled code.zip

2. Custom::OAuth2CredentialProvider
   Creates/deletes an OAuth2 credential provider via the bedrock-agentcore-control
   API. Required for MCP server gateway targets (GATEWAY_IAM_ROLE is not supported).

   Properties:
       ProviderName     — Name for the credential provider
       DiscoveryUrl     — OIDC discovery URL (Cognito)
       ClientId         — OAuth2 client ID
       ClientSecret     — OAuth2 client secret
   Returns:
       CredentialProviderArn — ARN of the created credential provider
"""

import io
import logging
import time
import zipfile
from urllib.parse import quote

import boto3

import cfn_response  # absolute import — this file is packaged as a flat Lambda zip, not a package

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Custom::AgentCodePackage
# ---------------------------------------------------------------------------

def _merge_deps_into_zip(target_zf: zipfile.ZipFile, bundle_bytes: bytes) -> None:
    """Extract dependency bundle into target zip, excluding __pycache__/.pyc."""
    with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as bundle_zf:
        for item in bundle_zf.namelist():
            if "__pycache__" in item or item.endswith(".pyc"):
                continue
            target_zf.writestr(item, bundle_zf.read(item))


def _merge_code_and_deps(agent_zip_bytes: bytes, bundle_bytes: bytes) -> bytes:
    """Merge agent code zip and dependency bundle into a single zip.

    Starts from the pre-built bundle and appends agent code files on top.
    This preserves the bundle's original compression, avoiding a full
    re-compress with ZIP_DEFLATED that can push runtime init past the
    30-second timeout.
    """
    buf = io.BytesIO(bundle_bytes)
    with zipfile.ZipFile(buf, "a") as out_zf:
        with zipfile.ZipFile(io.BytesIO(agent_zip_bytes), "r") as code_zf:
            for item in code_zf.namelist():
                if "__pycache__" in item or item.endswith(".pyc"):
                    continue
                out_zf.writestr(item, code_zf.read(item))
    buf.seek(0)
    return buf.read()


def _handle_code_package_create_update(event: dict) -> tuple[dict, str]:
    """Handle CREATE/UPDATE for AgentCodePackage."""
    props = event["ResourceProperties"]
    bucket = props["ArtifactsBucket"]
    agent_code_key = props["AgentCodeKey"]
    bundle_key = props["DependencyBundleKey"]
    output_key = props["OutputKey"]

    s3 = boto3.client("s3")

    logger.info("Downloading agent code: s3://%s/%s", bucket, agent_code_key)
    agent_zip = s3.get_object(Bucket=bucket, Key=agent_code_key)["Body"].read()
    logger.info("Agent code zip: %d bytes", len(agent_zip))

    logger.info("Downloading dependency bundle: s3://%s/%s", bucket, bundle_key)
    bundle = s3.get_object(Bucket=bucket, Key=bundle_key)["Body"].read()
    logger.info("Dependency bundle: %d bytes", len(bundle))

    merged = _merge_code_and_deps(agent_zip, bundle)
    logger.info("Merged code.zip: %d bytes", len(merged))

    logger.info("Uploading to s3://%s/%s", bucket, output_key)
    s3.put_object(Bucket=bucket, Key=output_key, Body=merged)

    physical_id = f"{bucket}/{output_key}"
    return {"CodeZipPrefix": output_key}, physical_id


def _handle_code_package_delete(event: dict) -> tuple[dict, str]:
    """Handle DELETE for AgentCodePackage."""
    props = event["ResourceProperties"]
    bucket = props["ArtifactsBucket"]
    output_key = props["OutputKey"]

    s3 = boto3.client("s3")
    try:
        s3.delete_object(Bucket=bucket, Key=output_key)
        logger.info("Deleted s3://%s/%s", bucket, output_key)
    except Exception as e:
        logger.warning("Failed to delete s3://%s/%s: %s", bucket, output_key, e)

    return {}, event.get("PhysicalResourceId", event.get("LogicalResourceId", ""))


# ---------------------------------------------------------------------------
# Custom::OAuth2CredentialProvider
# ---------------------------------------------------------------------------

def _get_agentcore_ctrl():
    """Get bedrock-agentcore-control client."""
    return boto3.client("bedrock-agentcore-control")


def _handle_oauth2_cred_create(event: dict) -> tuple[dict, str]:
    """Create an OAuth2 credential provider via bedrock-agentcore-control API."""
    props = event["ResourceProperties"]
    name = props["ProviderName"]
    discovery_url = props["DiscoveryUrl"]
    client_id = props["ClientId"]
    client_secret = props["ClientSecret"]

    ctrl = _get_agentcore_ctrl()

    logger.info("Creating OAuth2 credential provider: %s", name)  # nosemgrep: python-logger-credential-disclosure -- logs resource name, not secret
    try:
        resp = ctrl.create_oauth2_credential_provider(
            name=name,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={
                "customOauth2ProviderConfig": {
                    "oauthDiscovery": {
                        "discoveryUrl": discovery_url,
                    },
                    "clientId": client_id,
                    "clientSecret": client_secret,
                }
            },
        )
        cred_arn = resp.get("credentialProviderArn", "")
    except ctrl.exceptions.ValidationException as e:
        if "already exists" in str(e):
            logger.info("Credential provider %s already exists, fetching ARN", name)  # nosemgrep: python-logger-credential-disclosure -- logs resource name, not secret
            resp = ctrl.get_oauth2_credential_provider(name=name)
            cred_arn = resp.get("credentialProviderArn", "")
        else:
            raise
    logger.info("Created OAuth2 credential provider: %s", cred_arn)  # nosemgrep: python-logger-credential-disclosure -- logs resource ARN, not secret

    # Wait a few seconds for IAM propagation
    time.sleep(5)

    data = {"CredentialProviderArn": cred_arn}

    # If a RuntimeArn is provided, compute the URL-encoded MCP endpoint URL
    runtime_arn = props.get("RuntimeArn", "")
    if runtime_arn:
        region = runtime_arn.split(":")[3] if ":" in runtime_arn else "us-east-1"
        encoded_arn = quote(runtime_arn, safe="")
        endpoint_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
        data["McpEndpointUrl"] = endpoint_url
        logger.info("MCP endpoint URL: %s", endpoint_url)

    return data, cred_arn


def _handle_oauth2_cred_update(event: dict) -> tuple[dict, str]:
    """Update: delete old, create new."""
    old_arn = event.get("PhysicalResourceId", "")
    if old_arn and old_arn.startswith("arn:"):
        _delete_oauth2_cred(old_arn)
    return _handle_oauth2_cred_create(event)


def _delete_oauth2_cred(cred_arn: str) -> None:
    """Delete an OAuth2 credential provider by ARN."""
    ctrl = _get_agentcore_ctrl()
    # Extract the name from ARN
    # ARN format: arn:aws:bedrock-agentcore:region:account:token-vault/default/oauth2credentialprovider/name
    cred_name = cred_arn.rsplit("/", 1)[-1] if "/" in cred_arn else cred_arn
    try:
        ctrl.delete_oauth2_credential_provider(name=cred_name)
        logger.info("Deleted OAuth2 credential provider: %s", cred_arn)  # nosemgrep: python-logger-credential-disclosure -- logs resource ARN, not secret
    except Exception as e:
        logger.warning("Failed to delete credential provider %s: %s", cred_name, type(e).__name__)


def _handle_oauth2_cred_delete(event: dict) -> tuple[dict, str]:
    """Handle DELETE for OAuth2CredentialProvider."""
    cred_arn = event.get("PhysicalResourceId", "")
    if cred_arn and cred_arn.startswith("arn:"):
        _delete_oauth2_cred(cred_arn)
    physical_id = event.get("PhysicalResourceId", event.get("LogicalResourceId", ""))
    return {}, physical_id


# ---------------------------------------------------------------------------
# Router — dispatches by resource type
# ---------------------------------------------------------------------------

def _get_resource_type(event: dict) -> str:
    """Determine the custom resource type from the event."""
    return event.get("ResourceType", event.get("ResourceProperties", {}).get("ServiceToken", ""))


def handler(event: dict, context) -> None:
    """CloudFormation Custom Resource entry point."""
    request_type = event.get("RequestType", "")
    logical_id = event.get("LogicalResourceId", "")
    resource_type = _get_resource_type(event)
    logger.info("CFN %s for %s (type: %s)", request_type, logical_id, resource_type)

    try:
        if resource_type == "Custom::OAuth2CredentialProvider":
            if request_type == "Create":
                data, physical_id = _handle_oauth2_cred_create(event)
            elif request_type == "Update":
                data, physical_id = _handle_oauth2_cred_update(event)
            elif request_type == "Delete":
                data, physical_id = _handle_oauth2_cred_delete(event)
            else:
                raise ValueError(f"Unknown RequestType: {request_type}")
        else:
            # Default: AgentCodePackage
            if request_type in ("Create", "Update"):
                data, physical_id = _handle_code_package_create_update(event)
            elif request_type == "Delete":
                data, physical_id = _handle_code_package_delete(event)
            else:
                raise ValueError(f"Unknown RequestType: {request_type}")

        cfn_response.send(
            event, context,
            cfn_response.SUCCESS,
            data=data,
            physical_resource_id=physical_id,
        )

    except Exception as e:
        logger.exception("Custom resource handler failed")
        cfn_response.send(
            event, context,
            cfn_response.FAILED,
            reason=str(e),
            physical_resource_id=event.get("PhysicalResourceId", logical_id),
        )
