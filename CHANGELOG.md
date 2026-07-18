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

### Fixed — full-matrix verification (11 live-found deploy/runtime defects)
Every deployable pattern was verified end-to-end against real AWS
(93 patterns PASS with canary evidence; the only non-PASS is an AWS-side
web-crawler ingestion stall, not a platform defect). Fixes:
- Generated memory agents now retrieve long-term memory records across sessions
  (`retrieve_memories` was never called); memory+knowledge-base canvases no
  longer silently drop KB retrieval
- `CreateMemory` retries the IAM trust-policy propagation race; failed deploys
  no longer leak gateways (targets deleted before the gateway)
- OpenSearch Serverless KBs: `aoss:BatchGetCollection` scoped correctly
  (account-level API); BDA parsing uses the correct
  `supplementalDataStorageConfiguration` shape + bucket-root URI + role grants
- Knowledge-base deploys are idempotent on retry (`CreateDataSource` /
  `StartIngestionJob` conflict-adopt); KB step role gains
  `ListDataSources`/`GetDataSource`
- KB-backed runtime deletion is now asynchronous — returns immediately with a
  `delete_status` pointer instead of timing out API Gateway's 29s cap (503);
  double-delete is tolerated
- Cedar ENFORCE policy engine self-heals a regressed `UPDATE_FAILED` permit
  (previously could stay deny-all forever if no touchpoint fired); the
  scheduled sweep reconciles ENFORCE engines against live policy status
- `GET /evaluation-config` resolves custom-named online-evaluation configs by
  CloudWatch target (not just the `eval_<id>` name heuristic)
- `list_gateways` conflict recovery is paginated (multi-page accounts)

## [0.1.0] - 2026-07-17

Initial public sample: visual drag-and-drop workflow builder for Amazon Bedrock
AgentCore with Step Functions-orchestrated deployment, gateway/tool wiring,
memory, knowledge bases, guardrails, observability, evaluations, enterprise
governance (RBAC/ABAC, Cedar policies, approvals, budgets), and manifest-driven
teardown.
