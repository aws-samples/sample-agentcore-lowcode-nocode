# 🚀 Claude Code Master Execution Plan
# AgentCore Low-Code/No-Code — Market Gap Implementation

> **IMPORTANT**: This file is your single entry point. Read it top to bottom, execute tasks in order.
> Each task has a dedicated spec file in `tasks/market-gaps/` with full architecture, code snippets, and acceptance criteria.

## Project Location
```
/Users/omrsamer/Desktop/VSCode/sample-agentcore-lowcode-nocode/
```

## Task Spec Files
All task specs are at:
```
tasks/market-gaps/
├── 00-MASTER-ORCHESTRATION.md    ← High-level overview & deploy/test/bash cycle
├── 01-event-triggers-scheduling.md
├── 02-human-in-the-loop.md
├── 03-agent-versioning-rollback.md
├── 04-observability-dashboard.md
├── 05-a2a-protocol-support.md
├── 06-bedrock-guardrails-integration.md
├── 07-environment-promotion.md
├── 08-cli-sdk.md
├── 09-agent-marketplace.md
└── 10-advanced-security-hardening.md
```

## Existing Context (READ FIRST)
Before starting any task, familiarize yourself with:
- `CLAUDE.md` — Your workflow orchestration rules
- `README.md` — Full architecture, features, deploy instructions
- `CHANGELOG.md` — Recent changes and fixes
- `tasks/lessons.md` — Critical lessons from past bugs (MUST READ)
- `tasks/todo.md` — Current sprint status
- `tasks/harness-patterns-catalog.md` — AgentCore Harness integration patterns (CRITICAL)
- `tasks/skills-registry-final-plan.md` — Registry MVP plan already in progress

## Key AWS Services Already Integrated
The project ALREADY uses these AgentCore features — leverage them, don't duplicate:
- **AgentCore Runtime** — `CreateAgentRuntime` / `InvokeAgentRuntime` (fully integrated)
- **AgentCore Gateway** — MCP Gateway with Cognito OAuth2 (fully integrated)
- **AgentCore Memory** — Semantic/Episodic/Summary/UserPreferences strategies (integrated)
- **AgentCore Knowledge Base** — RAG with 5 data sources, 3 vector stores (integrated)
- **AgentCore Policy** — Cedar rules via policy engine (integrated)
- **AgentCore Harness** — `CreateHarness`/`UpdateHarness`/`GetHarness` (PARTIALLY integrated — see `backend/src/app/services/harness_deployer.py` and `tasks/harness-patterns-catalog.md`)
- **AWS Agent Registry** — Registry publish/discover (PARTIALLY integrated — see `backend/src/app/services/registry_*.py` and `frontend/src/components/registry/`)

---

## NEW AgentCore Services to Integrate

### 1. AgentCore Harness (Managed Agent)
**What it is**: A single declarative `Harness` resource that collapses Runtime + Gateway + Memory + Identity + Browser + Code Interpreter + orchestration into one API call (`CreateHarness`). The harness is FREE — you pay only for underlying resources.

**Current state in project**: `harness_deployer.py` exists with `CreateHarness`, `UpdateHarness`, `DeleteHarness`, `ListHarnesses`. Harness models exist in `backend/src/app/models/harness_models.py`. Frontend Harness node is planned (P1 in patterns catalog). CDK custom resource pattern documented (P13).

