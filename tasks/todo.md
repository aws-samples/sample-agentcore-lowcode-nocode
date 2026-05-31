# Phase 1 Verification Gate — Pattern Catalog Sweep

## Scope
Account 123456789012 (omare, non-prod) / us-east-1 / agentcore-workflow-dev

Verify Phase 1 features (versioning, eval, dashboard, NL agent creation) did not regress
the baseline pattern matrix. Rerun representative cells per family.

## Target matrix
- [ ] P-RUN-001 — UI deploy of minimal Strands runtime + invoke + versions endpoint + dashboard
- [ ] P-RUN-001 — CFN export deploy + invoke
- [ ] P-MEM-LTM-003 — Strands + Memory (summary, default ns), 2-turn recall
- [ ] P-KB-001 — Strands + KB (S3 Vectors, default chunking) + canary retrieval
- [ ] P-GW-LAM-001 — Strands + Gateway + duckduckgo_search Lambda invocation
- [ ] P-MCP-001 — MCP-server-runtime template (FastMCP)
- [ ] Phase 1 specific:
  - [ ] /api/runtimes/{name}/versions returns version data after a deploy
  - [ ] /api/runtimes/{name}/dashboard-url returns a URL
  - [ ] CloudWatch dashboard exists in account post-deploy
  - [ ] Eval-disabled deploys (default) skip eval step gracefully
  - [ ] DeploymentState w/o versioning fields still deploys (legacy path)

## Verification approach
- Mint Cognito JWT via SRP → `reports/phase1-matrix/scripts/get_token.py`
- Per cell:
  1. POST /api/deploy (or /api/generate-cfn-template + deploy.sh)
  2. Poll /api/deploy/{id} until terminal
  3. POST /api/test-runtime with canary-forcing prompt
  4. Validate response contains canary; reject apologies/errors
  5. (Phase 1) GET /api/runtimes/{name}/versions
  6. (Phase 1) Verify CloudWatch dashboard exists
  7. DELETE /api/runtime/{id}
- Hard time budget per cell: 8 min deploy + 3 min invoke = 11 min
- Total run cap: 90 min
- Evidence to /Users/omrsamer/Desktop/VSCode/sample-agentcore-lowcode-nocode/reports/phase1-matrix/evidence/

## Known historical risks
- Bug 60-63 chain: AgentCore IAM cache race on CreateAgentRuntime (5-25 min)
  → Phase 1 by-name + version_id S3 prefix should ride out the cache; verify
- DELETE leaks shared role (Bug 67) — must NOT touch shared role
- Pre-existing artifacts to preserve:
  - role: AgentCoreRuntime-agentcore-workflow-dev-shared
  - runtime: DemoTriage_TriageAgent-F8LnEpA8q0
  - secret: agentcore-otel/platform/dev
