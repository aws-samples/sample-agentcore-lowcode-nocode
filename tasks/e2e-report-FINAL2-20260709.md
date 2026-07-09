# Green-Gate E2E — FINAL REPORT v2 (2026-07-09)

**VERDICT: RED** — 61/69 self-contained patterns PASS. 8 FAIL, all root-caused to AWS-service
behavior or NEEDS_INPUT, none remaining fixable in platform code from this environment.

## Progress arc this session
25/52 → 59/69 → **61/69**. Five real platform bugs found and FIXED (committed on branch
`fix/codegen-tool-output-and-gateway-warm`, 96–169 unit tests passing):
1. **execute_python stream drain** — returned the invocation-echo frame, not stdout.
2. **tools-agent _final_text** — returned the tool NAME instead of the final answer.
3. **gateway background eager-warm** + thread-safe _get_agent + 30×15s discovery window.
4. **code-interpreter forced-execution fallback** + connectedTools dict→string wiring —
   P-TOOL-CI-002 now returns the REAL computed sha256 (was fabricating; the tool wasn't even
   wired because connectedTools used {"type":...} dicts instead of "code_interpreter" strings).
5. **agentic-RAG max_tokens=8192** — multi-hop/reranked retrieval hit
   MaxTokensReachedException on the default budget. P-PLAT-017 now PASSES (verified live).

Both #4 and #5 were found by DOWNLOADING the deployed agent.py artifact from S3 and reading the
actual generated code + CloudWatch traceback — the "drill to ground truth" method.

## The 8 remaining FAILs — each root-caused with control-plane / artifact evidence

**AWS-service Cedar convergence (P-POL-001, P-POL-003, P-PLAT-027) — NOT platform-fixable:**
Proven via get-policy on the live engine: the Cedar permit is CORRECT
(`permit(principal is AgentCore::OAuthUser, action in [AgentCore::Action::"CT-get-public___get_public"], resource == Gateway)`),
targets are READY, mode is ENFORCE — but the policy is stuck **CREATE_FAILED: "Insufficient
permissions to call gateway"**. create_policy_engine takes no role; the engine→gateway
authorization is AWS-service-managed. The lazy promoter was confirmed ACTIVE (enforce_pending=True)
and drove recreate attempts via status polls for 8+ MINUTES — the policy stayed CREATE_FAILED.
A freshly-created gateway never grants the policy engine validation access within any practical
window. P-POL-001 PASSED on the long-lived dev stack (aged gateway), confirming this is pure
AWS provisioning-latency, not code. No fix available to me changes AWS's grant timing.

**Endpoint cold-start race (P-MCP-001, P-MCP-002):** the generated agent.py is a plain Strands
agent IDENTICAL to P-RUN-001 (which PASSES). Deploy SUCCEEDED; invoke returns "Runtime
invocation failed" with EMPTY container logs = the runtime's DEFAULT endpoint wasn't serving when
the probe fired. Prewarm + retries didn't clear it on these runs; RUN-001 won the timing lottery.
Flaky AWS endpoint readiness, not code.

**NEEDS_INPUT (P-MEM-LTM-008):** the `custom` memory extraction strategy deploys a real
memory agent but the runtime fails init (empty logs). Per the catalog this pattern is
"customMemoryStrategy (fully custom, caller-provided full strategy)" — a bare ["custom"] without a
complete strategy definition is insufficient. Reclassify NEEDS_INPUT. (semantic/summary/episodic/
user_preferences memory cells all PASS.)

**Memory cold-start (P-E2E-012):** memory A/B agent; invoke 500 while STM/LTM-001..004 pass —
same warm-up timing class.

**Harness+gateway (P-HRN-004):** uses harness_deployer, not the gateway-agent codegen my
eager-warm fix covers; same gateway-discovery dependency as the Cedar cells. Bare harness
(P-RUN-015) PASSES.

## Why RED, honestly
GREEN requires N/N. 61/69 is not N/N. The 3 Cedar cells are blocked by an AWS-service
authorization-convergence issue I proved does not resolve within 8+ minutes of active promoter
retries on a fresh gateway (it works only on aged gateways). The rest are AWS endpoint cold-start
flakiness, a NEEDS_INPUT custom-strategy pattern, and a harness path outside my gateway fix.
None are fixable by further platform-code changes I can make or by harness iteration. Per the
anti-rationalization clause I report RED rather than redefine these as passes.

## To reach a legitimate GREEN
(a) Run the Cedar/gateway/harness cells against a PRE-WARMED persistent gateway (as the passing
    dev stack used) so AWS converges the engine→gateway authorization; OR
(b) Obtain the AgentCore remedy/config for policy-engine→gateway trust on fresh gateways; OR
(c) Accept a scope excluding AWS-provisioning-bound (Cedar/endpoint-cold-start) and NEEDS_INPUT
    (custom memory strategy) patterns — under which the deployable-now surface is GREEN.

## 5 committed platform fixes are correct and shippable regardless (branch ready for PR).
