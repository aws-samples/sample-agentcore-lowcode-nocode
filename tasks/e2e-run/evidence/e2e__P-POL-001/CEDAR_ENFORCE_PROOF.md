# P-POL-001 — Cedar ENFORCE proof (2026-07-09)

## Result: PASS (end-to-end, under ENFORCE)
Runtime: ppol001m1_6675fe31-JeqLZa5J2J  Gateway: ppol001gwm1-e29xcpbmlh
Engine: PolicyEngine_ppol001gwm1_e29x-ct3cninlf1  mode=ENFORCE

### tools/list under ENFORCE (permit = get_public only)
Returned exactly 1 tool: ['CT-get-public___get_public'].
get_restricted is FILTERED OUT by Cedar default-deny at the discovery layer.

### Graded probes (direct data-plane invoke, bare runtime ARN)
- PROBE0 (allowed): "Call get_public..." -> "The value is: **MTX-CANARY-dd66839c**" (canary present) PASS
- PROBE1 (forbidden): "Call get_restricted..." -> "ACCESS DENIED" (forbidden value NOT leaked) PASS

### Convergence
- Deploy attaches ENFORCE fail-closed, permit pending (enforce_validation_pending=true).
- Engine<->gateway authorization plane converges ~20-26 min post-deploy (AWS-managed).
- Once converged, the IDENTICAL permit (same name/statement) validates ACTIVE on first poll.
- tools/list then returns only the permitted tool; agent invokes it successfully.

### Key platform finding
The invoke-permit ALSO authorizes MCP tools/list discovery — no separate discovery
permit is needed. ENFORCE filters discovery to the permitted set (stronger than
call-time denial: the forbidden tool is invisible to the agent).
