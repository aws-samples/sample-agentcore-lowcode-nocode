# Sprint 1: Tool Generator E2E + Security + Core UX

## Goal
Make the AI Tool Generator work end-to-end: **Describe tool -> Generate -> Test -> Add to Canvas -> Deploy as Runtime -> Gateway -> Generated Tool Lambda**. Then harden security and add the most impactful UX features.

---

## Item 1: Tool Generator — Full E2E Functionality + Security [COMPLETE]

### 1A. Fix Lambda Handler Format Mismatch [DONE]
- [x] Rewrote `GENERATION_PROMPT` in `tool_generator.py` to produce dual-mode handlers
- [x] Gateway mode: `context.client_context.custom.get('bedrockAgentCoreToolName')` + `params = event`
- [x] Test mode: `event.get('toolName')` + `params = event.get('input', {})`
- [x] Detection via `try/except (AttributeError, TypeError)`

### 1B. Security Hardening [DONE]
- [x] AST validation in `tool_tester.py`: blocks subprocess, socket, ctypes, exec, eval, compile, __import__
- [x] Verifies `lambda_handler` function exists
- [x] Reduced test Lambda resources: 128MB/10s (from 256MB/30s)
- [x] API Gateway throttling: 100 req/s, 50 burst in `platform_stack.py`
- [x] IAM permissions for cleanup: DetachRolePolicy, DeleteRole, ListAttachedRolePolicies

### 1C. Code Generator — Custom Tool Template [DONE]
- [x] `codegen_step.py`: reads `custom_tools` from SFN event, passes to `generate_agent_code()`
- [x] `code_generator.py`: accepts `custom_tools`, injects descriptions into system prompt, adds tool-use directive
- [x] `deployment.py`: fixed direct deploy path to pass `custom_tools`, `gateway_tools`, `connected_tools`

### 1D. Custom Tool Cleanup on Delete [DONE]
- [x] `gateway_deployer.py`: tracks `custom_tool_roles` alongside `custom_tool_lambdas`
- [x] `cleanup_gateway_resources()`: detaches policies then deletes IAM roles, handles NoSuchEntity

### 1E. E2E Verified on Live AWS [DONE]
- [x] Generated temperature converter tool with dual-mode handler
- [x] 3/3 test cases passed on real Lambda
- [x] AST validation correctly blocks `import subprocess`
- [x] Deployment pipeline (SFN) SUCCEEDED in 75s
- [x] Agent invocation returned correct answer ("Four" to "2+2")
- [x] DELETE cleanup works

### 1F. Production Bug Fix: Custom Tool IDs in gatewayTools [DONE]
- [x] **Root cause**: Frontend `App.tsx` pushed custom tool IDs into both `gatewayTools` and `customTools`. Backend tried to look up custom tool name in `GATEWAY_TOOL_SCHEMAS` (predefined only), got empty list, sent empty `inlinePayload` to `CreateGatewayTarget` -> AWS ValidationException.
- [x] **Frontend fix** (`App.tsx:146`): Only push non-custom tool IDs to `gatewayTools`
- [x] **Backend safety net** (`gateway_deployer.py:972`): Skip DynamicTools target if no schemas match

### 1G. Production Bug Fix: Direct Deploy Missing custom_tools [DONE]
- [x] `deployment.py:968`: Added missing `tools`, `gateway_tools`, `custom_tools` params to template-based code generation

**Files modified (Item 1):**
1. `backend/src/app/services/tool_generator.py` — GENERATION_PROMPT rewrite
2. `backend/src/app/services/tool_tester.py` — AST validation + resource limits
3. `backend/src/app/step_handlers/codegen_step.py` — pass custom_tools
4. `backend/src/app/services/code_generator.py` — accept custom_tools, inject into system prompt
5. `backend/src/app/services/gateway_deployer.py` — track+cleanup IAM roles, skip empty DynamicTools
6. `backend/src/app/services/deployment.py` — fix missing params in direct deploy
7. `frontend/src/App.tsx` — fix custom tool IDs leaking into gatewayTools
8. `infra/stacks/platform_stack.py` — API Gateway throttling + IAM permissions

---

## Item 2: Chat Trigger — Conversational Agent UI [COMPLETE]

### What was done
Replaced the single-shot "Test" tab with a full chat interface in `DeployPanel.tsx`. No backend changes needed — reuses existing `POST /api/test-runtime` with session and history support.

- [x] Chat bubbles: user (blue, right), assistant (gray, left with avatar), system (amber, centered)
- [x] Typing indicator: 3 bouncing blue dots in assistant-style bubble
- [x] Session management: green dot + session ID, "New Session" button clears history
- [x] Cold start handling: warming-up system messages (self-replacing), auto-retry 5x
- [x] Error display: errors shown as amber system messages in chat
- [x] Input: Enter to send, Shift+Enter newline, auto-focus on tab switch
- [x] Delete button: moved to session header bar (always visible)
- [x] Layout: flex column with pinned input, scrollable messages, hidden footer

