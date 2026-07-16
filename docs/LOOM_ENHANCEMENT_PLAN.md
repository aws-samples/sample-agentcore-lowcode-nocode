# Loom-informed enhancement plan

Derived from a full study of **Loom for AWS** (awslabs/loom + the launch blog's 7
enterprise challenges) against our platform. Loom is our sibling: a fleet-management
console (ECS/Fargate + RDS) vs our serverless (Lambda + DynamoDB) **visual canvas
builder**. We keep our differentiator (the canvas + per-deploy codegen); we adopt
Loom's governance/identity/UX wins **only where they fit serverless**.

Each item: **value × fit-to-our-arch**, effort (S/M/L), and whether it's a
**real defect** in our code (fix regardless of roadmap) or a **new capability**.

---

## Phase 0 — Real defects the study exposed (fix first; low risk, high correctness)

These are bugs/dead-config in OUR code, independent of the Loom roadmap.

| # | Defect | Where | Effort |
|---|--------|-------|--------|
| 0.1 | **VPC config is modeled but never read** — `RuntimeConfiguration.vpc_config` exists but `runtime_deployer.py` + `cfn_template_generator.py` hardcode `networkMode=PUBLIC`. The field is dead. | `runtime_deployer.py`, `cfn_template_generator.py` | M |
| 0.2 | **Alternate-provider model init emits NO credentials** — selecting litellm/openai/anthropic generates a model with no `base_url`/`api_key` (only groq/deepseek/writer get env keys). Selecting those providers produces a broken agent. | `code_generator.py:_get_model_init_code` | S |
| 0.3 | **OBO gateway target hardcodes `CLIENT_CREDENTIALS`** even when `delegation_mode=obo` — the OBO provider is minted correctly but the target still requests client-credentials, so OBO never actually exchanges. | `gateway_deployer.py` (~target cred config) | S |
| 0.4 | **AWS Agent Registry auto-registration has zero callers** — `aws_agent_registry.register()` exists but nothing invokes it on deploy; the federation feature is wired but never fires. | `step_handlers/status_update_step.py` | M |
| 0.5 | **`session_uuid` never populated** in the audit store (field exists, always empty) — blocks any per-session analytics. | `audit_store.py` | S |
| 0.6 | **Cedar promoter re-drive gap** (found live in P-PLAT-027) — the lazy promoter stops re-attempting `update_policy` once `enforce_pending` state is mutated, even while the policy is still `UPDATE_FAILED`. A direct `update_policy` converged instantly. Re-drive on ANY non-ACTIVE state until ACTIVE. | `policy_promoter.py` | S |
| 0.7 | **Registry status not synced / not deleted on teardown** — stale AWS-registry records persist after resource delete + across enable/disable. | `registry.py`, teardown paths | S |
| — | *0.7 scope note:* delete-on-teardown is DONE (the main orphan risk). The `_sync_registry_statuses` reconciliation on aws-config re-enable (validate all stored record ids vs the live registry) remains a documented follow-up. | | |

---

## Phase 1 — Identity & governance completeness (highest enterprise value, fits serverless)

| # | Capability | Approach (serverless-fit) | Effort |
|---|-----------|---------------------------|--------|
| 1.1 | **3rd-party IdP federation** (Entra/Okta/Auth0/OIDC) | Federate INTO Cognito (hosted UI IdP), NOT Loom's in-app multi-issuer validation (that's ECS-shaped). Keeps the API-GW Cognito authorizer unchanged. + a pre-token Lambda for group-claim → internal-group mapping. | L |
| 1.2 | **OBO token-exchange: prove it works** | Add `/agents/{id}/test-obo` dry-run (ACPS `get_resource_oauth2_token` ON_BEHALF_OF) + `oauth_audience` field (Okta custom auth servers reject exchange without it). Pairs with 0.3. | M |
| 1.3 | **Token-info visualization** | A TokenInfoCard on the invoke/harness panel showing decoded user + OBO claims (iss/aud/scp) with group-mapping resolution — the "prove delegation preserved the user" story. Fits our React canvas. | M |
| 1.4 | **Integration gating** — only APPROVED MCP/A2A selectable in a deploy | Validation pass rejecting flows whose connected MCP/A2A map to non-APPROVED registry records. | M |
| 1.5 | **Import existing AgentCore Runtime by ARN** | `POST /register-runtime`: describe + adopt an externally-built runtime into our observability/cost/registry without redeploy. | M |
| 1.6 | **JIT IAM permission-request workflow** | request→approve→widen-role, gated by admin scope, wired to `iam_manager`. | M |

