# Market Gaps Execution Plan

Branch: `feature/market-gaps`
Account: 123456789012, us-east-1 only
Cadence: one PR at the end, multiple commits per task.

## Per-task execution template

1. Read the task spec file in full.
2. Implement backend (models → storage → service → router → wire into main.py).
3. Implement infra (CDK resources + IAM + env vars).
4. Implement frontend (API client → components → wire into pages).
5. Unit tests (backend + frontend where practical).
6. `cd backend && python run_tests.py` — must pass locally before deploy.
7. `cd infra && npx cdk synth` — must succeed before deploy.
8. `./scripts/deploy.sh` (COGNITO_USERS=omrsamer@amazon.com).
9. Smoke test: `curl $CLOUDFRONT_URL/health`.
10. Bug bash: exercise each new endpoint with real data, check DDB, check CloudWatch logs.
11. Security bash: IAM scoping, auth required, input validation, secrets, CDK-NAG sanity check.
12. Commit per task with message format: `feat(taskNN/<area>): <summary>`.
13. Move to next task.

## Skipped features

- AgentCore Optimization (A/B testing, bundles) — not GA in us-east-1 for this account per CLI check.
  - Task 03 falls back to Lambda versioning primitives (which spec allows).
  - Task 07 falls back to Lambda alias weighted routing.

## Service verifications (done)

- EventBridge Scheduler ✅
- Bedrock Guardrails ✅
- Comprehend PII ✅
- SES ✅
- AgentCore Runtime ✅
- Cognito ✅
- AgentCore Harness / Optimization — ❌ (CLI verbs absent, will not rely on them)

## Tenant isolation pattern (critical)

Every new resource MUST be scoped by `user_id` extracted from the JWT claim. The API Gateway JWT authorizer passes claims in:

```
event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
```

I'll add a helper `get_user_id_from_event()` in `backend/src/app/shared/auth.py`
and a FastAPI dependency `require_user()` that all new routers use.

## Lessons to respect (from tasks/lessons.md)

- Multi-path sync between `codegen_step.py` (SFN) and `deployment.py` (direct)
- Gateway naming: target_name + 3 + tool_name ≤ 64
- Memory strategy keys via STRATEGY_KEY_MAP
- Lambda packaging: CDK packages `backend/` — don't manually zip
- SFN error handling: check both `event.get("error")` and `event.get("error_info")`
- AI schema sanitization before AWS APIs
- Module-level MCP/agent init in generated code
- Registry records flow: draft → pending → approved

## Out-of-scope bugs

If I hit a pre-existing bug blocking progress, file it in `tasks/lessons.md` and route around it.