**API surface**:
- Control plane: `CreateHarness`, `UpdateHarness`, `GetHarness`, `ListHarnesses`, `DeleteHarness`
- Data plane: `POST /harnesses/invoke?harnessArn=…` with `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header
- Poll-until-READY pattern: 12× × 5s budget (see harness_deployer.py)

**How to leverage in market gap tasks**:
- **Task 01 (Triggers)**: Triggers can invoke Harnesses directly via the data plane. Simpler than invoking separate Runtimes.
- **Task 03 (Versioning)**: Harness + Optimization bundles = native versioning. Configuration bundles are immutable, versioned snapshots.
- **Task 06 (Guardrails)**: Harness supports `guardrailConfiguration` natively in the CreateHarness call.
- **Task 07 (Promotion)**: Configuration bundles + Gateway A/B testing = canary deployment without custom infrastructure.

### 2. AgentCore Optimization (Preview — May 4, 2026)
**What it is**: A closed-loop quality system: observe → evaluate → recommend → validate → ship.

**Key capabilities**:
- **Recommendations API**: Analyzes production traces (from CloudWatch Log group) + evaluation scores → generates optimized system prompt or tool descriptions for a specified evaluator
- **Configuration Bundles**: Immutable, versioned snapshots of agent config (model ID, system prompt, tool descriptions) keyed by runtime ARN. Agent reads active config dynamically via SDK — swapping a prompt is a config change, not a code change.
- **Batch Evaluation**: Run agent against curated dataset using new bundle, compare aggregate scores to baseline. Wire into CI/CD — no config reaches production without passing known-good cases.
- **A/B Testing via Gateway**: Split live production traffic between variants (% configurable). Reports confidence intervals + p-values. Variants can be different bundle versions (config-only) or different gateway targets (code changes).
- **Auto-rollback**: Pause test → agent reverts to existing configuration instantly.

**How to leverage in market gap tasks**:
- **Task 03 (Versioning)**: USE configuration bundles as the versioning primitive. Create bundle for current config + bundle for new config. Bundles are the "versions."
- **Task 04 (Observability)**: Built-in evaluators provide goal success rate, tool selection accuracy, helpfulness, safety scores. Surface these in the dashboard via the Evaluations API.
- **Task 07 (Promotion)**: A/B testing IS canary deployment. Gateway traffic splitting with statistical significance = production-grade environment promotion. No need for Lambda aliases or custom weighted routing.

### 3. AWS Agent Registry (Preview — April 9, 2026)
**What it is**: A fully managed catalog and discovery layer for agents, tools, MCP servers, agent skills, and custom resources within your organization.

**Key capabilities**:
- Stores structured metadata records (publisher, protocols, services exposed, invocation details)
- Supports MCP and A2A natively + custom descriptor schemas
- Auto-registration: point at MCP/A2A endpoint → registry pulls metadata automatically
- Hybrid search: keyword + semantic matching ("payment processing" finds "billing" and "invoicing")
- Approval workflows: draft → pending approval → discoverable
- **Accessible as MCP server** — any MCP client (Claude Code, Kiro) can query it
- OAuth-based access for custom UIs (no IAM needed for consumers)
- Lifecycle management: development → deployed → retired → versioned
- Cross-registry federation (future): connect multiple registries, search as one

**Current state in project**: Frontend components exist (`PublishWizard.tsx`, `AdminApprovalTable.tsx`, `RecordCard.tsx`, `RecordDetailDrawer.tsx`, `InstallConfigModal.tsx`, `RegistryPicker.tsx`). Backend has `registry_client.py`, `registry_authz.py`, `registry_publish_input.py`, `registry_descriptor_builder.py`, `registry_index_store.py`, etc.

**How to leverage in market gap tasks**:
- **Task 09 (Marketplace)**: AWS Agent Registry IS your marketplace backend. Don't build custom DynamoDB tables — use registry APIs for cataloging, discovery, search, approval, and lifecycle. Your frontend is a UI layer on the registry.
- **Task 05 (A2A)**: Registry supports A2A descriptors natively. Publishing an agent to registry with A2A type auto-exposes its agent card for discovery.
- **Task 10 (Security)**: Registry has IAM-based governance for publish/discover permissions. Approval workflows are built-in.

---

## Revised Execution Order

Execute in this order. After EACH task, deploy and test.

| # | Task File | Gap | AgentCore Integration | Priority |
|---|-----------|-----|----------------------|----------|
| 1 | `01-event-triggers-scheduling.md` | Scheduled/Event Agents | Invoke Harness via data plane | P0 |
| 2 | `02-human-in-the-loop.md` | Human Approval Workflows | Harness tool registration | P0 |
| 3 | `03-agent-versioning-rollback.md` | Versioning & Rollback | **Optimization Bundles** | P0 |
| 4 | `04-observability-dashboard.md` | Performance Dashboards | **Observability traces + Evaluations** | P1 |
| 5 | `05-a2a-protocol-support.md` | A2A Protocol | **Agent Registry A2A descriptors** | P1 |
| 6 | `06-bedrock-guardrails-integration.md` | Content Guardrails | Harness `guardrailConfiguration` | P1 |
| 7 | `07-environment-promotion.md` | Dev→Staging→Prod | **Optimization A/B Testing** | P1 |
| 8 | `08-cli-sdk.md` | CLI & SDK | Wraps AgentCore + Registry APIs | P2 |
| 9 | `09-agent-marketplace.md` | Marketplace | **AWS Agent Registry** (managed) | P2 |
| 10 | `10-advanced-security-hardening.md` | RBAC/Audit/DLP | Registry IAM + Policy engine | P2 |

---

## Deploy-Test-Bash Cycle (After Each Task)

### 1. Deploy
```bash
cd /Users/omrsamer/Desktop/VSCode/sample-agentcore-lowcode-nocode
COGNITO_USERS="omrsamer@amazon.com" ./scripts/deploy.sh
```

### 2. Smoke Test
```bash
CLOUDFRONT_URL=$(aws cloudformation describe-stacks --stack-name agentcore-workflow-dev \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text)
curl -s "$CLOUDFRONT_URL/api/health" | jq .
```

### 3. Bug Bash
- [ ] All new API endpoints return correct HTTP status codes
- [ ] Frontend renders without console errors
- [ ] DynamoDB tables have correct indexes and TTLs
- [ ] Step Functions handles all paths (success, failure, timeout)
- [ ] Error messages are user-friendly (no raw stack traces)
- [ ] Lambdas have structured error handling
- [ ] Race conditions: concurrent requests to same resources
- [ ] Edge cases: empty inputs, max-length, special chars, Unicode
- [ ] Browser: Chrome, Firefox, Safari

### 4. Security Bash
- [ ] `detect-secrets scan` — no new secrets
- [ ] IAM: no `*` actions, scoped to specific resources
- [ ] All endpoints require Cognito auth
- [ ] Input validation (Pydantic models) on all user data
- [ ] No injection vectors (sanitized DynamoDB expressions)
- [ ] CORS: no wildcard in production
- [ ] `cd infra && npx cdk synth` — CDK-NAG passes
- [ ] No hardcoded credentials or account IDs
- [ ] Secrets in SSM/Secrets Manager (not env vars)
- [ ] X-Ray tracing on new Lambdas
- [ ] CloudWatch alarms on new Lambda errors/throttles

### 5. Run Tests
```bash
cd backend && python run_tests.py
cd ../frontend && npm test
cd ../infra && python -m pytest tests/
```

---

## Critical Rules (From tasks/lessons.md — DO NOT VIOLATE)

1. **Multi-path sync**: Any field in code generation MUST exist in BOTH `codegen_step.py` (SFN) AND `deployment.py` (direct deploy)
2. **Gateway naming**: `len(target_name) + 3 + len(tool_name) <= 64`
3. **Memory strategy keys**: Use `STRATEGY_KEY_MAP` for camelCase API keys
4. **Lambda packaging**: CDK packages entire `backend/` dir. Manual deploys need `src/` + `lib/`
5. **SFN error handling**: Check BOTH `event.get("error")` AND `event.get("error_info")`
6. **SDK response keys**: `list_gateway_targets` returns under `items`, `targets`, OR `gatewayTargetSummaries`
7. **Sanitize AI schemas**: Strip unsupported keys before AWS APIs
8. **Module-level init**: Agent + MCP client at module level, NOT per-request
9. **Harness status polling**: 12× × 5s budget; unknown statuses = keep polling (not terminal)
10. **Registry records**: Start as draft → pending → approved. Never skip approval workflow.

---

## Start Here

```bash
cd /Users/omrsamer/Desktop/VSCode/sample-agentcore-lowcode-nocode

# 1. Read context
cat CLAUDE.md
cat tasks/lessons.md
head -100 tasks/harness-patterns-catalog.md

# 2. Start Task 01
cat tasks/market-gaps/01-event-triggers-scheduling.md

# 3. Implement, deploy, test, bash, repeat
```
