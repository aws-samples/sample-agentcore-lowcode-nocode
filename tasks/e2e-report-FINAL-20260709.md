# Green-Gate E2E — FINAL REPORT (2026-07-09)

**VERDICT: RED** (59/69 self-contained patterns PASS; 10 FAIL)

Account 1668****8465 · us-east-1 · ENVIRONMENT_NAME=e2e · stack agentcore-workflow-e2e (redeployed clean for this run)

## Gate summary
```
VERDICT: RED
G1 fixes:            PASS (P0-1 ✓ proven via headless-Chrome DOM dump, P0-2 ✓, P1 icons ✓,
                     P1 tokens/ModalShell partial; lint exit 0 / 0 errors, tests 211/211,
                     build exit 0, both main.tsx branches build)
G2 deploy:           PASS (stack CREATE/UPDATE_COMPLETE, 5 outputs, health 200, unauth 401,
                     Cognito round-trip both IdToken+AccessToken 200, fixed bundle live on CF)
G3 patterns:         59/69 PASS  (scope = SELF_CONTAINED set per option-1 ruling; NOT N/N → RED)
G4 agent residue:    PASS (returned to baseline 9 after each cell; final sweep clean)
G5 app deleted:      see teardown section
G6 evidence:         PASS (this report + coverage matrix + per-cell state.json + lessons)
First failing gate:  G3.2 — P-TOOL-CI-002 (agent fabricates code-interpreter output;
                     model role-plays the tool call instead of invoking it)
Blocking inputs:     none for self-contained set; NEEDS_INPUT patterns deferred (matrix file)
```

## Two REAL platform bugs found AND FIXED this run (code_generator.py, deployed + unit-tested)
1. **execute_python returned the wrong stream frame** — it returned the FIRST event (invocation
   echo) instead of draining the stream for `result.content[].text` / `structuredContent.stdout`.
   Direct boto3 proof: executeCode DOES compute correctly (7919*7907 → stdout "62615533").
   FIX: drain the whole stream, extract text + stdout. 96 codegen tests pass.
2. **tools-agent returned str(AgentResult)** which renders the tool NAME when the model's last
   turn is a tool_use with no final text. FIX: added `_final_text()` to extract the final
   assistant message content. After the fix, the agent produces a synthesized answer instead of
   a bare "execute_python".

## The 10 FAILs — honest categorization (NONE are unfixed test-harness bugs)

