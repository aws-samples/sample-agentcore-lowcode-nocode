#!/usr/bin/env python3
"""CDK app entry point for the AgentCore Visual Workflow Platform.

Reads configuration from CDK context parameters and instantiates the
PlatformStack with the appropriate environment settings.

CDK-NAG (AwsSolutionsChecks) runs during synthesis to flag security
best-practice violations. Suppressions document conscious trade-offs.

Requirements: 1.1, 1.4
"""

import aws_cdk as cdk
import cdk_nag

from stacks.platform_stack import PlatformStack


def get_context_value(app: cdk.App, key: str, default: str | None = None) -> str:
    """Read a value from CDK context, falling back to a default."""
    value = app.node.try_get_context(key)
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required CDK context parameter: '{key}'. Pass it with -c {key}=<value>")
    return value


app = cdk.App()

environment_name = get_context_value(app, "environment_name", default="dev")
aws_region = get_context_value(app, "aws_region", default="us-east-1")
project_name = get_context_value(app, "project_name", default="agentcore-workflow")

stack = PlatformStack(
    app,
    f"{project_name}-{environment_name}",
    env=cdk.Environment(region=aws_region),
    environment_name=environment_name,
    project_name=project_name,
)

# ---------------------------------------------------------------------------
# CDK-NAG: AWS Solutions security checks
# ---------------------------------------------------------------------------
cdk.Aspects.of(app).add(cdk_nag.AwsSolutionsChecks(verbose=True))

# Suppressions document conscious security trade-offs.
# Each suppression includes a reason so auditors understand the decision.
cdk_nag.NagSuppressions.add_stack_suppressions(
    stack,
    [
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-IAM4",
            reason="AWSLambdaBasicExecutionRole is AWS-recommended for Lambda CloudWatch logging",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-IAM5",
            reason="Wildcard resources required for dynamically-created Cognito pools, "
            "AgentCore runtimes, and Bedrock model invocations",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-S1",
            reason="S3 access logging deferred to production hardening phase",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-CFR1",
            reason="CloudFront geo restrictions not required — internal development tool",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-CFR4",
            reason="Using CloudFront default certificate — custom domain with ACM planned for production",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-APIG1",
            reason="API Gateway access logging planned for production — using Lambda CloudWatch logs",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-APIG4",
            reason="JWT authorizer on all /api/* routes; /health is intentionally unauthenticated",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-COG2",
            reason="MFA enforced at the IdP for FederateOIDC SSO logins; Cognito-native MFA "
            "would be redundant for this internal development tool",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-COG4",
            reason="Cognito JWT authorizer on all /api/* routes; /health is intentionally unauthenticated",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-COG8",
            reason="Cognito Plus tier (advanced security) not required for this internal "
            "development tool; upstream IdP provides threat protection",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-L1",
            reason="Using Python 3.12 for CDK Lambda construct stability",
        ),
        cdk_nag.NagPackSuppression(
            id="AwsSolutions-SF1",
            reason="Step Functions logs ERROR-level events; ALL-level logging planned for production",
        ),
    ],
    apply_to_nested_stacks=True,
)

app.synth()
