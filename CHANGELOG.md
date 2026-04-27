# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- **Region-aware model IDs** — Bedrock cross-region inference model IDs now use the correct regional prefix (`eu.`, `ap.`, `us.`) based on the deployment region. Previously all model IDs were hardcoded with `us.` prefix, causing 500 errors when deploying agents in non-US regions like `eu-west-1`.
- **Memory cleanup on delete** — "Delete from AWS" now deletes the AgentCore Memory resource. Previously, memory was not cleaned up when deleting a deployment, leaving orphaned resources.
- **Tool Generator model ID** — The AI Tool Generator Lambda now uses a region-appropriate model ID instead of a hardcoded `us.` prefix.
- **Code Interpreter & Browser code generation** — Connecting Code Interpreter or Browser nodes to a Runtime now generates working agent code with `execute_python` and `browse_web` tools. Previously the code generator silently ignored these tools.
- **Connect-only node validation** — Code Interpreter, Browser, and Observability nodes now show ✓ immediately on drop. Previously they stayed in "pending" state since they have no configuration modal.

### Changed

- **Memory configuration simplified** — Removed the `enableMemory` toggle from the Runtime configuration modal. Memory is now controlled solely by connecting a Memory node to the Runtime on the canvas. The deploy panel derives memory status from canvas connections, providing a single source of truth.

### Added

- **User Preferences memory strategy** — Added `User Preferences` as a selectable extraction strategy in the Memory configuration modal. The backend already supported it; now it's exposed in the UI.
- **Event expiry duration** — Memory event retention is now configurable (7, 30, 60, 90, 180, or 365 days) in the Memory configuration General tab. Previously hardcoded to 90 days.
- **Memory result persistence** — Deployment state now persists `memory_result` to DynamoDB, enabling memory cleanup on delete.
- `VITE_AWS_REGION` environment variable passed to the frontend build for region-aware model selection.

### Security

- **Lambda X-Ray tracing** — Active tracing enabled on all Lambda functions (workflow, deployment, 12 step handlers) and the Step Functions state machine.
- **S3 lifecycle rules** — Artifacts bucket: 90-day expiry on `deployments/` prefix. Frontend bucket: 30-day noncurrent version expiry.
- **S3 access logging** — Dedicated logging bucket with 90-day lifecycle. Both S3 buckets log access to it.
- **CloudFront access logging** — Distribution access logs written to the logging bucket under `cloudfront/` prefix.
- **CloudFront OAC** — Migrated from Origin Access Identity (OAI) to Origin Access Control (OAC) for S3 origin.
- **CloudWatch alarms** — Errors and Throttles alarms on all 14 Lambda functions (28 alarms total).
- **Pre-commit hardening** — Ruff linting/formatting enforced, detect-secrets baseline updated, JSONC files excluded from JSON validation.
- **ASH security scan config** — `.ash/.ash.yaml` excludes build artifacts and suppresses CDK internal Lambda findings.