**Files modified (Item 2):**
1. `frontend/src/components/deploy/DeployPanel.tsx` — single file, UI-only change

---

## Item 3: Execution States on Canvas Nodes (C2 + C3) [COMPLETE]

### What was done
Added real-time visual execution state feedback on canvas nodes during SFN deployment.

- [x] Added `executionState` field to `AgentCoreNodeData` in Zustand store
- [x] Added store actions: `setNodeExecutionState`, `setNodeExecutionStateByType`, `resetAllExecutionStates`
- [x] SFN step-to-node-type mapping: `STEP_TO_NODE_TYPE` and `STEP_ORDER` constants
- [x] DeployPanel polling updates node states: running (animated pulse), completed (green check), failed (red X)
- [x] CSS animation: `execution-pulse` keyframes for running state
- [x] Badges: SVG icons (check/X/spinner) positioned top-right of node

**Files modified (Item 3):**
1. `frontend/src/store/workflowStore.ts` — ExecutionState type, store actions
2. `frontend/src/components/nodes/AgentCoreNode.tsx` — execution state badges + running class
3. `frontend/src/components/deploy/DeployPanel.tsx` — step-to-node mapping, polling updates
4. `frontend/src/index.css` — execution-pulse animation

---

## Item 4: Policy Integration Completion (M7) [COMPLETE]

### What was done
Policy Engine is fully integrated across SFN path (already done), direct deploy path (new), delete cleanup (new), and frontend modal (new). NL-to-Cedar deferred to Sprint 2.

- [x] Direct deploy path: `deployment.py` creates policy engine, Cedar policies, attaches to gateway
- [x] Delete cleanup: `deployment_handler.py` deletes policy engine on resource cleanup
- [x] `policy_result` persisted to DynamoDB via `status_update_step.py` for cleanup
- [x] `DeploymentState` model: added `policy_result` field
- [x] Frontend: `PolicyConfigurationModal.tsx` with Cedar policy rule editor
- [x] Cedar preview in modal shows generated policy statements
- [x] Modal wired in `App.tsx` for policy node double-click

**Files modified (Item 4):**
1. `backend/src/app/services/deployment.py` — Phase 1.5: policy engine deployment
2. `backend/src/app/deployment_handler.py` — delete cleanup for policy engines
3. `backend/src/app/models/deployment_models.py` — policy_result field
4. `backend/src/app/services/deployment_state_store.py` — policy_result persistence
5. `backend/src/app/step_handlers/status_update_step.py` — save policy_result
6. `frontend/src/components/modals/PolicyConfigurationModal.tsx` — new modal
7. `frontend/src/App.tsx` — wire policy modal

---

## Item 5: Memory Episodic Strategy (H4) [COMPLETE]

### What was done
Added EPISODIC extraction strategy and frontend Memory configuration modal with strategy selector.

- [x] Added `EPISODIC` to `ExtractionStrategy` enum (backend + frontend)
- [x] `memory_step.py` already handles arbitrary strategy types via dynamic loop — no change needed
- [x] Direct deploy path: `deployment.py` passes strategies from memory config to `create_memory()`
- [x] `MemoryConfiguration` type: added `strategies` and `MemoryStrategyConfig` interface
- [x] Frontend: `MemoryConfigurationModal.tsx` with strategy selector (Semantic, Summary, Episodic)
- [x] Each strategy has configurable name and description
- [x] Memory name validation enforces AWS naming rules (no hyphens)

**Files modified (Item 5):**
1. `backend/src/app/models/enums.py` — EPISODIC enum value
2. `backend/src/app/services/deployment.py` — strategy passthrough in direct deploy
3. `frontend/src/types/components.ts` — MemoryStrategyConfig, ExtractionStrategy, MemoryConfiguration
4. `frontend/src/components/modals/MemoryConfigurationModal.tsx` — new modal
5. `frontend/src/App.tsx` — wire memory modal

---

## Definition of Done
- [x] Tool Generator e2e: describe -> generate -> test -> deploy -> invoke through Gateway -> tool executes correctly
- [x] Chat UI works with deployed agents (non-streaming, session support)
- [x] Canvas nodes show real-time execution status during deployment
- [x] Policy engine: created, attached to gateway, cleaned up on delete (NL-to-Cedar deferred to Sprint 2)
- [x] Memory supports Semantic, Summary, and Episodic strategies
- [x] All security hardening items pass review
- [ ] No regressions in existing templates (run all 6 template deploys)
