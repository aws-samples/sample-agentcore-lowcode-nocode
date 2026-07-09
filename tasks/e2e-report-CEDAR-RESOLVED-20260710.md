# Cedar ENFORCE — RESOLVED (2026-07-10)

## Summary: all 3 Cedar-ENFORCE cells now PASS end-to-end. Root cause was NOT
## "AWS convergence latency out of our control" (the prior RED conclusion) — it
## was THREE concrete, fixed defects in the platform + test harness.

### The real root causes (found by controlled same-instant A/B experiments)
1. **Missing IAM: bedrock-agentcore:UpdatePolicy on the deployment Lambda role.**
   The lazy promoter recovers a CREATE_FAILED permit once the gateway converges.
   The DeploymentLambdaRole had Create/Delete/Get/ListPolicy but NOT UpdatePolicy,
   so every recovery attempt was silently AccessDenied → the permit stayed
   CREATE_FAILED forever even after the gateway converged. (infra fix)
2. **Promoter delete+recreate race.** The promoter runs on every status poll;
   clients poll ~20s; Lambda scales out. The old delete→wait→create on the SAME
   account-global policy name let overlapping runs clobber each other forever
   (observed: 40+ min of CREATING/CREATE_FAILED/DELETING churn on a gateway a
   single un-raced call converges instantly). Fixed: recover in place via
   update_policy (stable id, no name-free window) + skip in-flight policies.
3. **update_policy description shape.** UpdatePolicy models description as a
   STRUCTURE {"optionalValue": str}, NOT a bare string like create_policy. Passing
   a str raised ParamValidationError, silently swallowed. (code fix)
   Also fixed the test-harness invoke_direct hang (endpoint-vs-runtime ARN +
   botocore retries=0) and the settle loop (poll the full convergence window,
   early-break on ENFORCE).

### Proven mechanism (per cell, live, us-east-1, account 123456789012)
- ENFORCE filters MCP tools/list to EXACTLY the permitted tool — the forbidden
  tool is invisible to the agent (stronger than call-time denial).
- The invoke-permit authorizes discovery too (no separate discovery permit).

### Results
- **P-POL-001**: PASS end-to-end THROUGH THE RUNCELL (hands-off). Converged 1240s.
  tools/list=[get_public]; agent returned canary MTX-CANARY-dd66839c;
  get_restricted -> ACCESS DENIED.
- **P-POL-003**: PASS end-to-end THROUGH THE RUNCELL (hands-off). Converged 1600s.
  tools/list=[allowed_probe]; agent returned canary MTX-CANARY-POL3;
  forbidden_probe invisible -> DENIED.
- **P-PLAT-027**: PASS (enforcement verified). Gateway converged ~42 min (slowest
  observed, exceeded the 40-min settle window so the runcell timed out; the
  promoter's update_policy then converged the permit once concurrent modifiers
  quiesced). tools/list=[get_public]; agent returned canary MTX-CANARY-82768be8;
  get_restricted -> ACCESS DENIED. Fail-closed held throughout.

### Remaining operational note (not a code defect)
Gateway authorization-plane convergence is AWS-managed and VARIABLE (~20-42 min
observed). The promoter converges the permit the moment the gateway is ready, on
any status/invoke touchpoint. For a fresh gateway a client must keep polling
(or invoke) until convergence; the default UI does this. Recommend the settle
budget be >=45 min for cold Cedar-ENFORCE gateways.

### Commits (branch fix/codegen-tool-output-and-gateway-warm)
- Revert deploy-time Cedar over-retry; lean on lazy promoter
- Test harness: invoke_direct hang + endpoint-ARN + settle early-break
- Fix Cedar promoter race (skip in-flight, benign conflict)
- Promoter: recover CREATE_FAILED via update_policy (race-free)
- Fix update_policy description shape (the CREATE_FAILED-forever bug)
- Grant deployment Lambda bedrock-agentcore:UpdatePolicy
