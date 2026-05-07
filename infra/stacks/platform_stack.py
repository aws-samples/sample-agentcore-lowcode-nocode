"""Serverless CDK stack for the AgentCore Visual Workflow Platform.

Replaces the ECS Fargate + ALB architecture with:
- API Gateway HTTP API
- Lambda functions (workflow, deployment, step handlers)
- Step Functions state machine for deployment orchestration
- DynamoDB tables (workflows + deployments)
- S3 + CloudFront for frontend
- Least-privilege IAM roles

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5
"""

import os

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Size
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as apigw_authorizers
from aws_cdk import aws_apigatewayv2_integrations as apigw_integrations
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as sfn_tasks
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


class PlatformStack(cdk.Stack):
    """CDK stack defining all serverless resources for the platform."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_name: str,
        project_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cdk.Tags.of(self).add("Environment", environment_name)
        cdk.Tags.of(self).add("Project", project_name)

        self._env = environment_name
        self._project = project_name

        # --- Storage ---
        self.workflows_table = self._create_workflows_table()
        self.deployments_table = self._create_deployments_table()
        self.flows_table = self._create_flows_table()
        self.triggers_table = self._create_triggers_table()
        self.trigger_invocations_table = self._create_trigger_invocations_table()
        self.approvals_table = self._create_approvals_table()
        self.versions_table = self._create_versions_table()
        self.a2a_configs_table = self._create_a2a_configs_table()
        self.a2a_tasks_table = self._create_a2a_tasks_table()
        self.logging_bucket = self._create_logging_bucket()
        self.artifacts_bucket = self._create_artifacts_bucket()
        self._upload_agentcore_deps()

        # --- SSM Parameters ---
        self._create_ssm_parameters()

        # --- Lambda code asset (shared by all Lambdas) ---
        self.backend_code = self._get_backend_code()

        # --- Trigger infrastructure (Scheduler group + router Lambda + roles) ---
        self.trigger_schedule_group = self._create_trigger_schedule_group()
        self.trigger_router_lambda = self._create_trigger_router_lambda()
        self.trigger_scheduler_role = self._create_trigger_scheduler_role()

        # --- Lambda Functions ---
        self.workflow_lambda = self._create_workflow_lambda()
        self.deployment_lambda = self._create_deployment_lambda()
        self.step_lambdas = self._create_step_lambdas()

        # --- Step Functions ---
        self.state_machine = self._create_state_machine()

        # --- Grant deployment Lambda permission to start executions ---
        self.state_machine.grant_start_execution(self.deployment_lambda)

        # --- API Gateway ---
        self.user_pool, self.user_pool_client = self._create_cognito()
        self.api = self._create_api_gateway()

        # --- S3 + CloudFront + WAF ---
        self.web_acl = self._create_waf_web_acl()
        self.bucket = self._create_s3_bucket()
        self.distribution = self._create_cloudfront_distribution()

        # --- Post-creation: add CloudFront URL to API Gateway CORS ---
        self._add_cloudfront_cors_origin()

        # --- CloudWatch Alarms ---
        self._create_lambda_alarms()

        # --- Update SSM with runtime URLs ---
        self._create_runtime_ssm_parameters()

        # --- Stack Outputs ---
        self._create_stack_outputs()

    # ------------------------------------------------------------------
    # DynamoDB Tables
    # ------------------------------------------------------------------

    def _create_workflows_table(self) -> dynamodb.Table:
        """Create DynamoDB table for workflow storage (kept from previous arch).

        Requirements: 7.1
        """
        return dynamodb.Table(
            self,
            "WorkflowsTable",
            table_name=f"{self._project}-{self._env}-workflows",
            partition_key=dynamodb.Attribute(
                name="workflow_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

    def _create_deployments_table(self) -> dynamodb.Table:
        """Create DynamoDB table for deployment state with TTL and GSI.

        Requirements: 4.1, 4.2, 4.3, 7.1
        """
        table = dynamodb.Table(
            self,
            "DeploymentsTable",
            table_name=f"{self._project}-{self._env}-deployments",
            partition_key=dynamodb.Attribute(
                name="deployment_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )
        table.add_global_secondary_index(
            index_name="workflow_id-index",
            partition_key=dynamodb.Attribute(
                name="workflow_id",
                type=dynamodb.AttributeType.STRING,
            ),
        )
        table.add_global_secondary_index(
            index_name="user_id-index",
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING,
            ),
        )
        return table

    def _create_flows_table(self) -> dynamodb.Table:
        """Create DynamoDB table for named, saveable flow persistence.

        Requirements: 7.1
        """
        return dynamodb.Table(
            self,
            "FlowsTable",
            table_name=f"{self._project}-{self._env}-flows",
            partition_key=dynamodb.Attribute(
                name="flow_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

    def _create_triggers_table(self) -> dynamodb.Table:
        """DynamoDB table for agent triggers (Task 01)."""
        table = dynamodb.Table(
            self,
            "TriggersTable",
            table_name=f"{self._project}-{self._env}-triggers",
            partition_key=dynamodb.Attribute(
                name="trigger_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )
        table.add_global_secondary_index(
            index_name="user_id-index",
            partition_key=dynamodb.Attribute(
                name="user_id", type=dynamodb.AttributeType.STRING
            ),
        )
        table.add_global_secondary_index(
            index_name="deployment_id-index",
            partition_key=dynamodb.Attribute(
                name="deployment_id", type=dynamodb.AttributeType.STRING
            ),
        )
        return table

    def _create_trigger_invocations_table(self) -> dynamodb.Table:
        """Append-only history of trigger executions. Entries expire via TTL (90d)."""
        return dynamodb.Table(
            self,
            "TriggerInvocationsTable",
            table_name=f"{self._project}-{self._env}-trigger-invocations",
            partition_key=dynamodb.Attribute(
                name="trigger_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="invoked_at", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

    def _create_versions_table(self) -> dynamodb.Table:
        """DynamoDB table for agent version snapshots (Task 03).

        PK=deployment_id, SK=version(Number). Append-only history.
        """
        return dynamodb.Table(
            self,
            "VersionsTable",
            table_name=f"{self._project}-{self._env}-versions",
            partition_key=dynamodb.Attribute(
                name="deployment_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="version", type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

    def _create_a2a_configs_table(self) -> dynamodb.Table:
        """A2A per-deployment config (Task 05). PK=deployment_id."""
        return dynamodb.Table(
            self,
            "A2AConfigsTable",
            table_name=f"{self._project}-{self._env}-a2a-configs",
            partition_key=dynamodb.Attribute(
                name="deployment_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

    def _create_a2a_tasks_table(self) -> dynamodb.Table:
        """A2A task lifecycle (Task 05). PK=task_id, TTL 30d."""
        return dynamodb.Table(
            self,
            "A2ATasksTable",
            table_name=f"{self._project}-{self._env}-a2a-tasks",
            partition_key=dynamodb.Attribute(
                name="task_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

    def _create_approvals_table(self) -> dynamodb.Table:
        """DynamoDB table for human-in-the-loop approval requests (Task 02)."""
        table = dynamodb.Table(
            self,
            "ApprovalsTable",
            table_name=f"{self._project}-{self._env}-approvals",
            partition_key=dynamodb.Attribute(
                name="approval_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )
        table.add_global_secondary_index(
            index_name="user_id-index",
            partition_key=dynamodb.Attribute(
                name="user_id", type=dynamodb.AttributeType.STRING
            ),
        )
        table.add_global_secondary_index(
            index_name="deployment_id-index",
            partition_key=dynamodb.Attribute(
                name="deployment_id", type=dynamodb.AttributeType.STRING
            ),
        )
        return table

    # ------------------------------------------------------------------
    # Trigger infrastructure
    # ------------------------------------------------------------------

    def _create_trigger_schedule_group(self) -> scheduler.CfnScheduleGroup:
        """Dedicated EventBridge Scheduler group for our triggers."""
        return scheduler.CfnScheduleGroup(
            self,
            "TriggerScheduleGroup",
            name=f"{self._project}-{self._env}-triggers",
        )

    def _create_trigger_router_lambda(self) -> _lambda.Function:
        """Lambda invoked by Scheduler and EventBridge when a trigger fires.

        It reads the trigger config from DynamoDB and invokes the target
        AgentCore runtime via the data-plane API.
        """
        role = iam.Role(
            self,
            "TriggerRouterLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )
        self.triggers_table.grant_read_write_data(role)
        self.trigger_invocations_table.grant_read_write_data(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore-control:GetAgentRuntime",
                ],
                resources=["*"],  # runtime ARN is user-provided per trigger
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:GetCallerIdentity"],
                resources=["*"],
            )
        )

        fn = _lambda.Function(
            self,
            "TriggerRouterLambda",
            function_name=f"{self._project}-{self._env}-trigger-router",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="src/app/trigger_router_handler.handler",
            code=self.backend_code,
            memory_size=256,
            timeout=Duration.seconds(60),
            role=role,
            tracing=_lambda.Tracing.ACTIVE,
            environment={
                "TRIGGERS_TABLE_NAME": self.triggers_table.table_name,
                "TRIGGER_INVOCATIONS_TABLE_NAME": self.trigger_invocations_table.table_name,
                "ENVIRONMENT": self._env,
                "APP_AWS_REGION": self.region,
                "PYTHONPATH": "/var/task/src:/var/task:/var/task/lib",
            },
            log_group=logs.LogGroup(
                self,
                "TriggerRouterLambdaLogGroup",
                log_group_name=f"/aws/lambda/{self._project}-{self._env}-trigger-router",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        return fn

    def _create_trigger_scheduler_role(self) -> iam.Role:
        """Role assumed by EventBridge Scheduler to invoke the router Lambda."""
        role = iam.Role(
            self,
            "TriggerSchedulerInvokeRole",
            assumed_by=iam.ServicePrincipal(
                "scheduler.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[self.trigger_router_lambda.function_arn],
            )
        )
        return role

    # ------------------------------------------------------------------
    # SSM Parameters
    # ------------------------------------------------------------------

    def _create_ssm_parameters(self) -> None:
        """Create SSM parameters under /agentcore-workflow/{env}/ path.

        Requirements: 7.5
        """
        prefix = f"/agentcore-workflow/{self._env}"

        ssm.StringParameter(
            self,
            "CorsOriginsParam",
            parameter_name=f"{prefix}/cors-origins",
            string_value="http://localhost:5173",
            description="Allowed CORS origins for the backend API",
        )

        ssm.StringParameter(
            self,
            "AwsRegionParam",
            parameter_name=f"{prefix}/aws-region",
            string_value=self.region,
            description="AWS region for the platform",
        )

        ssm.StringParameter(
            self,
            "WorkflowsTableNameParam",
            parameter_name=f"{prefix}/dynamodb-table-name",
            string_value=self.workflows_table.table_name,
            description="DynamoDB table name for workflow storage",
        )

        ssm.StringParameter(
            self,
            "DeploymentsTableNameParam",
            parameter_name=f"{prefix}/deployments-table-name",
            string_value=self.deployments_table.table_name,
            description="DynamoDB table name for deployment state",
        )

        ssm.StringParameter(
            self,
            "FlowsTableNameParam",
            parameter_name=f"{prefix}/dynamodb-flows-table-name",
            string_value=self.flows_table.table_name,
            description="DynamoDB table name for flow persistence",
        )

    def _create_runtime_ssm_parameters(self) -> None:
        """Create SSM parameters that depend on runtime resources (API GW URL)."""
        prefix = f"/agentcore-workflow/{self._env}"

        ssm.StringParameter(
            self,
            "ApiGatewayUrlParam",
            parameter_name=f"{prefix}/api-gateway-url",
            string_value=self.api.url or "",
            description="API Gateway HTTP API URL",
        )

    # ------------------------------------------------------------------
    # Lambda Code Asset
    # ------------------------------------------------------------------

    def _get_backend_code(self) -> _lambda.Code:
        """Package the backend source as a Lambda code asset with bundled dependencies.

        Dependencies are pre-installed into backend/lib/ by the deploy script
        (pip install -r requirements-lambda.txt -t backend/lib/).
        The asset includes both src/ and lib/ directories.
        """
        backend_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
        return _lambda.Code.from_asset(
            backend_path,
            exclude=[
                ".venv",
                "__pycache__",
                ".pytest_cache",
                ".hypothesis",
                "tests",
                ".git",
                ".env",
                "build",
                "*.pyc",
            ],
        )

    # ------------------------------------------------------------------
    # Lambda Functions
    # ------------------------------------------------------------------

    def _create_artifacts_bucket(self) -> s3.Bucket:
        """Create S3 bucket for deployment code artifacts."""
        return s3.Bucket(
            self,
            "ArtifactsBucket",
            bucket_name=f"{self._project}-{self._env}-artifacts-{self.region}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="s3-artifacts/",
            lifecycle_rules=[
                s3.LifecycleRule(expiration=Duration.days(90), prefix="deployments/"),
            ],
        )

    def _upload_agentcore_deps(self) -> None:
        """Upload pre-built aarch64 dependency bundles to S3 artifacts bucket.

        Uses s3_deployment.BucketDeployment to sync backend/agentcore-deps/*.zip
        to s3://{artifacts_bucket}/agentcore-deps/

        Gracefully skips if the bundle directory does not exist (e.g. local dev).

        Requirements: 2.1, 2.2, 2.3
        """
        deps_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "agentcore-deps"))
        if not os.path.isdir(deps_path):
            return

        s3_deployment.BucketDeployment(
            self,
            "AgentCoreDepsDeployment",
            sources=[s3_deployment.Source.asset(deps_path)],
            destination_bucket=self.artifacts_bucket,
            destination_key_prefix="agentcore-deps",
            memory_limit=512,
            ephemeral_storage_size=Size.mebibytes(1024),
        )

    def _create_workflow_lambda(self) -> _lambda.Function:
        """Create Workflow Lambda (FastAPI + Mangum) for CRUD operations.

        Requirements: 1.1, 1.5, 6.1
        """
        role = iam.Role(
            self,
            "WorkflowLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        # DynamoDB workflows table: read/write
        self.workflows_table.grant_read_write_data(role)
        # DynamoDB flows table: read/write
        self.flows_table.grant_read_write_data(role)
        # DynamoDB triggers tables: read/write
        self.triggers_table.grant_read_write_data(role)
        self.trigger_invocations_table.grant_read_write_data(role)
        # Approvals table: read/write (Task 02)
        self.approvals_table.grant_read_write_data(role)
        # Versions table: read/write (Task 03)
        self.versions_table.grant_read_write_data(role)
        # A2A tables: read/write (Task 05)
        self.a2a_configs_table.grant_read_write_data(role)
        self.a2a_tasks_table.grant_read_write_data(role)
        # SSM read for app config
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath",
                ],
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/agentcore-workflow/{self._env}/*"],
            )
        )

        # --- Trigger management permissions ---
        # EventBridge Scheduler
        schedule_group_arn = (
            f"arn:aws:scheduler:{self.region}:{self.account}:schedule-group/"
            f"{self._project}-{self._env}-triggers"
        )
        schedule_arn_pattern = (
            f"arn:aws:scheduler:{self.region}:{self.account}:schedule/"
            f"{self._project}-{self._env}-triggers/*"
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "scheduler:CreateSchedule",
                    "scheduler:UpdateSchedule",
                    "scheduler:DeleteSchedule",
                    "scheduler:GetSchedule",
                    "scheduler:ListSchedules",
                ],
                resources=[schedule_arn_pattern, schedule_group_arn],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["scheduler:GetScheduleGroup", "scheduler:CreateScheduleGroup"],
                resources=[schedule_group_arn],
            )
        )
        # EventBridge rules (default bus)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "events:PutRule",
                    "events:DeleteRule",
                    "events:DescribeRule",
                    "events:DisableRule",
                    "events:EnableRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:ListTargetsByRule",
                ],
                resources=[
                    f"arn:aws:events:{self.region}:{self.account}:rule/"
                    f"{self._project}-{self._env}-*"
                ],
            )
        )
        # Secrets Manager for webhook HMAC secrets
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:CreateSecret",
                    "secretsmanager:UpdateSecret",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:TagResource",
                ],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:"
                    f"/agentcore/{self._env}/trigger-webhook/*"
                ],
            )
        )
        # Pass the scheduler role to EventBridge Scheduler (for schedule targets)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[self.trigger_scheduler_role.role_arn],
                conditions={
                    "StringEquals": {
                        "iam:PassedToService": "scheduler.amazonaws.com"
                    }
                },
            )
        )
        # Manage Lambda resource policy so EventBridge rules can invoke the router
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:AddPermission", "lambda:RemovePermission"],
                resources=[self.trigger_router_lambda.function_arn],
            )
        )
        # Invoke AgentCore runtime for manual "test trigger" requests
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "sts:GetCallerIdentity",
                ],
                resources=["*"],
            )
        )
        # CloudWatch for analytics dashboard (Task 04). GetMetric* actions
        # only support Resource=* — CloudWatch scopes by namespace inside the
        # call, which we always pin to AgentCore/Agents.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:GetMetricData",
                    "cloudwatch:ListMetrics",
                ],
                resources=["*"],
            )
        )

        fn = _lambda.Function(
            self,
            "WorkflowLambda",
            function_name=f"{self._project}-{self._env}-workflow",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="src/app/lambda_handler.handler",
            code=self.backend_code,
            memory_size=512,
            timeout=Duration.seconds(30),
            role=role,
            tracing=_lambda.Tracing.ACTIVE,
            environment={
                "DYNAMODB_TABLE_NAME": self.workflows_table.table_name,
                "DYNAMODB_FLOWS_TABLE_NAME": self.flows_table.table_name,
                "TRIGGERS_TABLE_NAME": self.triggers_table.table_name,
                "TRIGGER_INVOCATIONS_TABLE_NAME": self.trigger_invocations_table.table_name,
                "TRIGGER_SCHEDULE_GROUP": f"{self._project}-{self._env}-triggers",
                "TRIGGER_SCHEDULER_ROLE_ARN": self.trigger_scheduler_role.role_arn,
                "TRIGGER_ROUTER_LAMBDA_ARN": self.trigger_router_lambda.function_arn,
                "TRIGGER_SECRET_PREFIX": f"/agentcore/{self._env}/trigger-webhook",
                "APPROVALS_TABLE_NAME": self.approvals_table.table_name,
                "VERSIONS_TABLE_NAME": self.versions_table.table_name,
                "A2A_CONFIGS_TABLE_NAME": self.a2a_configs_table.table_name,
                "A2A_TASKS_TABLE_NAME": self.a2a_tasks_table.table_name,
                "PROJECT_NAME": self._project,
                "ENVIRONMENT": self._env,
                "APP_AWS_REGION": self.region,
                "POWERTOOLS_SERVICE_NAME": "workflow",
                "PYTHONPATH": "/var/task/src:/var/task:/var/task/lib",
            },
            log_group=logs.LogGroup(
                self,
                "WorkflowLambdaLogGroup",
                log_group_name=f"/aws/lambda/{self._project}-{self._env}-workflow",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        return fn

    def _create_deployment_lambda(self) -> _lambda.Function:
        """Create Deployment Lambda for deploy/status/test/delete operations.

        Requirements: 1.2, 6.2
        """
        role = iam.Role(
            self,
            "DeploymentLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        # DynamoDB deployments table: read/write
        self.deployments_table.grant_read_write_data(role)
        # states:StartExecution on the state machine (granted after SM creation)
        # SSM read
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath",
                ],
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/agentcore-workflow/{self._env}/*"],
            )
        )
        # bedrock-agentcore for test-runtime invocation and runtime deletion
        # Wildcards required — AgentCore IAM action prefixes are not stable.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock-agentcore:*",
                    "bedrock-agentcore-control:*",
                ],
                resources=["*"],
            )
        )
        # Cleanup permissions: Cognito, Lambda, STS (needed by delete handler)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:DeleteUserPool",
                    "cognito-idp:DeleteUserPoolClient",
                    "cognito-idp:DeleteUserPoolDomain",
                    "cognito-idp:DescribeUserPool",
                ],
                resources=[f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:GetCallerIdentity"],
                resources=["*"],
            )
        )
        # Tool tester + custom tool cleanup: create/invoke/delete Lambdas + IAM roles
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "iam:CreateRole",
                    "iam:GetRole",
                    "iam:AttachRolePolicy",
                    "iam:PassRole",
                    "iam:DetachRolePolicy",
                    "iam:DeleteRole",
                    "iam:ListAttachedRolePolicies",
                ],
                resources=[f"arn:aws:iam::{self.account}:role/AgentCore*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "lambda:CreateFunction",
                    "lambda:GetFunction",
                    "lambda:InvokeFunction",
                    "lambda:DeleteFunction",
                ],
                resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:AgentCore*"],
            )
        )
        # S3 artifacts bucket: read/write for CFN template generation
        self.artifacts_bucket.grant_read_write(role)

        fn = _lambda.Function(
            self,
            "DeploymentLambda",
            function_name=f"{self._project}-{self._env}-deployment",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="src/app/deployment_handler.handler",
            code=self.backend_code,
            memory_size=512,
            timeout=Duration.seconds(120),
            role=role,
            tracing=_lambda.Tracing.ACTIVE,
            environment={
                "DEPLOYMENTS_TABLE_NAME": self.deployments_table.table_name,
                "DEPLOYMENT_TABLE_NAME": self.deployments_table.table_name,
                "WORKFLOWS_TABLE_NAME": self.workflows_table.table_name,
                "ARTIFACTS_BUCKET_NAME": self.artifacts_bucket.bucket_name,
                "ENVIRONMENT": self._env,
                "APP_AWS_REGION": self.region,
                "POWERTOOLS_SERVICE_NAME": "deployment",
                "TOOL_GENERATOR_MODEL_ID": f"{'eu' if self.region.startswith('eu-') else 'ap' if self.region.startswith('ap-') else 'us'}.anthropic.claude-sonnet-4-20250514-v1:0",
                "PYTHONPATH": "/var/task/src:/var/task:/var/task/lib",
            },
            log_group=logs.LogGroup(
                self,
                "DeploymentLambdaLogGroup",
                log_group_name=f"/aws/lambda/{self._project}-{self._env}-deployment",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        return fn

    def _create_step_role(self, step_name: str) -> iam.Role:
        """Create a dedicated IAM role for a step Lambda (1:1 relationship)."""
        role = iam.Role(
            self,
            f"Step{step_name.title().replace('_', '')}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        self.deployments_table.grant_read_write_data(role)
        self.workflows_table.grant_read_data(role)
        self.artifacts_bucket.grant_read_write(role)
        role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/agentcore-workflow/{self._env}/*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "iam:CreateRole", "iam:AttachRolePolicy", "iam:PutRolePolicy", "iam:GetRole",
                "iam:PassRole", "iam:DeleteRole", "iam:DetachRolePolicy", "iam:DeleteRolePolicy",
                "iam:ListAttachedRolePolicies", "iam:ListRolePolicies",
            ],
            resources=[f"arn:aws:iam::{self.account}:role/AgentCore*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=["iam:CreateServiceLinkedRole"],
            resources=[f"arn:aws:iam::{self.account}:role/aws-service-role/*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
                "lambda:DeleteFunction", "lambda:GetFunction", "lambda:InvokeFunction",
                "lambda:AddPermission", "lambda:RemovePermission",
            ],
            resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:*"],
        ))
        # CreateUserPool does not support resource-level permissions
        role.add_to_policy(iam.PolicyStatement(
            actions=["cognito-idp:CreateUserPool"],
            resources=["*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "cognito-idp:DeleteUserPool", "cognito-idp:CreateUserPoolClient",
                "cognito-idp:DescribeUserPool", "cognito-idp:AdminCreateUser", "cognito-idp:AdminSetUserPassword",
                "cognito-idp:AdminInitiateAuth", "cognito-idp:CreateResourceServer",
                "cognito-idp:CreateUserPoolDomain", "cognito-idp:DeleteUserPoolClient",
                "cognito-idp:DeleteUserPoolDomain",
            ],
            resources=[f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
                "bedrock:CreateKnowledgeBase", "bedrock:GetKnowledgeBase", "bedrock:ListKnowledgeBases",
                "bedrock:DeleteKnowledgeBase", "bedrock:CreateDataSource", "bedrock:DeleteDataSource",
                "bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:ListFoundationModels",
                "bedrock:Retrieve", "bedrock:RetrieveAndGenerate",
                # Guardrails API actions
                "bedrock:CreateGuardrail", "bedrock:GetGuardrail", "bedrock:ListGuardrails",
                "bedrock:UpdateGuardrail", "bedrock:DeleteGuardrail", "bedrock:CreateGuardrailVersion",
                "bedrock-agentcore:*", "bedrock-agentcore-control:*",
            ],
            resources=["*"],
        ))
        role.add_to_policy(iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"]))
        role.add_to_policy(iam.PolicyStatement(actions=["sts:GetCallerIdentity"], resources=["*"]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:CreateSecret", "secretsmanager:DeleteSecret",
                     "secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"],
            resources=["*"],
        ))
        return role

    def _create_step_lambdas(self) -> dict[str, _lambda.Function]:
        """Create individual Lambda functions for each Step Functions step.

        Requirements: 1.3, 6.3
        """
        step_configs = {
            "validate": {
                "handler": "src/app/step_handlers/validate_step.handler",
                "memory": 256,
                "timeout": 30,
            },
            "codegen": {
                "handler": "src/app/step_handlers/codegen_step.handler",
                "memory": 1024,
                "timeout": 90,
            },
            "iam": {
                "handler": "src/app/step_handlers/iam_step.handler",
                "memory": 256,
                "timeout": 60,
            },
            "mcp_server": {
                "handler": "src/app/step_handlers/mcp_server_step.handler",
                "memory": 1024,
                "timeout": 600,
            },
            "gateway": {
                "handler": "src/app/step_handlers/gateway_step.handler",
                "memory": 512,
                "timeout": 300,
            },
            "runtime_configure": {
                "handler": "src/app/step_handlers/runtime_configure_step.handler",
                "memory": 512,
                "timeout": 60,
            },
            "runtime_launch": {
                "handler": "src/app/step_handlers/runtime_launch_step.handler",
                "memory": 512,
                "timeout": 600,
            },
            "auth": {
                "handler": "src/app/step_handlers/auth_step.handler",
                "memory": 256,
                "timeout": 60,
            },
            "status_update": {
                "handler": "src/app/step_handlers/status_update_step.handler",
                "memory": 256,
                "timeout": 15,
            },
            "memory": {
                "handler": "src/app/step_handlers/memory_step.handler",
                "memory": 512,
                "timeout": 120,
            },
            "evaluation": {
                "handler": "src/app/step_handlers/evaluation_step.handler",
                "memory": 512,
                "timeout": 120,
            },
            "policy": {
                "handler": "src/app/step_handlers/policy_step.handler",
                "memory": 512,
                "timeout": 120,
            },
            "knowledge_base": {
                "handler": "src/app/step_handlers/knowledge_base_step.handler",
                "memory": 1024,
                "timeout": 600,
            },
            "guardrails": {
                "handler": "src/app/step_handlers/guardrails_step.handler",
                "memory": 512,
                "timeout": 120,
            },
        }

        lambdas: dict[str, _lambda.Function] = {}
        for step_name, config in step_configs.items():
            step_role = self._create_step_role(step_name)
            fn = _lambda.Function(
                self,
                f"Step{step_name.title().replace('_', '')}Lambda",
                function_name=f"{self._project}-{self._env}-step-{step_name.replace('_', '-')}",
                runtime=_lambda.Runtime.PYTHON_3_12,
                handler=config["handler"],
                code=self.backend_code,
                memory_size=config["memory"],
                timeout=Duration.seconds(config["timeout"]),
                role=step_role,
                tracing=_lambda.Tracing.ACTIVE,
                environment={
                    "DEPLOYMENTS_TABLE_NAME": self.deployments_table.table_name,
                    "DEPLOYMENT_TABLE_NAME": self.deployments_table.table_name,
                    "WORKFLOWS_TABLE_NAME": self.workflows_table.table_name,
                    "ARTIFACTS_BUCKET_NAME": self.artifacts_bucket.bucket_name,
                    "ENVIRONMENT": self._env,
                    "APP_AWS_REGION": self.region,
                    "PYTHONPATH": "/var/task/src:/var/task:/var/task/lib",
                },
                log_group=logs.LogGroup(
                    self,
                    f"Step{step_name.title().replace('_', '')}LogGroup",
                    log_group_name=f"/aws/lambda/{self._project}-{self._env}-step-{step_name.replace('_', '-')}",
                    retention=logs.RetentionDays.ONE_MONTH,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            )
            lambdas[step_name] = fn

        return lambdas

    # ------------------------------------------------------------------
    # Step Functions State Machine
    # ------------------------------------------------------------------

    def _create_state_machine(self) -> sfn.StateMachine:
        """Create Step Functions state machine for deployment orchestration.

        Retry: 3 attempts with exponential backoff (2s, 4s, 8s)
        Catch: fallback to failure handler writing error to DynamoDB
        Per-step timeouts per design table
        Overall timeout: 30 minutes

        Requirements: 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.1
        """
        # Failure handler — writes error to DynamoDB
        failure_handler = self._create_step_task(
            "StatusUpdateFailure",
            self.step_lambdas["status_update"],
            timeout_seconds=15,
            result_path="$.failure_result",
        )
        failure_handler.add_retry(**self._retry_kwargs())
        fail_state = sfn.Fail(self, "DeploymentFailed", cause="Deployment failed", error="DeploymentError")
        failure_handler.next(fail_state)

        # --- Define steps ---
        # Each step handler returns {**event, ...new_fields} so we use result_path="$"
        # to replace the entire state, allowing fields to accumulate across steps.
        validate = self._create_step_task(
            "ValidateWorkflow",
            self.step_lambdas["validate"],
            timeout_seconds=30,
            result_path="$",
        )
        validate.add_retry(**self._retry_kwargs())
        validate.add_catch(**self._catch_kwargs(failure_handler))

        guardrails = self._create_step_task(
            "CreateGuardrails",
            self.step_lambdas["guardrails"],
            timeout_seconds=120,
            result_path="$",
        )
        guardrails.add_retry(**self._retry_kwargs())
        guardrails.add_catch(**self._catch_kwargs(failure_handler))

        mcp_server = self._create_step_task(
            "DeployMCPServer",
            self.step_lambdas["mcp_server"],
            timeout_seconds=600,
            result_path="$",
        )
        mcp_server.add_retry(**self._retry_kwargs())
        mcp_server.add_catch(**self._catch_kwargs(failure_handler))

        codegen = self._create_step_task(
            "GenerateCode",
            self.step_lambdas["codegen"],
            timeout_seconds=90,
            result_path="$",
        )
        codegen.add_retry(**self._retry_kwargs())
        codegen.add_catch(**self._catch_kwargs(failure_handler))

        iam_step = self._create_step_task(
            "CreateIAMRole",
            self.step_lambdas["iam"],
            timeout_seconds=60,
            result_path="$",
        )
        iam_step.add_retry(**self._retry_kwargs())
        iam_step.add_catch(**self._catch_kwargs(failure_handler))

        gateway = self._create_step_task(
            "DeployGateway",
            self.step_lambdas["gateway"],
            timeout_seconds=300,
            result_path="$",
        )
        gateway.add_retry(**self._retry_kwargs())
        gateway.add_catch(**self._catch_kwargs(failure_handler))

        knowledge_base = self._create_step_task(
            "CreateKnowledgeBase",
            self.step_lambdas["knowledge_base"],
            timeout_seconds=600,
            result_path="$",
        )
        knowledge_base.add_retry(**self._retry_kwargs())
        knowledge_base.add_catch(**self._catch_kwargs(failure_handler))

        memory_step = self._create_step_task(
            "CreateMemory",
            self.step_lambdas["memory"],
            timeout_seconds=120,
            result_path="$",
        )
        memory_step.add_retry(**self._retry_kwargs())
        memory_step.add_catch(**self._catch_kwargs(failure_handler))

        policy_step = self._create_step_task(
            "CreatePolicy",
            self.step_lambdas["policy"],
            timeout_seconds=120,
            result_path="$",
        )
        policy_step.add_retry(**self._retry_kwargs())
        policy_step.add_catch(**self._catch_kwargs(failure_handler))

        runtime_configure = self._create_step_task(
            "ConfigureRuntime",
            self.step_lambdas["runtime_configure"],
            timeout_seconds=60,
            result_path="$",
        )
        runtime_configure.add_retry(**self._retry_kwargs())
        runtime_configure.add_catch(**self._catch_kwargs(failure_handler))

        runtime_launch = self._create_step_task(
            "LaunchRuntime",
            self.step_lambdas["runtime_launch"],
            timeout_seconds=600,
            result_path="$",
        )
        runtime_launch.add_retry(**self._retry_kwargs())
        runtime_launch.add_catch(**self._catch_kwargs(failure_handler))

        evaluation_step = self._create_step_task(
            "CreateEvaluation",
            self.step_lambdas["evaluation"],
            timeout_seconds=120,
            result_path="$",
        )
        evaluation_step.add_retry(**self._retry_kwargs())
        evaluation_step.add_catch(**self._catch_kwargs(failure_handler))

        auth = self._create_step_task(
            "ConfigureJWTAuth",
            self.step_lambdas["auth"],
            timeout_seconds=60,
            result_path="$",
        )
        auth.add_retry(**self._retry_kwargs())
        auth.add_catch(**self._catch_kwargs(failure_handler))

        status_update = self._create_step_task(
            "UpdateStatusSuccess",
            self.step_lambdas["status_update"],
            timeout_seconds=15,
            result_path="$",
        )
        status_update.add_retry(**self._retry_kwargs())
        status_update.add_catch(**self._catch_kwargs(failure_handler))

        succeed = sfn.Succeed(self, "DeploymentSucceeded")

        # --- Build chain with conditionals ---
        # Flow: validate → [mcp_server?] → [knowledge_base?] → [gateway?] → [memory?] → [policy?]
        #       → codegen → iam → configure → launch → [evaluation?] → [auth?] → status
        #
        # KB runs BEFORE gateway because deploy_gateway() reads knowledge_base_result
        # from the event to create the KB Lambda target.
        #
        # Each optional step uses a Pass state as a skip target so that
        # each Lambda task's .next() is called exactly once (CDK requirement).
        has_guardrails = sfn.Condition.is_present("$.guardrails_config")
        has_mcp_server = sfn.Condition.is_present("$.mcp_server_config")
        has_gateway = sfn.Condition.is_present("$.gateway_config")
        has_knowledge_base = sfn.Condition.is_present("$.knowledge_base_config")
        has_memory = sfn.Condition.is_present("$.memory_config")
        has_policy = sfn.Condition.is_present("$.policy_config")
        has_evaluation = sfn.Condition.is_present("$.evaluation_config")

        skip_guardrails = sfn.Pass(self, "SkipGuardrails")
        skip_mcp_server = sfn.Pass(self, "SkipMCPServer")
        skip_knowledge_base = sfn.Pass(self, "SkipKnowledgeBase")
        skip_gateway = sfn.Pass(self, "SkipGateway")
        skip_memory = sfn.Pass(self, "SkipMemory")
        skip_policy = sfn.Pass(self, "SkipPolicy")
        skip_evaluation = sfn.Pass(self, "SkipEvaluation")
        skip_auth = sfn.Pass(self, "SkipAuth")

        # validate → guardrails choice
        validate.next(sfn.Choice(self, "HasGuardrails?").when(has_guardrails, guardrails).otherwise(skip_guardrails))
        guardrails.next(skip_guardrails)

        # → mcp_server choice
        skip_guardrails.next(sfn.Choice(self, "HasMCPServer?").when(has_mcp_server, mcp_server).otherwise(skip_mcp_server))
        mcp_server.next(skip_mcp_server)  # converge after mcp_server

        # → knowledge base choice (runs before gateway so result is available)
        skip_mcp_server.next(sfn.Choice(self, "HasKnowledgeBase?").when(has_knowledge_base, knowledge_base).otherwise(skip_knowledge_base))
        knowledge_base.next(skip_knowledge_base)

        # → gateway choice (reads knowledge_base_result to create KB Lambda target)
        skip_knowledge_base.next(sfn.Choice(self, "HasGateway?").when(has_gateway, gateway).otherwise(skip_gateway))
        gateway.next(skip_gateway)  # converge after gateway

        # → memory choice
        skip_gateway.next(sfn.Choice(self, "HasMemory?").when(has_memory, memory_step).otherwise(skip_memory))
        memory_step.next(skip_memory)

        # → policy choice (only meaningful when gateway exists, but handler handles gracefully)
        skip_memory.next(sfn.Choice(self, "HasPolicy?").when(has_policy, policy_step).otherwise(skip_policy))
        policy_step.next(skip_policy)

        # → codegen → iam → configure → launch
        skip_policy.next(codegen)
        codegen.next(iam_step)
        iam_step.next(runtime_configure)
        runtime_configure.next(runtime_launch)

        # → evaluation choice
        runtime_launch.next(
            sfn.Choice(self, "HasEvaluation?").when(has_evaluation, evaluation_step).otherwise(skip_evaluation)
        )
        evaluation_step.next(skip_evaluation)

        # → auth choice (only when gateway was deployed)
        skip_evaluation.next(sfn.Choice(self, "HasGatewayForAuth?").when(has_gateway, auth).otherwise(skip_auth))
        auth.next(skip_auth)

        # → status update → succeed
        skip_auth.next(status_update)
        status_update.next(succeed)

        # State machine role
        sm_role = iam.Role(
            self,
            "StateMachineRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )
        # Grant invoke on all step lambdas
        for fn in self.step_lambdas.values():
            fn.grant_invoke(sm_role)
        # DynamoDB access for deployment state
        self.deployments_table.grant_read_write_data(sm_role)

        return sfn.StateMachine(
            self,
            "DeploymentStateMachine",
            state_machine_name=f"{self._project}-{self._env}-deployment",
            definition_body=sfn.DefinitionBody.from_chainable(validate),
            role=sm_role,
            timeout=Duration.minutes(30),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(
                    self,
                    "StateMachineLogGroup",
                    log_group_name=f"/stepfunctions/{self._project}-{self._env}/deployment",
                    retention=logs.RetentionDays.ONE_MONTH,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
                level=sfn.LogLevel.ERROR,
            ),
        )

    def _create_step_task(
        self,
        id: str,
        fn: _lambda.Function,
        *,
        timeout_seconds: int,
        result_path: str,
    ) -> sfn_tasks.LambdaInvoke:
        """Create a Step Functions LambdaInvoke task with payload passthrough."""
        return sfn_tasks.LambdaInvoke(
            self,
            id,
            lambda_function=fn,
            payload_response_only=True,
            result_path=result_path,
            task_timeout=sfn.Timeout.duration(Duration.seconds(timeout_seconds)),
        )

    @staticmethod
    def _retry_kwargs() -> dict:
        """Return retry configuration kwargs for add_retry()."""
        return {
            "errors": ["States.TaskFailed", "States.Timeout"],
            "interval": Duration.seconds(2),
            "max_attempts": 3,
            "backoff_rate": 2.0,
        }

    @staticmethod
    def _catch_kwargs(handler: sfn_tasks.LambdaInvoke) -> dict:
        """Return catch configuration kwargs for add_catch()."""
        return {
            "handler": handler,
            "result_path": "$.error_info",
        }

    # ------------------------------------------------------------------
    # Cognito Authentication
    # ------------------------------------------------------------------

    def _create_cognito(self) -> tuple:
        """Create Cognito User Pool, client, and pre-set users."""
        pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"{self._project}-{self._env}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            standard_threat_protection_mode=cognito.StandardThreatProtectionMode.FULL_FUNCTION,
            removal_policy=RemovalPolicy.DESTROY,
        )

        client = pool.add_client(
            "FrontendClient",
            user_pool_client_name=f"{self._project}-{self._env}-frontend",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(7),
        )

        # Pre-create users from context (comma-separated string via env var)
        cognito_users_raw = self.node.try_get_context("cognito_users") or ""
        cognito_users = [e.strip() for e in cognito_users_raw.split(",") if e.strip()] if isinstance(cognito_users_raw, str) else cognito_users_raw
        for email in cognito_users:
            cognito.CfnUserPoolUser(
                self,
                f"User-{email.replace('@', '-at-').replace('.', '-')}",
                user_pool_id=pool.user_pool_id,
                username=email,
                desired_delivery_mediums=["EMAIL"],
                user_attributes=[
                    cognito.CfnUserPoolUser.AttributeTypeProperty(
                        name="email", value=email,
                    ),
                    cognito.CfnUserPoolUser.AttributeTypeProperty(
                        name="email_verified", value="true",
                    ),
                ],
            )

        return pool, client

    # ------------------------------------------------------------------
    # API Gateway HTTP API
    # ------------------------------------------------------------------

    def _create_api_gateway(self) -> apigwv2.HttpApi:
        """Create API Gateway HTTP API with route mappings and CORS.

        Routes:
        - /api/workflows/* → Workflow Lambda
        - /api/deploy, /api/test-runtime, /api/runtime/* → Deployment Lambda
        - /health → Workflow Lambda

        Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
        """
        # CORS origins: localhost for local development. CloudFront distribution
        # URL is added post-construction by _add_cloudfront_cors_origin() since
        # the distribution is created after the API. Browsers send CORS preflight
        # for requests with Authorization headers even on same-origin via CloudFront.
        api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"{self._project}-{self._env}-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["http://localhost:5173"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.PUT,
                    apigwv2.CorsHttpMethod.DELETE,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                ],
                max_age=Duration.minutes(5),
            ),
        )

        # Workflow Lambda integration
        workflow_integration = apigw_integrations.HttpLambdaIntegration("WorkflowIntegration", self.workflow_lambda)

        # Deployment Lambda integration
        deployment_integration = apigw_integrations.HttpLambdaIntegration(
            "DeploymentIntegration", self.deployment_lambda
        )

        # JWT Authorizer (Cognito)
        jwt_authorizer = apigw_authorizers.HttpJwtAuthorizer(
            "CognitoAuthorizer",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool.user_pool_id}",
            jwt_audience=[self.user_pool_client.user_pool_client_id],
        )

        # --- Workflow routes ---
        api.add_routes(
            path="/api/workflows",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/workflows/{proxy+}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.PUT,
                apigwv2.HttpMethod.DELETE,
                apigwv2.HttpMethod.POST,
            ],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )

        # --- Flow routes ---
        api.add_routes(
            path="/api/flows",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/flows/{proxy+}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.PUT,
                apigwv2.HttpMethod.DELETE,
            ],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )

        # --- Deployment routes ---
        api.add_routes(
            path="/api/deploy",
            methods=[apigwv2.HttpMethod.POST],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/deploy/{proxy+}",
            methods=[apigwv2.HttpMethod.GET],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/deployments",
            methods=[apigwv2.HttpMethod.GET],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/test-runtime",
            methods=[apigwv2.HttpMethod.POST],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/test-runtime-stream",
            methods=[apigwv2.HttpMethod.POST],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/runtime/{proxy+}",
            methods=[apigwv2.HttpMethod.DELETE, apigwv2.HttpMethod.GET],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/generate-tool",
            methods=[apigwv2.HttpMethod.POST],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/generate-tool/{jobId}",
            methods=[apigwv2.HttpMethod.GET],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/test-tool",
            methods=[apigwv2.HttpMethod.POST],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/test-tool/{testId}",
            methods=[apigwv2.HttpMethod.GET],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/generate-cfn-template",
            methods=[apigwv2.HttpMethod.POST],
            integration=deployment_integration,
            authorizer=jwt_authorizer,
        )

        # --- Trigger routes (authenticated) ---
        api.add_routes(
            path="/api/triggers",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/triggers/{proxy+}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.PUT,
                apigwv2.HttpMethod.DELETE,
                apigwv2.HttpMethod.POST,
            ],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )

        # --- Webhook route (public, HMAC-verified in Lambda) ---
        api.add_routes(
            path="/api/webhooks/{webhook_path}",
            methods=[apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            # intentionally no authorizer: verified via HMAC in the Lambda
        )

        # --- Approval routes (Task 02) ---
        api.add_routes(
            path="/api/approvals",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/approvals/{proxy+}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
            ],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )

        # --- Version routes (Task 03) ---
        api.add_routes(
            path="/api/deployments/{deployment_id}/versions",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/deployments/{deployment_id}/versions/{proxy+}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
            ],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )

        # --- Analytics routes (Task 04) ---
        api.add_routes(
            path="/api/analytics/{deployment_id}/{proxy+}",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )

        # --- A2A config routes (Task 05, authenticated) ---
        api.add_routes(
            path="/api/a2a/config",
            methods=[apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        api.add_routes(
            path="/api/a2a/config/{deployment_id}",
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.DELETE,
            ],
            integration=workflow_integration,
            authorizer=jwt_authorizer,
        )
        # --- Public A2A routes: agent card + JSON-RPC ---
        api.add_routes(
            path="/.well-known/agents/{deployment_id}",
            methods=[apigwv2.HttpMethod.GET],
            integration=workflow_integration,
        )
        api.add_routes(
            path="/a2a/{deployment_id}",
            methods=[apigwv2.HttpMethod.POST],
            integration=workflow_integration,
        )

        # --- Health check route ---
        api.add_routes(
            path="/health",
            methods=[apigwv2.HttpMethod.GET],
            integration=workflow_integration,
        )

        # Add throttling to the default stage to prevent abuse
        default_stage = api.default_stage
        if default_stage:
            cfn_stage = default_stage.node.default_child
            if cfn_stage:
                cfn_stage.add_property_override("DefaultRouteSettings.ThrottlingBurstLimit", 50)
                cfn_stage.add_property_override("DefaultRouteSettings.ThrottlingRateLimit", 100)

        # Store state machine ARN in deployment lambda env
        self.deployment_lambda.add_environment("STATE_MACHINE_ARN", self.state_machine.state_machine_arn)

        return api

    def _add_cloudfront_cors_origin(self) -> None:
        """Widen API Gateway CORS to allow CloudFront origin.

        Cannot reference distribution.domain_name here — CloudFront depends on
        the API URL, so a back-reference creates a circular dependency.
        Token-based auth (Cognito JWT) means allow_origins=["*"] is safe:
        no ambient credentials (cookies) are sent cross-origin.
        """
        cfn_api = self.api.node.default_child
        if cfn_api:
            cfn_api.add_property_override(
                "CorsConfiguration.AllowOrigins",
                ["*"],
            )

    # ------------------------------------------------------------------
    # S3 + CloudFront
    # ------------------------------------------------------------------

    def _create_logging_bucket(self) -> s3.Bucket:
        """Create S3 bucket for access logs (S3 + CloudFront)."""
        return s3.Bucket(
            self,
            "LoggingBucket",
            bucket_name=f"{self._project}-{self._env}-logs-{self.region}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            lifecycle_rules=[
                s3.LifecycleRule(expiration=Duration.days(90)),
            ],
        )

    def _create_s3_bucket(self) -> s3.Bucket:
        """Create S3 bucket for frontend static assets.

        Requirements: 7.1
        """
        return s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"{self._project}-{self._env}-frontend-{self.region}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="s3-frontend/",
            lifecycle_rules=[
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(30),
                ),
            ],
        )

    def _create_waf_web_acl(self) -> wafv2.CfnWebACL:
        """Create WAFv2 WebACL for CloudFront with managed rules + rate limiting."""
        return wafv2.CfnWebACL(
            self,
            "CloudFrontWebACL",
            name=f"{self._project}-{self._env}-cloudfront-waf",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name=f"{self._project}-{self._env}-waf",
                sampled_requests_enabled=True,
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"{self._project}-{self._env}-common-rules",
                        sampled_requests_enabled=True,
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=2,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=2000,
                            aggregate_key_type="IP",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"{self._project}-{self._env}-rate-limit",
                        sampled_requests_enabled=True,
                    ),
                ),
            ],
        )

    def _create_cloudfront_distribution(self) -> cloudfront.Distribution:
        """Create CloudFront distribution with S3 + API Gateway origins.

        - /* → S3 (frontend)
        - /api/* → API Gateway
        - /health → API Gateway

        Requirements: 7.2, 7.3
        """
        # S3 origin for frontend (OAC — recommended over legacy OAI)
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            self.bucket,
        )

        # API Gateway origin — extract domain from the API URL
        # API URL format: https://{api-id}.execute-api.{region}.amazonaws.com/
        api_domain = cdk.Fn.select(2, cdk.Fn.split("/", self.api.url or ""))
        api_origin = origins.HttpOrigin(
            domain_name=api_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )

        # Security response headers (HSTS, X-Frame-Options, X-Content-Type-Options, etc.)
        security_headers = cloudfront.ResponseHeadersPolicy(
            self,
            "SecurityHeadersPolicy",
            response_headers_policy_name=f"{self._project}-{self._env}-security-headers",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                    override=True,
                ),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.seconds(63072000),
                    include_subdomains=True,
                    override=True,
                ),
                xss_protection=cloudfront.ResponseHeadersXSSProtection(
                    protection=True,
                    mode_block=True,
                    override=True,
                ),
            ),
        )

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            comment=f"{self._project}-{self._env} distribution",
            default_root_object="index.html",
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            web_acl_id=self.web_acl.attr_arn,
            log_bucket=self.logging_bucket,
            log_file_prefix="cloudfront/",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=security_headers,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=security_headers,
                ),
                "/health": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=security_headers,
                ),
            },
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        return distribution

    # ------------------------------------------------------------------
    # Stack Outputs
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # CloudWatch Alarms (LAMBDA-011)
    # ------------------------------------------------------------------

    def _create_lambda_alarms(self) -> None:
        """Create CloudWatch alarms for all Lambda functions."""
        all_fns: dict[str, _lambda.Function] = {
            "workflow": self.workflow_lambda,
            "deployment": self.deployment_lambda,
            "trigger-router": self.trigger_router_lambda,
            **{f"step-{k}": v for k, v in self.step_lambdas.items()},
        }
        for name, fn in all_fns.items():
            slug = name.replace("_", "-")
            fn.metric_errors(period=Duration.minutes(5)).create_alarm(
                self,
                f"Alarm-{slug}-errors",
                alarm_name=f"{self._project}-{self._env}-{slug}-errors",
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            fn.metric_throttles(period=Duration.minutes(5)).create_alarm(
                self,
                f"Alarm-{slug}-throttles",
                alarm_name=f"{self._project}-{self._env}-{slug}-throttles",
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )

    def _create_stack_outputs(self) -> None:
        """Create CloudFormation stack outputs.

        Requirements: 7.3
        """
        CfnOutput(
            self,
            "ApiGatewayUrl",
            value=self.api.url or "",
            description="API Gateway HTTP API URL",
        )

        CfnOutput(
            self,
            "CloudFrontUrl",
            value=f"https://{self.distribution.distribution_domain_name}",
            description="CloudFront distribution URL",
        )

        CfnOutput(
            self,
            "S3BucketName",
            value=self.bucket.bucket_name,
            description="Frontend S3 bucket name",
        )

        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
        )
