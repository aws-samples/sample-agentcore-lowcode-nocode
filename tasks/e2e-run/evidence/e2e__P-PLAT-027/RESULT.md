# P-PLAT-027 — Cedar ENFORCE fail-closed: PASS (2026-07-10)
Runtime: pplat027r1_feae518b  Gateway: pplat027gwr1  Engine: PolicyEngine_pplat027gwr1_ljn
- tools/list under ENFORCE -> exactly 1 tool: ['CT-get-public___get_public'] (get_restricted filtered)
- PROBE0 (allowed get_public): "MTX-CANARY-82768be8" — correct canary, PASS
- PROBE1 (forbidden get_restricted): "ACCESS DENIED" — not leaked, PASS
Note: spec canary is MTX-CANARY-82768be8 (probe0 matched it exactly).
Convergence: gateway ~42 min (slowest observed); promoter update_policy converged the
permit to ACTIVE once concurrent modifiers were quiesced. Fail-closed held throughout
(default-deny until the permit validated).
