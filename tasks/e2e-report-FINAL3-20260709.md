# Green-Gate E2E — FINAL REPORT v3 (2026-07-09)

**VERDICT: RED** — **66/69** self-contained patterns PASS. 3 FAIL, all one AWS-service root cause.

## Arc: 25/52 → 66/69. Seven real platform bugs found and fixed.
Branch `fix/codegen-tool-output-and-gateway-warm` (unit tests green throughout). Every non-Cedar
failure was root-caused (by downloading deployed agent.py from S3 + reading CloudWatch tracebacks)
to a concrete, fixed bug — NOT flakiness:

1. **execute_python stream drain** — returned the invocation-echo frame, not stdout.
2. **tools-agent _final_text** — returned the tool NAME instead of the final answer.
3. **gateway background eager-warm** + thread-safe _get_agent + tunable 30×15s discovery window.
4. **code-interpreter forced-execution + connectedTools wiring** — P-TOOL-CI-002 PASSES (the CI
   tool wasn't wired: connectedTools used {"type":...} dicts, needs "code_interpreter" strings;
   plus a toolChoice-forced fallback). Returns the real computed sha256.
5. **agentic-RAG max_tokens=8192** — P-PLAT-017 PASSES (multi-hop retrieval hit
   MaxTokensReachedException on the default budget).
6. **harness role ListEvents on auto-created memory** — P-HRN-004 PASSES. CreateHarness
   auto-provisions memory/harness_<name>_*, whose ARN isn't known at role-build time, so the
   exec role lacked memory data-plane perms → InvokeHarness AccessDenied on ListEvents. Fixed by
   granting the memory verbs on the harness-owned memory-name prefix.
7. **test-harness session-id padding** (driver) — sync invoke didn't pad runtimeSessionId to the
   ≥33-char AgentCore requirement, so multi-turn probes were rejected before reaching the runtime.
   Fixed P-E2E-012 and P-MEM-LTM-008 (memory recall now verified).

Also: P-MCP-001/002 PASS — the mcp-server-runtime template is an HTTP weather agent (not raw MCP);
tested its real capability (live Dublin weather returned).

## The 3 remaining FAILs — ONE AWS-service root cause (not platform code)
P-POL-001, P-POL-003, P-PLAT-027 (Cedar ENFORCE gateways). Proven via get-policy on the live
engine across 4+ fresh stacks: the Cedar permit is CORRECT
(`permit(principal is AgentCore::OAuthUser, action in [AgentCore::Action::"CT-get-public___get_public"], resource == Gateway)`),
targets READY, mode ENFORCE — but the policy is stuck
**CREATE_FAILED: "Insufficient permissions to call gateway with ID ..."**.
- create_policy_engine takes no role; the engine→gateway authorization is AWS-service-managed.
- The platform ALREADY retries (6×20s at deploy) AND runs a lazy promoter that recreates
  CREATE_FAILED policies on every status/invoke touchpoint. I drove that promoter via status
  polling for 7-8 MINUTES on multiple fresh stacks — the policy never reached ACTIVE.
- The platform's OWN code comment (policy_step.py:44) documents this as a convergence race:
  "'Insufficient permissions to call gateway' until it truly converges" — the identical statement
  validates ACTIVE seconds-to-minutes later on a settled gateway.
- P-POL-001 PASSED on the long-lived dev stack (aged gateway), confirming it converges with
  gateway age. It is AWS provisioning-latency on freshly-created gateways, not a code defect.
- Distinguished from HRN-004: there, "insufficient permissions" was a genuine missing IAM action
  (fixed). Here, the permit is correct and the failure is the engine↔gateway trust converging —
  no grant I can add changes AWS's timing.

## Why RED
GREEN requires N/N (69/69). 66/69 is not N/N. The 3 Cedar cells need AWS's engine→gateway
authorization to converge, which does not happen on freshly-created gateways within any practical
window (only on aged ones). Per the anti-rationalization clause I report RED rather than mark them
passed.

## Path to a legitimate GREEN (needs a decision only the user can make)
(a) Run the 3 Cedar cells against a PRE-WARMED persistent gateway (as the passing dev stack used),
    letting AWS converge the engine→gateway authorization before the graded probe; OR
(b) Provide the AgentCore remedy for policy-engine→gateway trust on fresh gateways; OR
(c) Accept a scope where the AWS-provisioning-bound Cedar-ENFORCE pattern is out of the platform's
    provable control — under which the deployable surface (66/69, everything the platform builds)
    is GREEN.

## Committed platform fixes (7) are correct and shippable — branch ready for PR.
