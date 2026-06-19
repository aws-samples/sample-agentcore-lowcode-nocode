# Fix: AI generator tool→runtime edges + custom tool Configure button (2026-06-19)

## Bug 1 — "Cannot connect tool to runtime" (AI agent generator)
Root cause: `GENERATION_PROMPT` tells the LLM every non-runtime node edges
straight to the runtime. For `tool` nodes that's invalid — the canvas matrix
(`frontend/src/types/validation.ts`) only allows `tool → gateway`. The generator
also omits the required `gateway` node when tools exist, so even rewired it
wouldn't deploy (tools attach to a gateway at deploy time).

- [ ] Update `GENERATION_PROMPT` in `backend/src/app/services/agent_generator.py`:
      tools connect to a gateway (not runtime); a gateway is REQUIRED whenever any
      tool exists; gateway → runtime; show the canonical `tool → gateway → runtime` shape.
- [ ] Strengthen `_validate_spec`: if any `tool` node exists, require the gateway
      wiring — each tool edges to a gateway, a gateway → runtime edge exists, and
      tools do NOT edge directly to runtime. Error strings feed the existing
      self-correction retry loop.
- [ ] Tests in `backend/tests/test_agent_generator.py`: reject tool→runtime,
      reject tools-without-gateway, accept tool→gateway→runtime.

## Bug 2 — custom tool "Configure" button does nothing
Root cause: `App.tsx:753` only renders a modal for `tool` nodes when
`isKnowledgeBase` is truthy. Custom (and plain built-in) tools have no modal,
so the Configure/double-click action opens nothing.

- [ ] New `frontend/src/components/modals/ToolConfigModal.tsx` (basic editable):
      edit displayName/name, description, enabled; show inputSchema + lambdaCode
      read-only. Preserves toolId/isCustom and all other fields on save.
- [ ] Wire it into `App.tsx` for `componentType === 'tool'` when NOT a KB tool.

## Verification
- [x] `pytest backend/tests/test_agent_generator.py` → 15 passed
- [x] `npm run build` (tsc -b + vite) → clean
- [x] LIVE: real Bedrock generation of the exact Slack→Jira prompt now returns
      `tool -> gateway -> runtime` (gw->rt, slack_tool->gw, jira_tool->gw) →
      passes backend _validate_spec AND the frontend CONNECTION_COMPATIBILITY
      matrix (0 canvas errors). See backend/tests/live_generator_e2e.py.
- [x] LIVE: deployed a `tool -> gateway -> runtime` agent (built-in
      duckduckgo_search through a Cognito gateway) to real AWS via the deploy
      Step Functions. SFN SUCCEEDED, runtime READY, gateway target DynamicTools
      READY (real Lambda, not zero targets). Invoke returned a real
      tool-grounded answer ("Dario Amodei is the CEO of Anthropic", quoting live
      search output). Full cleanup verified. (agentcore-real-tester)
- [x] LIVE: ToolConfigModal component tests (render, save-preserves-hidden-fields,
      empty-name-blocks-save, built-in-hides-impl-tab) → 4 passed.
- [x] Capture lesson in tasks/lessons.md

## Pre-existing test drift fixed (production-readiness pass)

Running the FULL suites surfaced 3 stale frontend tests (NOT caused by this
change — all date to the initial import commit 6331f43; they test old behavior):

- [x] `dragDrop.test.ts` — asserted blanket `validationStatus === 'pending'`;
      source intentionally returns `'valid'` for pre-configured types
      (code_interpreter/browser/observability). Test now encodes the real contract.
- [x] `FlowSidebarItem.test.tsx` — asserted the pen click calls `onRename(id,name)`
      (old window.prompt flow). Component now uses inline-edit. Rewrote to: pen
      reveals input; `onRename(id, oldName, newName)` fires on Enter; no-op on
      unchanged; Escape cancels. Fixed stale `OnRenameFn` type (3-arg).
- [x] `FlowSidebar.test.tsx` — asserted `window.prompt` create flow. Component now
      uses inline-create. Rewrote to type-into-input + Enter; added Escape-cancel.
      Wrapped mount in `act()` (renderSidebar helper) to clear the React
      "not wrapped in act" warnings from the async fetchFlows effect.

Note: the earlier "flaky" failures (backend session test + extra FE timeouts) were
CPU STARVATION from running backend+frontend suites concurrently (import times
ballooned to 800s+, tripping 5s test timeouts). Run isolated: backend 4:18 (was
22:00), all green. Not a real defect — but I mislabeled drift as "flaky" before
isolating; fixed both characterization and the tests.

## Final verification (all isolated, clean signal)
- [x] backend `pytest` (full) → 713 passed, 8 skipped, 0 failed (258s)
- [x] frontend `vitest` (full) → 211 passed, 0 failed, 0 act() warnings
- [x] frontend `npm run build` (tsc -b + vite) → clean
- [x] backend generator unit tests → 15 passed
- [x] LIVE Bedrock generation + LIVE AWS deploy/invoke (prior turn) → passed

## Review

Bug 1 (generator): root cause was a prompt rule that said EVERY non-runtime node
edges to the runtime — wrong for `tool` nodes, which the canvas matrix only lets
connect to a `gateway`. Two tool nodes → two "Cannot connect tool to runtime"
errors. Fixed `GENERATION_PROMPT` to teach the `tool -> gateway -> runtime` shape
and require a gateway whenever tools exist, and hardened `_validate_spec` to
reject tool→runtime edges, tools without a gateway, and orphan tools — all via
error strings that drive the existing self-correction retry loop. The deeper
issue (no gateway generated at all) is covered by the same gateway-required rule.

Bug 2 (UI): `App.tsx` only rendered a `tool` modal when `isKnowledgeBase` was
truthy, so custom/built-in tools had no Configure modal. Added
`ToolConfigModal` (edit name/description/enabled; read-only inputSchema +
lambdaCode for custom tools) and rendered it for non-KB tool nodes. All
unsurfaced fields (toolId/isCustom/lambdaCode/inputSchema) are preserved on save
so deploy-time tool extraction keeps working.

Files: backend/src/app/services/agent_generator.py,
backend/tests/test_agent_generator.py,
frontend/src/components/modals/ToolConfigModal.tsx, frontend/src/App.tsx.