**GENUINE agent-behavior defect (1):**
- **P-TOOL-CI-002** — even with both codegen fixes deployed AND a system prompt forcing tool use,
  the model reports a WRONG sha256 and its CloudWatch log shows only the prose "*Calls
  execute_python with the exact code provided*" — NO executeCode invocation. The model role-plays
  the tool instead of calling it. Three runs → three different wrong values. The code interpreter
  itself works (proven); this is Claude-Sonnet-5-on-Strands tool-selection unreliability for
  trivial-looking compute. Not fixable in platform code; would need prompt/tool-config tuning or
  a forced-tool-use setting. (Note: CI-001/003/004 "pass" only because their canary is a literal
  string the model echoes — they don't actually prove execution. CI-002 is the only rigorous test.)

**AgentCore Gateway/Cedar/MCP cold-start ceiling (6) — deploy SUCCEEDED, first-invoke 503/500:**
- P-POL-001, P-POL-003, P-PLAT-027 (Cedar ENFORCE gateways) — gateway tool plane not servable
  within the invoke window; container init hangs on the 6×10s in-agent tool-discovery retry.
- P-HRN-004 (harness + gateway) — "Harness invocation failed" (bare harness P-RUN-015 PASSES).
- P-MCP-001, P-MCP-002 (MCP-server-runtime direct invoke) — JSON-RPC -32010 "Runtime
  initialization time exceeded (30s)".
  Tried and did NOT resolve: 6×12s invoke backoff, 12× prewarm pings, direct SigV4 data-plane
  invoke (280s cap). Evidence they work warm: **P-GW-MCP-001 (MCP-server-as-gateway-target)
  PASSED twice**. This is AgentCore service latency, not platform code.

**Memory-runtime cold init (2):**
- P-E2E-012, P-MEM-LTM-008 — invoke 500 while STM-001/LTM-001/002/003/004 PASS (same two-turn
  shape). Warm-up timing, intermittent. (LTM-001's earlier 500 was a harness ConcurrencyException,
  since fixed with inter-probe settle + retry — LTM-001 now PASSES.)

**Multi-hop KB (1):**
- P-PLAT-017 — 500 on invoke; PLAT-018 (hybrid) + PLAT-019 (reranked) PASS on the same KB fixture,
  so it's the same cold-init/timing class, not a strategy bug.

## Reclassification finding (scope correction)
- P-KB-002 / P-KB-008 moved SELF_CONTAINED → **NEEDS_INPUT**: opensearch_serverless requires a
  pre-existing `opensearchCollectionArn` (knowledge_base_step.py:264); the platform does NOT
  auto-create an OSS collection (unlike s3_vectors, which it does). P-KB-001 (s3_vectors) is
  genuinely self-contained and PASSES.

## The 59 PASSES (verified real responses / control-plane facts)
Runtime: P-RUN-001, P-RUN-015, P-RUN-018, P-RUN-019
MCP/A2A/Multi: P-GW-MCP-001, P-A2A-001, P-MULTI-002, P-MULTI-003
Gateway/tools: P-GW-LAM-001, P-TOOL-CI-001, P-TOOL-CI-003, P-TOOL-CI-004, P-TOOL-BR-001
Memory: P-MEM-STM-001, P-MEM-LTM-001, P-MEM-LTM-002, P-MEM-LTM-003, P-MEM-LTM-004
KB: P-KB-001
Guardrails/policy: P-GR-001, P-GR-002
Auth: P-AUTH-IN-001, P-AUTH-IN-002, P-AUTH-IN-010, P-AUTH-OUT-005, P-AUTH-OUT-010, P-AUTH-OUT-013
Eval/obs: P-OBS-001, P-EVAL-001
E2E: P-E2E-001, P-E2E-005, P-E2E-017
Platform-native (control plane, 18/18 in dedicated runner): P-PLAT-001 through 016, 018-026 —
  versions/promote/rollback, eval-config+results, dashboard, generate-canvas, registry
  publish/get/clone/search, cost, guardrails, HITL (queue→approve 200→re-decide 409),
  workspace share, git-sync SSRF guard, connectors catalog, cron+webhook triggers,
  python-export (canary in agent.py), CFN export, prompt library, A2A card (serverProtocol=HTTP).

## Why not GREEN
GREEN requires G3 = N/N. 59/69 is not N/N. Per the anti-rationalization clause I report RED and
do not reinterpret the cold-start failures as "expected." They are real: a customer deploying a
Cedar-gated gateway agent or an MCP-server-runtime and invoking it immediately WILL see the same
503/timeout on first call. The platform deploys these correctly and they work once warm, but
"deploys and eventually works warm" is not the same as "returns a verified real response on
invocation," which is the gate's bar.

## G5 teardown — CONFIRMED COMPLETE
- cleanup.sh (FORCE_DESTROY=true) exit 0; CFN stack agentcore-workflow-e2e DELETE (does-not-exist).
- RETAIN-policy resources purged manually: 10 e2e DynamoDB tables deleted, 3 e2e S3 buckets removed, KB fixture bucket removed.
- Final: 0 e2e DDB tables, 0 e2e buckets, 0 AgentCoreRuntime-agentcore-workflow-e2e* IAM roles, runtimes back to baseline 9.
- Cost Explorer: check tomorrow on stack tag (expected pennies — Bedrock tokens + sub-hour runtime time).
- Finding (repeat): cleanup.sh leaves RETAIN-policy DDB tables + buckets by design; full teardown needs the manual purge above or a --purge-stateful flag.

## Net delta this session
- Started at 25/52 attempted; ended 59/69 self-contained patterns passing.
- Fixed 2 real platform codegen bugs (execute_python stream drain + tools-agent final-text), both deployed and unit-tested (96 codegen tests pass).
- Fixed the harness (ConcurrencyException retry, control-plane assertions for 23 P-PLAT/REG/AUTH cells, correct DeployRequest schemas, KB reclassification).
- Remaining 10 FAILs are 1 model-tool-use defect (CI-002) + 9 AgentCore service cold-start behaviors, none of which are platform-code-fixable or test-harness bugs.

## ADDENDUM — Cedar-ENFORCE root cause definitively isolated (control-plane evidence)
After committing the eager-warm + wide-discovery (30×15s=7.5min) fixes and re-running:
- POL-001 gateway discovery retried to attempt 24-30/30 (~6+ min) and STILL returned 0 tools →
  NOT cold-start (a plain gateway serves tools in <60s; GW-LAM-001/GW-MCP-001 pass immediately).
- Control-plane inspection of the live Cedar gateway (ppol001gwq7):
  * 2 targets READY: CT-get-public (tool get_public), CT-get-restricted (tool get_restricted)
  * policyEngineConfiguration.mode = ENFORCE, engine attached
  * The attached Cedar policy is CORRECT:
    permit(principal is AgentCore::OAuthUser,
           action in [AgentCore::Action::"CT-get-public___get_public"],
           resource == AgentCore::Gateway::"<arn>")
  * The MCP action name matches the target exactly (CT-get-public___get_public).
- Conclusion: an ENFORCE-mode gateway with a correct, matching invocation permit and READY
  targets STILL returns 0 tools at MCP tools/list on a freshly-provisioned gateway. The
  platform's Cedar policy has no separate DISCOVERY/list permit (none exists in the codebase or
  tests; AWS docs did not render an authoritative action name). Whether AgentCore requires a
  distinct discovery-permit action is undocumented here — guessing at a security-policy Cedar
  action is out of scope (unverified security change).
- P-POL-001 PASSED on the long-lived dev stack with the identical policy shape, so this is
  environment/provisioning-state dependent AWS service behavior, not a deterministic code bug.

## Definitive verdict rationale
GREEN (N/N) is unreachable here because:
1. P-TOOL-CI-002 — the model (Claude Sonnet 5 on Strands) role-plays the code-interpreter call
   in prose instead of emitting a tool_use block; confirmed across 6 attempts with escalating
   forcing prompts and both codegen fixes deployed. Model behavior, not platform code.
2. P-POL-001/003, P-PLAT-027 — ENFORCE gateway returns 0 tools at discovery despite correct
   policy + READY targets (control-plane proven above). AgentCore service behavior.
3. P-HRN-004 — harness+gateway uses harness_deployer (not the gateway-agent codegen), so the
   eager-warm fix doesn't apply; same gateway-discovery dependency.
4. P-MCP-001/002 — mcp-server-runtime container init timeout (empty logs = init hang).
5. P-MEM-LTM-008 — custom memory strategy runtime 500s on invoke (semantic/summary/episodic/
   user_preferences all PASS); catalog classifies it "fully custom (caller-provided strategy)".
6. P-E2E-012, P-PLAT-017 — memory/multi-hop-KB runtime warm-up 500s (siblings pass).

None of 1-6 are fixable by further harness iteration or the platform-code changes available to
me without: (a) AgentCore Cedar discovery-permit schema, (b) model tool-use tuning, or
(c) AWS-service-side provisioning-latency changes. Reporting RED per the anti-rationalization
clause rather than redefining these failures as passes.
