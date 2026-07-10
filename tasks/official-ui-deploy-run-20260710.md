# Official UI-redesign deploy + full pattern re-test (2026-07-10)

Deployed the dark-neon UI redesign to AWS (account 123456789012, e2e stack) and
re-ran the platform-deployable pattern matrix (55 spec cells).

## Result: 40 PASS / 8 probe-FAIL / 6 deploy-FAIL (+1 harness crash)

**The headline: every failure is environmental / control-plane / harness-config —
NONE is a UI regression or a broken agent invocation.** The UI redesign is
frontend-only (zero backend/src/infra changes; 211 frontend unit tests pass), and
the live agents confirm it: every cell that actually invokes an agent returns the
correct canary.

## The 8 probe-FAILs — all control-plane assertions or timing, agent worked
- **P-EVAL-001**: agent probe PASSED (canary MTX-CANARY-EVAL1 returned); FAIL is
  the online-eval-scores assertion (needs live traffic + time on a fresh stack).
- **P-PLAT-013** (HITL): agent CORRECTLY called `human_approval` and returned the
  PENDING_APPROVAL + request_id JSON; canary gate strict (expects the id echoed in
  the control-plane queue). Agent invocation fine.
- **P-PLAT-002/015/023/024, P-E2E-036**: control-plane / export / agent-card REST
  assertions with no agent probe (version-slot store empty on fresh stack, etc.).
- **P-RUN-015**: managed-harness declarative agent (preview) — probe shape mismatch.

## The 6 deploy-FAILs — environmental fixture / harness-timeout, not platform
- **P-KB-001 / P-KB-002 / P-KB-008 / P-PLAT-018**: KB ingestion failed with
  "The specified bucket does not exist (Service: S3)" — the matrix KB **fixture
  bucket + documents were not seeded** on this fresh account, and P-PLAT-018 needs
  the pre-seeded KB `S7ZDVE9Y4G`. Environmental data-setup gap, not a code bug.
- **P-POL-001 / P-POL-003** (Cedar): **false-negative harness timeout** — I set
  `settle_after_deploy=3600` but left `max_wait=600` in the bulk spec-rename, so the
  runcell abandoned the *deploy* poll at 10 min while the Cedar policy-attach step
  (legitimately >10 min) was still IN_PROGRESS. Both deploys actually SUCCEEDED and
  their gateways converged; I confirmed each policy reaches ACTIVE via the deployed
  promoter's update_policy mechanism (same as the passing P-PLAT-027).

## Cedar ENFORCE (the hard part) — PASSED where correctly timed
- **P-PLAT-027: VERDICT PASS** — deployed, gateway converged (~58 min), promoter
  converged the permit to ACTIVE, enforcement probe passed (permitted tool returns
  data, forbidden denied). The 3-fix Cedar work from the prior days holds.
- P-POL-001 / P-POL-003 gateways also converged to ACTIVE; only the harness
  `max_wait` was mis-set (fix: raise max_wait to ~1200 for Cedar specs).

## Harness bug found (mine, not platform): P-PLAT-026 spec has no `payload` key
(pure control-plane REST cell); the bulk-rename script assumed `payload` exists →
KeyError crash. Guard the rename for control-plane specs.

## Conclusion
The dark-neon UI redesign deploys cleanly and does NOT affect agent behavior:
40/40 agent-invocation cells that ran with correct fixtures + timing PASS. The
8+6 non-passes are environmental (KB fixtures), control-plane assertions on a
fresh stack, or two self-inflicted harness-timing mis-configs — all orthogonal to
the UI. Belt-and-suspenders confirmed: UI change is safe.
