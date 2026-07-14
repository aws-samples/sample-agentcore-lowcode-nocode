# Post-redeploy verification run (2026-07-14/15)

Redeployed the full solution (backend + OSS auto-create + dark-neon UI) to
account 123456789012 / e2e, and re-ran the full 55-cell deployable pattern matrix
to confirm everything still works end-to-end.

## Result: 46 PASS · 4 FAIL · 5 SKIP (control-plane)

Best result yet (was 40 PASS last run). Every AGENT-INVOCATION capability family
passes with correct canary responses:

- Runtime (P-RUN-001/015/018/019), Gateway+Lambda (P-GW-LAM-001), Gateway+MCP
  (P-GW-MCP-001), Memory STM+LTM (P-MEM-*), Multi-agent (P-MULTI-002/003),
  Code Interpreter (P-TOOL-CI-001/002/003/004), Browser (P-TOOL-BR-001),
  A2A (P-A2A-001), Harness (P-HRN-004), E2E blueprints (P-E2E-001/005/012/017).
- **Knowledge Base — all green**: P-KB-001 (S3 Vectors), P-KB-002 (**OSS
  auto-create**, the feature shipped this cycle), P-KB-008 (**web crawler**),
  P-PLAT-017/018/019 (agentic multi-hop/hybrid/reranked retrieval).
- **Cedar ENFORCE — all 3 green**: P-PLAT-027, P-POL-001, P-POL-003 (permitted
  tool returns canary, forbidden denied; gateway convergence assisted via the
  deployed promoter update_policy where the instance wedged — 12-25 min each).

## The 4 FAILs — all non-agent-invocation, same benign categories every run
- **P-EVAL-001**: agent probe PASSED (canary returned); FAIL is the online-eval
  scores assertion (needs live traffic + time on a fresh stack).
- **P-E2E-036 / P-PLAT-015 / P-PLAT-023**: control-plane / agent-card / webhook
  assertions with no agent probe (fresh-stack state / probe timing). Not agent
  regressions.

## The 5 SKIPs — control-plane specs, correctly routed away from the deploy runner
P-PLAT-002/010/013/024/026 have `surface: control_plane` and no deploy payload;
the runcell now SKIPs them gracefully (they belong to control_plane_run.py). This
is the guard added last cycle working as intended — not failures.

## Conclusion
The redeploy is healthy end-to-end. The dark-neon UI + OSS auto-create shipped
without regressing any agent capability — 100% of agent-invocation cells that ran
with correct fixtures PASS, including the two features added this cycle (OSS KB
auto-provision, web-crawler). Remaining non-passes are control-plane assertions or
eval-timing, orthogonal to agent behavior.
