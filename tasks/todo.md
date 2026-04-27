# AgentCore Flows — Sprint Tracker

## Previous Work (Complete)
- [x] Phase 1: Gateway/Memory/MCP bug fixes (7 bugs)
- [x] Phase 2: UI testing feedback fixes (5 fixes, 266 tests passing)
- [x] UI Redesign: AWS Console design system

## Active: Sprint 1 — Tool Generator E2E + Security + Core UX
See [sprint-1.md](sprint-1.md) for full details.

- [x] **Item 1: Tool Generator E2E** (Runtime -> Gateway -> Generated Tool)
  - [x] 1A. Fix Lambda handler format mismatch (dual-mode handler in GENERATION_PROMPT)
  - [x] 1B. Security hardening (AST validation, resource limits, API Gateway throttling)
  - [x] 1C. Code generator custom tool template (custom_tools in system prompt + tool-use directive)
  - [x] 1D. Custom tool cleanup on delete (IAM role tracking + detach/delete)
  - [x] 1E. E2E verified on live AWS (generate -> test -> deploy -> invoke -> cleanup)
  - [x] 1F. Fix: custom tool IDs leaking into gatewayTools causing empty schema error
  - [x] 1G. Fix: direct deploy path missing custom_tools in code generation
- [x] **Item 2: Chat Trigger** (chat bubble UI replacing Test tab in DeployPanel)
  - [x] Chat bubbles (user=blue right, assistant=gray left with avatar, system=amber centered)
  - [x] Typing indicator (3 bouncing dots)
  - [x] Session management (New Session, session ID display)
  - [x] Cold start retry messages as system chat bubbles
  - [x] Enter to send, Shift+Enter newline
  - [x] Auto-scroll, auto-focus on tab switch
  - [x] Delete button in session header
  - Note: reuses existing POST /api/test-runtime (no backend changes needed)
- [x] **Item 3: Execution States** (visual feedback on canvas nodes during deploy)
  - [x] executionState field + store actions in Zustand
  - [x] SFN step-to-node-type mapping in DeployPanel polling
  - [x] Visual badges: running (pulse+spinner), completed (green check), failed (red X)
- [x] **Item 4: Policy Integration** (direct deploy path + cleanup + frontend modal)
  - [x] Direct deploy: creates policy engine, Cedar policies, attaches to gateway
  - [x] Delete cleanup: deletes policy engine on resource teardown
  - [x] policy_result persisted to DynamoDB for cleanup
  - [x] PolicyConfigurationModal with Cedar rule editor + preview
  - Note: NL-to-Cedar deferred to Sprint 2
- [x] **Item 5: Memory Episodic Strategy** (enum + frontend modal)
  - [x] Added EPISODIC to ExtractionStrategy enum
  - [x] Strategy passthrough in direct deploy path
  - [x] MemoryConfigurationModal with strategy selector (Semantic/Summary/Episodic)

## Next: Sprint 2 — Architecture + Missing Backends
See [sprint-2.md](sprint-2.md) for full details.

- [ ] Sub-node architecture refactor (C1)
- [ ] Code Interpreter backend (H1)
- [ ] Browser Tool backend (H3)
- [ ] Identity outbound auth (H2)
- [ ] Evaluations full picker (L2)
- [ ] Governed Tool Access e2e (P4)
