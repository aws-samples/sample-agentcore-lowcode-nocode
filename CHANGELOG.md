# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- GitHub Actions CI: ruff lint/format, backend unit tests with coverage floor,
  CDK assertion tests + `cdk synth` (cdk-nag gate), frontend lint/typecheck/tests/build
- Dependabot for npm, pip, and GitHub Actions; `SECURITY.md` vulnerability policy
- Pyright (basic mode, advisory) and wider ruff rule set (`I`, `B`, `UP`)
- Committed `frontend/package-lock.json` for reproducible builds (`npm ci`)

### Fixed
- README/`.env.example` no longer instruct deploying to `us-west-2`, which
  `deploy.sh` rejects (the WAF WebACL is CLOUDFRONT-scoped and requires
  `us-east-1`)
- Stale CDK assertion tests updated to the current architecture (14 DynamoDB
  tables, 3 S3 buckets, no `States.TaskFailed` retry, CloudFront Function SPA
  routing instead of CustomErrorResponses)

## [0.1.0] - 2026-07-17

Initial public sample: visual drag-and-drop workflow builder for Amazon Bedrock
AgentCore with Step Functions-orchestrated deployment, gateway/tool wiring,
memory, knowledge bases, guardrails, observability, evaluations, enterprise
governance (RBAC/ABAC, Cedar policies, approvals, budgets), and manifest-driven
teardown.
