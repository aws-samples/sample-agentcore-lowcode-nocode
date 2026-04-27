# Sprint 2: Architecture Refactor + Missing Service Backends

## Goal
Refactor to the two-tier node architecture (sub-nodes), implement missing service backends (Code Interpreter, Browser), complete Identity outbound auth, and validate multi-agent patterns.

---

## Item 1: Sub-Node Architecture Refactor (C1)

### Problem
Memory, Identity, Code Interpreter, Browser, Policy are peer canvas nodes with edges. The spec requires them as expandable config panels docked inside Runtime or Gateway.

### Root Nodes (remain as canvas nodes with ports)
- Runtime
- Gateway
- Evaluations

### Sub-Nodes (become config panels inside parent)
| Sub-Node | Parent | Slot |
|----------|--------|------|
| Memory | Runtime | Memory |
| Identity | Runtime | Auth |
| Code Interpreter | Runtime | Tools |
| Browser | Runtime | Tools |
| Policy | Gateway | Policy |
| Lambda Target | Gateway | Targets |
| OpenAPI Target | Gateway | Targets |
| Smithy Target | Gateway | Targets |
| MCP Server Target | Gateway | Targets |
| API Gateway Target | Gateway | Targets |

### Implementation
- [ ] Redesign `AgentCoreNode.tsx` — expand root nodes to show collapsible sub-config sections
- [ ] Remove sub-node types from `ComponentPalette.tsx` drag targets
- [ ] Remove sub-node edges from workflow schema (sub-node config stored inside parent node data)
- [ ] Update `getConnectedToolsAndGateway()` — read sub-config from parent node data instead of traversing edges
- [ ] Migrate all 6 templates to new schema (nodes carry sub-config internally)
- [ ] Update all deploy paths: SFN input builder, direct deploy, all step handlers
- [ ] Backward compat: migration function to convert old edge-based workflows to sub-node format

### Risk Mitigation
- Build behind feature flag (new node renderer alongside old)
- Migrate one sub-node at a time (start with Memory → Runtime, lowest risk)
- Keep old edge-discovery as fallback during transition

---

## Item 2: Code Interpreter Backend (H1)

### Current State
- Frontend node + `CodeInterpreterConfiguration` exist
- No backend step handler

### Implementation
- [ ] New `code_interpreter_step.py` step handler
- [ ] Uses official SDK: `from bedrock_agentcore.tools.code_interpreter_client import code_session`
- [ ] Config passed via Runtime env vars: `CODE_INTERPRETER_ENABLED=true`, `CODE_INTERPRETER_LANGUAGE`, `CODE_INTERPRETER_TIMEOUT`
- [ ] Generated agent code integrates Code Interpreter as a tool
- [ ] Add to SFN flow as optional step (after runtime_configure, before launch)
- [ ] CDK: new step Lambda + SFN choice node

---

## Item 3: Browser Tool Backend (H3)

### Current State
- Frontend node + `BrowserConfiguration` exist
- No backend step handler

### Implementation
- [ ] New `browser_step.py` step handler
- [ ] Uses official SDK: `from strands_tools.browser import AgentCoreBrowser`
- [ ] Config: enable/disable, timeout, allowed domains
- [ ] Runtime needs strands-mcp.zip bundle (Browser requires strands_tools)
- [ ] Generated agent code creates `AgentCoreBrowser(region=region).browser` tool
- [ ] Add to SFN flow as optional step
- [ ] CDK: new step Lambda + SFN choice node

---

## Item 4: Identity Outbound Auth Completion (H2)

### Current State
- Inbound JWT (Cognito) works via `auth_step.py`
- `IdentityConfiguration` has OAuth2 providers defined (Google, Microsoft, GitHub, Slack, etc.)
- Outbound flow: agent calls external APIs with user-delegated or autonomous OAuth2 tokens

### Implementation
- [ ] Implement outbound credential provider creation in `auth_step.py`
  - Uses `CreateCredentialProvider` API on bedrock-agentcore-control
  - OAuth2 provider config: clientId, clientSecret, scopes, discoveryUrl
- [ ] Runtime env vars: `OUTBOUND_AUTH_PROVIDER_ARN`, `OUTBOUND_AUTH_SCOPES`
- [ ] Generated agent code retrieves tokens from credential provider for external API calls
- [ ] Test with at least 2 providers: GitHub (code access) + Slack (message sending)

---

## Item 5: Evaluations Full Picker (L2)

### Current State
- Basic evaluator config + deploy step work
- Missing: full 13-evaluator list, custom evaluator panel, inline scores

### Implementation
- [ ] Evaluator picker dropdown with all 13 built-in evaluators:
  - Builtin.GoalSuccessRate (SESSION)
  - Builtin.Helpfulness, Correctness, Coherence, Faithfulness (TRACE)
  - Builtin.ToolSelectionAccuracy (TOOL_CALL)
  - Builtin.ResponseRelevance, Conciseness, InstructionFollowing, Refusal, Stereotyping (TRACE)
  - + 2 others (add when documented)
- [ ] Custom evaluator panel: model selection, rating scale, instructions
- [ ] Inline score display post-evaluation run
- [ ] Up to 10 evaluators per online config (validation)

---

## Item 6: Governed Tool Access E2E Validation (P4)

### Pattern: Runtime -> Gateway + Policy + Identity
- [ ] Create a test workflow: Runtime + Gateway (with Lambda tools) + Policy (Cedar rules) + Identity (JWT auth)
- [ ] Deploy and verify:
  - Agent authenticates via JWT
  - Agent discovers tools via Gateway MCP
  - Policy engine intercepts tool calls
  - Cedar rules enforce/deny based on conditions
  - Audit log shows policy decisions
- [ ] Create a template for this pattern (Template 7: "Governed Agent")

---

## Definition of Done
- [ ] Sub-node architecture renders correctly for all node types
- [ ] All 6 existing templates work with new architecture
- [ ] Code Interpreter deploys and agent can execute Python/JS in sandbox
- [ ] Browser tool deploys and agent can navigate web pages
- [ ] Outbound OAuth2 works for at least 2 external providers
- [ ] All 13 evaluators selectable and deployable
- [ ] Governed Tool Access pattern works end-to-end
- [ ] No regressions from Sprint 1 features