---

## Phase 2 — HITL hardening (we have voluntary HITL; Loom has guaranteed HITL)

| # | Capability | Approach | Effort |
|---|-----------|----------|--------|
| 2.1 | **BeforeToolCall hook** (guarantee, not voluntary) | Today we inject a `human_approval` tool the LLM *may* call — a sensitive tool can be invoked without approval. Add a Strands `BeforeToolCallEvent` HookProvider that auto-gates matched tools. | M |
| 2.2 | **Config-driven approval policies** | ApprovalPolicy store (DDB, tenant-scoped like `hitl_store`) + CRUD + glob tool-match/notify-only/timeout, injected to the agent as env var consumed by 2.1. | M |
| 2.3 | **Durable approval audit log** | Our HITL rows TTL-expire in 24h. Persist decisions to `audit_store` + a filterable `/api/hitl/logs`. | S |
| 2.4 | **Harness HITL** (managed agents have zero HITL today) | tool_use pause + toolResult-resume in the harness invoke path. | L |

---

## Phase 3 — End-user Chat persona (biggest NEW capability; we're builder-only)

| # | Capability | Approach | Effort |
|---|-----------|----------|--------|
| 3.1 | **ChatPage for `t-user`** | We defined `t-user`/`t-admin` groups but standard users have nowhere to land. Route `t-user` to a chat UI (agent picker filtered by group tag + SSE streaming + conversation history + "My Memory" panel). We already have SSE invoke + memory + RBAC — this is mostly frontend. | L |
| 3.2 | **View-as preview** | Admin previews the end-user experience (we partly have this via RBAC). | S |

---

## Phase 4 — Networking (enterprise-private connectivity; depends on 0.1)

| # | Capability | Approach | Effort |
|---|-----------|----------|--------|
| 4.1 | **VPC-egress agents** | Thread `vpc_config` → `networkMode=VPC` (builds on 0.1) + `iam:CreateServiceLinkedRole` for the AgentCore network SLR (first VPC deploy fails without it). | M |
| 4.2 | **Named VPC config profiles** | DDB store + CRUD + a canvas network-mode selector bound to the existing (dead) frontend field. | M |
| 4.3 | **PrivateLink ingress + SG IaC** | Ship optional CFN (NLB + VPC Endpoint Service + per-protocol SG) as a downloadable add-on stack. | L |

---

## Phase 5 — Analytics & alternate models (valuable; some external-infra-bound)

| # | Capability | Approach | Effort / caveat |
|---|-----------|----------|--------|
| 5.1 | **Live model catalog** | `/api/models` doing live Bedrock `list_foundation_models` + pricing merge, replacing the hardcoded frontend list. Valuable even without LiteLLM. | M |
| 5.2 | **Rich admin analytics** | recharts dashboard: login/action/page tracking, session-UUID scoping (needs 0.5), 2-level action taxonomy, per-session drill-down, multi-user filter. | L |
| 5.3 | **Usage-log cost reconciliation** | EventBridge-scheduled Lambda (NOT Loom's always-on poller) upgrading estimated→actual vCPU/GB-hr cost. | M |
| 5.4 | **LiteLLM alternate providers** | Per-agent vended virtual keys + dynamic catalog. **CAVEAT: needs a running LiteLLM proxy (out-of-band infra) — weighs against our pure-serverless model.** Lowest priority; consider only if a customer demands non-Bedrock models at scale. | M + external infra |

---

## Explicitly NOT adopting (Loom features that fight our architecture)
- Loom's **in-app multi-issuer JWT validation** (`jwt_validator` per-request) — assumes a long-running app; we use the API-GW edge authorizer + Cognito federation instead (simpler).
- Loom's **backend code-exchange proxy / confidential-client toggle** — subsumed by Cognito hosted UI.
- Loom's **always-on asyncio usage_poller** — re-cast as EventBridge (5.3).
- **RDS/Postgres + integer PKs** — we're DynamoDB single-table; no change.

## Recommended sequencing
**Phase 0 first** (defects — some are shipping bugs). Then **Phase 1** (enterprise
identity/governance is the blog's core thesis and our biggest credibility gap).
**Phase 3** (end-user chat) is the highest-visibility new capability — good to
schedule alongside Phase 1. Phases 2/4/5 as capacity allows. Phase 5.4 only on demand.
