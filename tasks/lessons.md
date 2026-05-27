# Lessons Learned

## 2026-03-07: End-to-End Pattern Fix

### Bug 1: API Response Key Inconsistency
- `list_gateway_targets` can return targets under `items`, `targets`, or `gatewayTargetSummaries` depending on SDK version
- Same for `list_gateways`: `items`, `gateways`, or `gatewaySummaries`
- **Rule**: Always check ALL possible response keys. Created helper functions `_get_targets_from_response()` and `_get_gateways_from_response()`.

### Bug 2: customer-support-blueprint Template ID Mismatch
- Gateway deployer had `if template_id == "customer-support-assistant"` but the actual template sends `customer-support-blueprint`
- DynamicTools Lambda only implements search/weather tools, NOT customer support tools
- Customer support tools need the dedicated `AgentCoreCustomerSupportTools` Lambda
- **Rule**: When routing on template_id, also check the actual gateway_tools to determine which Lambda to use. Don't rely solely on exact template string matching.

### Bug 3: Missing secretsmanager:GetSecretValue in CDK
- The CDK stack's step Lambda role had `CreateSecret`, `DeleteSecret`, `PutSecretValue` but was missing `GetSecretValue`
- The OAuth2 credential provider stores client_secret in Secrets Manager; gateway role needs read access
- This caused MCP targets to reach `UPDATE_UNSUCCESSFUL` status
- **Rule**: When adding Secrets Manager permissions, always include CRUD: Create, Get, Put, Delete.

### Bug 4: Gateway Role Policy Silent Failure
- When reusing an existing gateway role, the policy update was wrapped in try/except with a warning log
- If the update failed silently, the role would lack required permissions
- **Rule**: IAM policy updates on existing roles should be hard errors, not warnings, especially for MCP patterns that depend on secretsmanager access.

### Bug 5: Step Functions Catch puts error at `$.error_info`, not `$.error`
- `status_update_step.py` checked `event.get("error")` but the SFN Catch handler uses `result_path="$.error_info"`
- On failure, the Lambda saw no error and marked deployment as SUCCEEDED
- Partial results (gateway_result, mcp_server_runtime_id) were NOT saved in the failure path
- **Rule**: Always check BOTH `event.get("error")` and `event.get("error_info")` in SFN step handlers. Save partial results even on failure for cleanup.

### Bug 6: Multi-Runtime Deployable Node Selection
- `firstRuntimeNode` used `nodes.find()` which picks the first added node
- In drag-and-drop `Runtime → Gateway → MCP Server Runtime`, if the MCP Server was added first, it was incorrectly selected as the deployable agent
- **Rule**: When multiple runtimes share a gateway, detect the MCP server pattern and exclude target runtimes from deployable selection. Use protocol (MCP vs HTTP) or connection count as heuristic.

### Bug 7: Delete Handler Can't Find Partial Deployments
- Delete scans DynamoDB by `runtime_id`, but on partial failure, `runtime_id` is null
- Frontend falls back to `deployment_id` as the runtime_id, but the scan wouldn't find it
- **Rule**: Delete handler should also try direct `store.get(deployment_id)` lookup when scan-by-runtime_id finds nothing.

## 2026-03-08: Sprint 1 Production Bugs

### Bug 8: Custom Tool IDs Leaking into gatewayTools
- Frontend `App.tsx:146` pushed ALL tool IDs (including custom/generated tools) into `gatewayTools`
- Backend `gateway_deployer.py` looked up each ID in `GATEWAY_TOOL_SCHEMAS` (predefined tools only)
- Custom tool IDs like "simple_calculator" returned empty schemas list → empty `inlinePayload` → AWS ValidationException
- **Root cause**: No distinction between predefined gateway tools and user-generated custom tools at the frontend level
- **Fix**: Two layers — (1) Frontend: `if (toolConfig?.toolId && !toolConfig?.isCustom)` filter, (2) Backend: `if schemas:` guard before CreateGatewayTarget
- **Rule**: Custom tools follow a completely separate deployment path (individual Lambda per tool). Never mix them into the predefined tool schema lookup. Always add backend safety nets for frontend filtering assumptions.

### Bug 9: Direct Deploy Path Missing custom_tools in Code Generation
- `deployment.py:968` called `cg_generate_agent_code()` with only `config` and `template_id` when `template_id` was set
- Missing `tools`, `gateway_tools`, `custom_tools` params meant the agent's system prompt never mentioned custom tools
- SFN path (`codegen_step.py`) was NOT affected — it correctly passes all params
- **Rule**: Any new field added to code generation MUST be added to BOTH paths: (1) `codegen_step.py` (SFN) and (2) `deployment.py` (direct deploy). These two paths must stay in sync.

### Bug 10: AI-Generated inputSchema Has Unsupported Keys for Gateway API
- AI tool generator (Claude Sonnet) produces JSON Schemas with `default`, `enum`, `format`, etc. keys
- The Gateway `CreateGatewayTarget` API only allows: `type`, `properties`, `required`, `items`, `description` in property definitions
- Custom tool Lambda was created successfully but the target creation failed silently (`except` caught the error, logged it, continued)
- **Root cause**: No sanitization of AI-generated schemas before passing to AWS API. Error was swallowed at line 1146.
- **Fix**: Added `_sanitize_gateway_schema()` that recursively strips unsupported keys from property definitions
- **Rule**: ALWAYS sanitize external/AI-generated data before passing to AWS APIs with strict schema validation. The Gateway API is especially strict about JSON Schema property keys.

### Bug 11: Gateway Tool Names Exceed Bedrock 64-Char Limit
- Gateway returns tool names as `{TargetName}___{ToolName}` to MCP clients
- Old naming: `CustomTool-ireland-traffic-conditions___ireland_traffic_conditions` = 66 chars > 64 limit
- Bedrock Converse API rejects tool names > 64 characters
- **Fix (two layers)**: (1) Gateway deployer: dynamically compute max target name length = `64 - 3 - len(tool_name)`, use short `CT-` prefix. (2) Code generator: `_to_bedrock_tools()` returns a `name_map` to translate truncated names back to full gateway names for `tools/call`.
- **Rule**: Gateway target names MUST be short. Formula: `len(target_name) + 3 + len(tool_name) <= 64`. Use `CT-` prefix (3 chars) instead of `CustomTool-` (11 chars) for custom tool targets.

### Bug 12: Manual Lambda Deploy Broke All Endpoints (Missing lib/ Dependencies)
- Manual `aws lambda update-function-code` zipped only `src/` from inside `backend/src/`, missing:
  1. The `src/` path prefix (handler expects `src/app/deployment_handler.handler`)
  2. The `lib/` directory containing ALL Python deps (fastapi, mangum, boto3, pydantic, etc.)
- CDK packages the entire `backend/` directory: `src/` (code) + `lib/` (pre-installed deps from `pip install -r requirements-lambda.txt -t backend/lib/`)
- **Rule**: When manually updating Lambda code, ALWAYS zip from `backend/` and include BOTH `src/` and `lib/`: `cd backend && zip -r deploy.zip src/ lib/`
- **Better rule**: Prefer `cdk deploy` over manual Lambda updates to avoid packaging mistakes

### Bug 13: Generated Agent Code Used Per-Request MCP Init Instead of Module-Level
- Old code created MCPClient, called `list_tools_sync()`, and created Agent inside every `invoke()` call
- Official pattern (from `amazon-bedrock-agentcore-samples/01-tutorials/02-AgentCore-gateway/04-integration/01-runtime-gateway`) does module-level init: `mcp_client.start()` once, fetch tools once, create Agent once
- Old code also used `async def invoke(payload, context)` — official pattern uses `def invoke(payload)` (sync, single arg)
- Old memory agent used manual urllib MCP (`_mcp_request`, `_list_gateway_tools`, `_call_gateway_tool`, `_to_bedrock_tools`) instead of MCPClient
- **Fix**: Rewrote both `_generate_strands_gateway()` and `_generate_memory_agent()` to use module-level Strands Agent + MCPClient with `get_full_tools_list()` pagination
- **Rule**: ALWAYS follow the official tutorial patterns. Gateway agent code must: (1) init MCP client at module level with `.start()`, (2) fetch tools with pagination, (3) create Agent once, (4) use sync entrypoint `def invoke(payload)`. The Strands Agent handles the full tool-use loop — never manually implement Converse API + tool calling when using Strands.

### Lesson: Integration Test Report False Positives
- "Tool generator returns clarifications instead of code" — this is BY DESIGN (multi-turn: CLARIFICATION_PROMPT first, GENERATION_PROMPT on subsequent calls with history)
- "Session memory not working" — tester sent only `sessionId` without `history` field. Backend requires explicit `history` array for context.
- **Rule**: Before filing a bug from integration tests, verify the expected behavior by reading the source code. Multi-turn APIs need history, not just session IDs.

### Bug 15: OTEL Drift Across Three Deploy Paths (similar shape to Bug 9)
- Three places construct OTEL_* env vars: `services/deployment.py` (direct), `step_handlers/runtime_configure_step.py` (SFN), `services/cfn_template_generator.py` (CFN export). Each had different / wrong values.
- Direct deploy used a non-existent `https://otel.{region}.amazonaws.com` endpoint. SFN injected nothing. CFN hardcoded `localhost:4318`.
- **Fix**: Single helper `services/observability.build_otel_env_vars()` consumed by all three. New `Observability` node config (provider preset, endpoint, sample rate, secret ARN) drives it.
- **Rule**: Any OTEL/runtime-env change must touch all three call sites, plus `deployment_handler.py` (passes `observability_config` into the SFN input) and `iam_step.py` (scoped `secretsmanager:GetSecretValue` for the auth header).

### Bug 16: OTLP Exporter Missing from Dependency Bundles
- Strands' `StrandsTelemetry().setup_otlp_exporter()` lazily imports `opentelemetry.exporter.otlp.proto.http.trace_exporter`. If the package isn't bundled, the call silently fails with ModuleNotFoundError logged at WARN.
- `strands-mcp.zip` had `opentelemetry-api/sdk/instrumentation/semantic-conventions` but **not** the exporter. `base.zip` had no OTel at all.
- **Fix**: Added `opentelemetry-exporter-otlp-proto-http` to both bundles, plus the API/SDK/semantic-conventions packages to `base.zip`.
- **Rule**: When relying on a lazy-imported optional package, verify it's in the bundle with `unzip -l backend/agentcore-deps/<bundle>.zip | grep <package>`. Don't trust transitive deps.

### Bug 17: GenAI-Convention Attributes Hidden Behind Opt-In
- Strands gates rich GenAI semantic-convention attributes (input/output messages, tool definitions, latest token-usage names) behind `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`. Without it, Langfuse traces are present but missing token counts and cost rollups.
- **Fix**: `build_otel_env_vars()` always sets this opt-in when telemetry is enabled.
- **Rule**: Whenever wiring up a new SDK's tracing path, search its source for `*_OPT_IN` env vars — there's almost always one gating the rich semantics needed by downstream tools.

### Bug 18: AgentCore Runtime has NO localhost OTLP sidecar (the `agentcore_native` provider preset was a lie)
- The `agentcore_native` provider preset defaulted `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`. Documented assumption: AgentCore Runtime ships a sidecar that forwards to CloudWatch GenAI dashboards.
- **Live test 2026-05-15 disproved this.** Runtime CloudWatch logs showed: `Transient error HTTPConnectionPool(host='localhost', port=4318): Max retries exceeded ... Connection refused`. Every span silently dropped at connect time.
- **Fix**: Removed `agentcore_native` from the provider Literal and from the modal preset list. Default provider is now `langfuse`. Removed `dual_export_native` flag and its codegen branch. If AWS later ships a sidecar, this can be re-introduced — until then, do not pretend.
- **Rule**: Never bake a provider preset into the UI without proving traffic gets there end-to-end on a live deploy. "The docs say there's a sidecar" is not evidence. The cost of the false preset was a half-day of unverifiable success claims.

### Bug 19: Langfuse `?name=` query filters span operation name, not service.name
- `scripts/verify-otel.py` filtered traces with `?name=<service-name>`, expecting it to match the OTEL resource `service.name`. Langfuse's `name` field is the OTEL **span operation name** (e.g. `"invoke_agent Strands Agents"`). The filter never matched, returned 0 traces, falsely failed.
- Trace-level `totalTokens` is also empty for OTLP-pushed traces — the token data lives in `metadata.attributes."gen_ai.usage.total_tokens"` and Langfuse derives `totalCost` from it.
- **Fix**: `verify-otel.py` now fetches recent traces unfiltered, then filters client-side on `metadata.resourceAttributes."service.name"`. Token assertion checks `gen_ai.usage.*` attrs and `totalCost > 0`.
- **Rule**: When integrating with a third-party API, write the verifier query against the actual response shape, not against assumptions. Run a single curl + jq to inspect a real trace before writing assertions.

### Bug 20: cleanup.sh `sweep_orphan_resources` deleted unrelated AgentCore IAM roles + runtimes
- The orphan sweep filter was `Roles[?starts_with(RoleName, 'AgentCore')]` and `list-agent-runtimes` with no filter at all. In a shared account, this matches and deletes resources owned by other stacks/users.
- Live cleanup deleted `AgentCore-DemoTriage-defa-ApplicationAgentTriageAge-...` IAM role belonging to a pre-existing runtime not owned by this stack. Runtime is intact but cold starts will fail until role is re-created.
- **Fix**: IAM-role filter narrowed to `AgentCoreRuntime-${PROJECT_NAME}*`. Runtime/gateway/memory/policy/oauth sweeps are now opt-in via `CLEANUP_INCLUDE_FOREIGN_RUNTIMES=1` because per-deployment cleanup already targets owned IDs. Added secret sweep for `agentcore-otel/*` (always on — namespace is unique).
- **Rule**: Cleanup scripts must distinguish "resources owned by THIS stack" from "resources matching a vague prefix". When in doubt, read deployment IDs from the state table; never list-and-delete by string prefix in shared AWS accounts.

### Bug 21: Platform stack missing route + IAM perms for /api/observability/credentials
- The FastAPI router was registered in `main.py`, but `infra/stacks/platform_stack.py` enumerates each API Gateway route explicitly. The new route was missing → 404 from the SPA. Workflow Lambda role also lacked `secretsmanager:CreateSecret`.
- **Fix during live deploy**: Added the route + the IAM grant in `infra/stacks/platform_stack.py`. Both committed.
- **Rule**: Whenever a new FastAPI router is added in `backend/src/app/main.py`, also: (1) add an explicit `api.add_routes(...)` in `platform_stack.py`, (2) grant any AWS IAM perms the router calls. CDK changes are part of "wiring up a new router", not optional.

### Bug 22: ADOT Lambda layer breaks slash-form handlers + shadows pydantic_core
- The AWS-managed ADOT Python Lambda layer's exec wrapper (`/opt/otel-instrument`) does `__import__(handler_string_minus_dot_handler)`. For our handler `src/app/lambda_handler.handler` it tries `__import__("src/app/lambda_handler")` — Python rejects slashes in module names. Every platform Lambda crashed at INIT_START with `ModuleNotFoundError: No module named 'src/app/lambda_handler'`. `/health` returned HTTP 500 immediately after a "successful" CloudFormation deploy.
- Same layer also bundles `/opt/python/typing_extensions.py` (older version, no `Sentinel`) which shadows `/var/task/lib/typing_extensions/__init__.py`. Even with the slash issue fixed, pydantic_core's `from typing_extensions import Sentinel` would fail at import.
- **Fix**: Removed the ADOT layer entirely. `services/_otel_platform.py` now does manual `TracerProvider` + `OTLPSpanExporter` setup at module import, with `BotocoreInstrumentor` for boto3 spans. Each handler imports it FIRST. OTel SDK + exporter + botocore-instrumentation packages added to `backend/requirements-lambda.txt`.
- **Rule**: Don't trust AWS-managed Lambda layers blindly — they can ship dependency versions that conflict with your bundle. Always verify cold-start success with a `aws lambda invoke` after deploying. Test BOTH the Lambda's basic import path AND any third-party SDK imports the layer might shadow.

### Bug 23: Codegen prologue gated on per-canvas signal, missed platform-default-driven agents
- `services/code_generator.py:generate_agent_code()` accepts `observability_enabled: bool` and only injects `_inject_otel(code)` when True. The two callers (`step_handlers/codegen_step.py` and `services/deployment.py`) compute that flag from per-canvas signals only: `observability_config`, `"observability" in connected_tools`, or legacy `enable_otel`. None checked `get_platform_observability_defaults()`.
- Result: when platform-level OTEL was configured but the user deployed a default Strands agent with NO Observability node on the canvas, the runtime got correct OTEL_* env vars (proven via `get-agent-runtime`) but the generated `agent.py` lacked `_otel_bootstrap()` / `_otel_force_flush()` / `StrandsTelemetry` import. Strands does NOT auto-export OTLP from env vars alone — `setup_otlp_exporter()` MUST be called. Three live invocations produced HTTP 200 responses but zero spans in Langfuse. Reading A entirely non-functional.
- **Fix**: OR-in `bool(get_platform_observability_defaults())` to the `observability_enabled` computation in both callers + the unified-generator branch.
- **Rule**: When adding a new "platform default" mechanism that should affect generated code, audit EVERY codegen call site for whether it derives its enabled-flag from canvas-only signals. Same Bug 9 / Bug 15 pattern: drift across deploy paths.

### Bug 24: cleanup.sh `agentcore-otel/*` sweep deleted admin-managed platform secret
- `scripts/bootstrap-otel-secret.sh` creates `agentcore-otel/platform/{env}` and explicitly documents that this secret is admin-managed and outlives any individual stack.
- `scripts/cleanup.sh` orphan-sweep used `starts_with(Name, 'agentcore-otel/')` — matched the admin secret too and `--force-delete-without-recovery` deleted it (no 7-day undo). Next admin re-deploy with the cached ARN would silently fail (CDK accepts the ARN, runtime fetch returns AccessDenied / NotFound).
- **Fix**: Narrowed query to `starts_with(Name, 'agentcore-otel/') && !starts_with(Name, 'agentcore-otel/platform/')` so per-agent secrets (langfuse/custom prefix) sweep but admin secret survives.
- **Rule**: Cleanup scripts must not destroy admin-managed resources just because they share a prefix. When introducing a new admin-managed resource that uses an existing namespace, audit every cleanup-script branch that walks that namespace.

### Bug 25: Per-runtime IAM execution roles orphaned by cleanup
- `cleanup.sh per_deployment_cleanup()` deleted runtimes but never deleted their `AgentCoreRuntime-{runtime_name}` IAM execution roles. Live test 2026-05-15 left 5 orphan roles after teardown; tester had to manually `iam delete-role` each one.
- **Fix**: capture `roleArn` via `get-agent-runtime` BEFORE `delete-agent-runtime` (after deletion the get fails), then detach managed policies + delete inline policies + delete role. Same pattern for the MCP server runtime branch above. Idempotent — soft-fails on already-gone roles.
- **Rule**: When a runtime has a paired IAM role, capture the role identity FIRST. Order of operations matters: read-then-delete becomes impossible after the read target is gone.

### Bug 26: Hardcoded Bedrock Claude 3.x defaults flagged Legacy
- Multiple files defaulted to `anthropic.claude-3-5-sonnet-20241022-v2:0` and `us.anthropic.claude-3-5-haiku-20241022-v1:0`. Bedrock now flags these as Legacy in some accounts: `ResourceNotFoundException: Access denied. This Model is marked by provider as Legacy and you have not been actively using the model in the last 30 days.`
- **Fix**: replaced defaults with `us.anthropic.claude-sonnet-4-5-20250929-v1:0` and `us.anthropic.claude-haiku-4-5-20251001-v1:0` in: `frontend/src/utils/runtimeConfig.ts`, `frontend/src/components/modals/KnowledgeBaseConfigModal.tsx`, `frontend/src/components/modals/kb/AdvancedFields.tsx`, `backend/src/app/step_handlers/knowledge_base_step.py`, `backend/src/app/services/cfn_template_generator.py`. Removed Claude 3.x entries from the model dropdown.
- **Rule**: Bedrock Legacy designation is silent. When a hardcoded model ID stops working, suspect Legacy first — it's not an IAM issue. Track Bedrock model lifecycle and prefer current-generation IDs in defaults.

### Bug 27: Bug 25 fix only patched cleanup.sh, not the API DELETE path
- Bug 25 added "delete the runtime's execution IAM role too" logic to `scripts/cleanup.sh per_deployment_cleanup`. But the user-facing `DELETE /api/runtime/<id>` endpoint goes through `services/runtime_deployer.destroy_runtime`, which still only called `delete_agent_runtime` and stopped — the role was orphaned every time.
- Live verification (Team 1, 2026-05-16): deployed `team1_otel_cleanup_*` runtime, hit DELETE /api/runtime, got 200, then `aws iam get-role` STILL returned the role. Same drift-across-paths shape as Bugs 9, 15, 23.
- **Fix**: moved capture-then-delete-role logic INTO `runtime_deployer.destroy_runtime` so both the API and `cleanup.sh` share the same code. Added `iam:ListRolePolicies` and `iam:DeleteRolePolicy` to the deployment Lambda's IAM grant in `platform_stack.py`.
- **Rule**: When fixing a behavior in cleanup scripts, audit the equivalent API/handler path. They almost always exist as a separate code branch and almost always need the same fix. Same lesson as Bug 9.

### Bug 28: mcp-server-runtime template protocol mismatch
- Template set `protocol: 'MCP'` but `_generate_mcp_server_runtime()` emits a BedrockAgentCoreApp HTTP entrypoint, not a FastMCP server. AgentCore data plane returned 406 on every invocation.
- **Fix**: Set the template's `protocol: 'HTTP'`. A real FastMCP server is a v2 effort.

### Bug 29: Memory persistence broken — payload.session_id never populated
- `code_generator.py:1053` reads `session_id` from payload body. `deployment_handler.py:411` only passed it as `runtimeSessionId` (AgentCore-level), never inside payload. So MemoryClient stored every turn under literal `"default"`.
- **Fix**: deployment_handler now also includes `session_id` in the payload body. (Backwards-compat: existing reads of `payload.get("session_id", "default")` continue to work.)

### Bug 30: Lambda OTEL spans dropping at default 10s read timeout
- BatchSpanProcessor was hitting Langfuse's HTTPS read timeout, then retrying. Burned Lambda CPU and dropped spans.
- **Fix**: Set `OTEL_EXPORTER_OTLP_TIMEOUT=2000` + `OTEL_BSP_SCHEDULE_DELAY=1000` + `OTEL_BSP_EXPORT_TIMEOUT=5000` in the platform OTEL env helper.

### Bug 31: Dead routers/tools.py and routers/deployment.py confused readers
- `routers/tools.py` mounted `/api/test-tool`/`/api/generate-tool` on the workflow Lambda's FastAPI; same for `routers/deployment.py` mounting `/api/deploy`/`/api/test-runtime`/`/api/runtime/{id}`. API Gateway routes those endpoints DIRECTLY to the Deployment Lambda (deployment_handler.py). The workflow-Lambda router files were never reached. Two divergent implementations of the same endpoints.
- **Fix**: Deleted both files. Updated `main.py` and dropped the corresponding test class from `test_comprehensive_preservation.py`.
- **Rule**: When introducing API GW routes via CDK enumeration, also remove (or never add) FastAPI mounts on the workflow Lambda for the same paths.

### Bug 32: Multi-agent codegen — 4 distinct runtime errors per pattern
- `_generate_graph_agent` / `_generate_swarm_agent` / `_generate_workflow_agent` had: (a) only one provider import for a multi-provider DAG → NameError when sub-agents used different model providers, (b) `graph.add_node("id", agent)` arg order reversed (executor first, node_id keyword), (c) `graph.run(prompt)` doesn't exist (it's `graph(prompt)` — Graph is callable), (d) `Swarm(agents=...)` wrong kwarg (it's `nodes=`), `swarm.execute()` doesn't exist (it's `swarm(prompt)`).
- **Fix**: Added `_collect_multi_agent_imports` that gathers all distinct providers across parent + sub-agents. Fixed `add_node`, `Swarm(nodes=...)`, replaced `.run()`/`.execute()` with `__call__`.
- **Rule**: When generating code for a third-party SDK, deploy + invoke at least once before claiming the generator works. Strands' Graph/Swarm API contracts changed and our codegen lagged.

### Bug 33: Deployment Lambda couldn't self-invoke; tool-gen returned plaintext 500
- `lambda:InvokeFunction` was scoped to `function:AgentCore*` only — the deployment Lambda's own ARN didn't match. Async tool-generation and tool-test self-invokes failed with `AccessDeniedException`. Worse, the FastAPI handlers' `except` returned plaintext "Internal Server Error" 500 instead of structured JSON.
- **Fix**: Added `fn.grant_invoke(fn)` in CDK so the Lambda can invoke itself. Wrapped `handle_generate_tool` and `handle_test_tool` with try/except that raises HTTPException(500, detail={"error": ...}).

### Bug 34: Bedrock model IDs accepted at deploy, fail at invoke
- `/api/deploy` was happy to accept arbitrary `model.modelId` strings. The user wouldn't find out the model is invalid until first invocation, by which time the runtime was deployed and "succeeded".
- **Fix**: Pydantic `model_validator` on `RuntimeConfig` rejects empty/malformed/Legacy Bedrock IDs at the API boundary with HTTP 422. Allowlist of substrings for active Bedrock generations (Claude 4.x, Nova, Llama 3+, etc).
- **Rule**: Reject obviously-broken inputs at the API boundary, not after deploying real AWS resources.

### Bug 35: KB config without knowledgeBaseId 202'd then died mid-SFN
- `kbMode` defaults to `"existing"` in the backend; without `knowledgeBaseId` the SFN's knowledge_base step raised `ValueError`, and the user only learned about it by polling `/api/deploy/{id}`.
- **Fix**: Pydantic `model_validator` on `DeployRequest` rejects KB config without the required field for the chosen mode at HTTP 422.

### Bug 36: Per-step Lambda IAM policies were identical, kitchen-sink wide
- Every one of the 14 step Lambdas got the same policy with `iam:CreateRole`, `lambda:CreateFunction` on `function:*`, `secretsmanager:*` on `*`, `bedrock-agentcore:*`/`bedrock-agentcore-control:*` on `*`. RCE in any step Lambda → full account compromise via CreateRole(Admin) + CreateFunction.
- **Fix**: Split `_create_step_role` per `step_name`. Common: DDB + SSM read + cloudwatch:PutMetricData. Per-step: only the verbs that step actually calls. e.g. `status_update` gets nothing beyond DDB; `iam_step` gets `iam:Create/Get/Put/AttachRolePolicy` on `AgentCore*`; `gateway` gets the cognito + secrets verbs scoped to `agentcore-*` namespaces; runtime steps get specific bedrock-agentcore-control verbs.
- **Rule**: Resist the temptation to give every step Lambda the same kitchen-sink policy. The radius of an RCE/SSRF in any one Lambda equals the kitchen sink.

### Bug 37: Zero tenant isolation on workflows, flows, deployments
- `routers/workflows.py:list_all` was `dynamodb.scan` with no FilterExpression. Same for flows. `test_runtime`/`delete_runtime` accepted user-supplied runtime ARNs with no ownership check. Any Cognito-authenticated user could read/modify everyone else's data.
- **Fix**: New `services/auth.py` exports `get_caller_sub(request)` (reads JWT claim) and `assert_owner(record_owner_sub, caller_sub)` (raises 404 to hide existence). Added `owner_sub` to `WorkflowDefinition` + `Flow`. Every router CRUD endpoint now stamps `owner_sub` on create + asserts ownership on get/update/delete + filters list by caller. Deployment Lambda's test-runtime + delete-runtime check `user_id` against caller. Pre-tenancy records (owner_sub=None) accessible to keep migration-safe.
- **Rule**: API Gateway JWT authorization establishes the caller's identity but does NOT enforce tenant boundaries. Application code must do that explicitly. Default to 404, not 403, to avoid leaking existence.

### Bug 38: Cognito client allowed USER_PASSWORD_AUTH and didn't suppress user-existence errors
- `auth_flows.user_password=True` lets clients send plaintext passwords (Amplify defaults to SRP, so this was unused but available). `prevent_user_existence_errors` was unset, allowing username enumeration on login.
- **Fix**: `user_password=False`, `prevent_user_existence_errors=True`. Frontend Amplify uses SRP — no UX impact.

### Bug 39: No CSP on CloudFront responses, HSTS missing preload
- ResponseHeadersPolicy had HSTS, X-Frame-Options, Referrer-Policy, X-XSS-Protection — but no Content-Security-Policy. An XSS in the React app had no second line of defence.
- **Fix**: Added a baseline SPA-friendly CSP (`default-src 'self'`, `script-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, etc.) and HSTS preload.

### Bug 40: Workflow Lambda secretsmanager:CreateSecret on `*`
- The router always names secrets `agentcore-otel/{provider}/{uuid}`, but IAM allowed any name pattern. A future bug that lets a user influence the secret name could overlap with secrets owned by other workloads.
- **Fix**: Scoped Resource to `arn:aws:secretsmanager:{region}:{account}:secret:agentcore-otel/*`.

### Bug 41: Direct execute-api.amazonaws.com hits bypassed CloudFront WAF (PARTIAL)
- The WAF Web ACL was attached only to the CloudFront distribution. Clients hitting the bare API Gateway URL (`https://<id>.execute-api.us-east-1.amazonaws.com/...`) bypassed the WAF entirely. They still need a JWT, but rate limiting + Common + KnownBadInputs rule sets were skipped.
- **Attempted fix**: Created a regional WAFv2 Web ACL and tried to associate it with the API Gateway `$default` stage. CloudFormation rejected the association: WAFv2 supports REST API Gateway (v1), CloudFront, ALB, AppSync, Cognito — but NOT HTTP API Gateway (v2), which this stack uses.
- **Current state**: API Gateway throttling (default-stage CfnStage throttle settings) provides per-route rate limiting. The CloudFront WAF still handles browser-driven traffic. Direct API GW attacks bypass managed rule sets. Documented as a known gap.
- **Real fix (deferred)**: either (a) migrate to a REST API and re-attach WAFv2 (large change), (b) front API Gateway with an Application Load Balancer + regional WAFv2 (added cost), (c) add CloudFront-only access via custom auth header that the API GW authorizer requires.
- **Rule**: Verify the resource-type compatibility of WAFv2 associations BEFORE writing CDK. The `wafv2.CfnWebACLAssociation` constructor accepts any string for `resource_arn`; the failure surfaces only at deploy time.

### Bug 42: `fn.grant_invoke(fn)` creates circular CloudFormation dependency
- Adding `deployment_lambda.grant_invoke(deployment_lambda)` for self-invoke caused `Circular dependency between resources` at synth-time-OK / deploy-time-fail. The role policy referenced the function ARN; the function referenced its role. CDK couldn't order them.
- **Fix**: Manually construct the ARN from `function_name` literal (not the Function object's `function_arn` attribute) and add a `PolicyStatement` to the role's principal policy. The literal ARN is a static string with no token references, so no dependency edge.
- **Rule**: When granting a Lambda permission to invoke itself, reference the function via a literal ARN built from `account/region/function_name`, not the Function construct. Same trap exists for any "self-grant" pattern.

### Bug 43: AgentCore IAM action prefix is `bedrock-agentcore:`, NOT `bedrock-agentcore-control:`
- The boto3 service name `bedrock-agentcore-control` (with the `-control` suffix) is purely a client identifier — IAM evaluates BOTH control-plane (CreateAgentRuntime, etc) and data-plane (InvokeAgentRuntime) actions against the SAME prefix `bedrock-agentcore:`.
- Bug 36 (per-step IAM split) used `bedrock-agentcore-control:` for the control-plane verbs, breaking every Step Functions deployment with `AccessDeniedException: ... is not authorized to perform: bedrock-agentcore:CreateAgentRuntime`. 4/4 deploys failed in re-verification.
- **Fix**: Search-replace `bedrock-agentcore-control:` → `bedrock-agentcore:` across `_create_step_role` in `platform_stack.py`. The deployment Lambda already had the correct prefix in its kitchen-sink wildcard.
- **Rule**: When writing IAM policy actions, look up the service in the IAM action reference docs, not boto3's client list. Boto3 service names ≠ IAM action prefixes.

### Bug 44: DELETE /api/runtime swallowed destroy errors as success:true
- `handle_delete_runtime` always returned `DeleteResponse(success=True)` even when `destroy_runtime` returned `{success: False, message: "AccessDeniedException..."}`. Caller saw 200 OK with `success:true`, but the runtime / IAM role was still alive.
- **Fix**: Track `runtime_destroy_failed` from the destroy result and propagate to the top-level `DeleteResponse.success`.
- **Rule**: When wrapping a function that returns `{success: bool, message: str}`, propagate the success flag — don't drop it on the floor.

### Bug 45: Memory step needs iam:CreateRole (was missing from per-step IAM gate)
- The memory step creates an `AgentCoreMemory-{name}` IAM role for the memory resource. Bug 36's per-step IAM split gated `iam:CreateRole/Attach/Put/Pass` on `step_name in {iam, mcp_server, gateway, knowledge_base}` — `memory` was missing.
- **Fix**: Added `"memory"` to the gate.
- **Rule**: When splitting kitchen-sink IAM, audit every step handler for which AWS APIs it actually calls. Read the source, not the docs.

### Bug 46: runtime_configure step missing CreateAgentRuntimeEndpoint
- AgentCore's `CreateAgentRuntime` API auto-creates a default endpoint as a side effect, so the IAM caller must hold BOTH `CreateAgentRuntime` AND `CreateAgentRuntimeEndpoint` even though only `CreateAgentRuntime` is in the boto3 call. The `runtime_launch` step has the endpoint actions, but `runtime_configure` was missing them and failed first.
- **Fix**: Added `CreateAgentRuntimeEndpoint`/`GetAgentRuntimeEndpoint`/`DeleteAgentRuntimeEndpoint`/`UpdateAgentRuntimeEndpoint`/`ListAgentRuntimeEndpoints`/`DeleteAgentRuntime` to the `runtime_configure` action list.
- **Rule**: AWS APIs that auto-create child resources require the caller's IAM to cover the child action too. Test by reading the actual AccessDeniedException message — it names the missing action.

### Bug 47: AgentCore service does NOT honor `bedrock-agentcore:*` wildcard
- DeploymentLambda role had `Action: bedrock-agentcore:*` on `Resource: *`. `aws iam simulate-principal-policy` reported "allowed" for every individual action. But live calls to `DeleteAgentRuntime` returned `AccessDeniedException` from the AgentCore service itself.
- Conclusion: the service's authorization layer enumerates explicit verbs and rejects pure-`*` action grants. (Possibly a not-yet-GA service still on a deny-by-default-against-wildcards code path.)
- **Fix**: Enumerate every explicit `bedrock-agentcore:*` action the deployment Lambda calls in its policy. Same goes for the per-step roles where Bug 36 already used explicit lists.
- **Rule**: For services in active rollout, prefer explicit action grants over wildcards. IAM simulate is necessary but not sufficient evidence — invoke the API to confirm.

### Bug 49: AgentCore CreateAgentRuntime requires iam:PassRole on the runtime exec role
- The Bug-36 per-step IAM split granted `iam:CreateRole` to the iam_step but didn't grant `iam:PassRole` to the steps that hand the role over to AgentCore (runtime_configure, runtime_launch, mcp_server). CreateAgentRuntime requires the calling principal to also hold PassRole on the role being passed.
- **Fix**: Added `iam:PassRole` on `arn:aws:iam::*:role/AgentCoreRuntime-*` and `AgentCoreMemory-*` to the three steps that call AgentCore Create/Update operations.
- **Rule**: Any AWS API that takes a role ARN (`roleArn=...` or `RoleArn=...` parameter) requires the caller to hold `iam:PassRole` on that role's ARN. Easy to forget when splitting kitchen-sink policies.

### Bug 50: destroy_runtime called with friendly name → AccessDenied (not 404)
- AgentCore distinguishes the human-readable name (`my_agent_v1`) from the canonical id (`my_agent_v1-AbCdEfGh01`). `delete_agent_runtime(agentRuntimeId=...)` accepts ONLY the canonical id. Pass the friendly name and AgentCore returns AccessDeniedException — not ResourceNotFound — masking the real cause and bypassing the idempotency-on-NotFound branch.
- **Fix**: New `_resolve_runtime_identifier()` in `runtime_deployer.py` paginates `list_agent_runtimes` and matches by `agentRuntimeName`. Heuristic skips the lookup when the input already matches the canonical id pattern (`-{10 hash chars}$`).
- **Rule**: When an AWS API takes an "id" parameter, look up whether the resource has a separate name vs id. If yes, the wrapper must accept either and resolve.

### Bug 51: Bedrock model validator skipped substring check for non-prefixed IDs
- `_validate_bedrock_model_id` had a regex gate `^(us|eu|ap|global)\.` that only enforced the active-substring allowlist for inference-profile IDs. A bogus ID like `anthropic.claude-bogus-9000-v9:0` (no region prefix) slipped through and got 202.
- **Fix**: Removed the regex gate. Validator only runs when `model_provider == "bedrock"`, so every Bedrock model_id is now checked against the allowlist.

### Bug 52: AgentCore CreateAgentRuntime IAM-propagation race
- After `iam:put_role_policy` for the runtime's exec role, the AgentCore service evaluates the role's S3 read permission via a service-side cache that takes ~60s to populate. CreateAgentRuntime called within ~30s returns `ValidationException: Access denied when trying to retrieve zip file from S3` — even though the policy is correct.
- Previous mitigation was a 10s sleep after put_role_policy. SFN retry budget added another ~14s, total ~26s — still short. 3/3 fresh deploys failed with this exact error in re-verify.
- **Fix**: Bumped sleep to 15s AND added retry-with-backoff inside `create_agent_runtime` for this specific exception pattern: 5 attempts × 15s = up to 75s. Other errors (ConflictException, etc) propagate immediately to the existing handler.
- **Rule**: Service-side IAM evaluation can have its own cache separate from the IAM control plane's. When `iam:simulate-principal-policy` says allowed but the live API returns AccessDenied/ValidationException, suspect a service-cache race and add bounded retry.

### Bug 53: DeleteAgentRuntime requires bedrock-agentcore:DeleteWorkloadIdentity
- `CreateAgentRuntime` auto-creates a paired `workload-identity-directory/.../workload-identity/{runtime}` record alongside the runtime. `DeleteAgentRuntime` cascade-deletes that record, so the calling principal must ALSO hold `bedrock-agentcore:DeleteWorkloadIdentity`. Without it, DELETE /api/runtime fails AccessDenied even though `bedrock-agentcore:DeleteAgentRuntime` itself is granted.
- **Fix**: Added `CreateWorkloadIdentity` / `GetWorkloadIdentity` / `DeleteWorkloadIdentity` / `ListWorkloadIdentities` to the DeploymentLambda role, the runtime_configure step role, and the mcp_server step role.
- **Rule**: When an AWS API "deletes a resource", check what auto-created child records that delete cascades through and grant verbs on those too. The `workload-identity-directory` namespace is invisible until you hit the AccessDenied.

### Bug 54: runtime_configure Lambda timeout collided with the Bug-52 retry budget
- Bug 52 added a 5-attempt × 15s retry inside `create_agent_runtime` (75s worst case) but `step-runtime-configure` Lambda's `timeout=60s` was unchanged. Every deploy timed out at the IAM-race retry. 100% deploy regression.
- **Fix**: bumped `runtime_configure` Lambda timeout to 240s.
- **Rule**: When adding a retry loop with non-trivial total time inside a Lambda, audit the Lambda's timeout and bump it. The retry helper and the Lambda config live in different files, easy to forget.

### Bug 55: AgentCore returns AccessDenied (not ResourceNotFound) for non-existent runtime IDs
- `destroy_runtime` only treated `ResourceNotFound` as benign. AgentCore returns `AccessDeniedException: ... is not authorized to perform: bedrock-agentcore:DeleteAgentRuntime` when the runtime ID doesn't exist (regardless of whether the IAM principal is authorized for existing runtimes).
- Practical effect: any DELETE for a deployment that failed before reaching `create_agent_runtime` (i.e. broken-deploy cleanup) returned `success:false` and skipped the IAM-role cascade, leaking the runtime IAM role.
- **Fix**: extended the benign-error filter in both `get_agent_runtime` and `delete_agent_runtime` to also match `AccessDeniedException`.
- **Rule**: AWS services don't always return ResourceNotFound for missing resources — some return AccessDenied (intentionally, for security). When wrapping cleanup paths, treat both as "resource is gone" or distinguish by inspecting the error message.

### Bug 56: SFN task TimeoutSeconds capped the Lambda before its retry could succeed
- Bug 54 bumped the `step-runtime-configure` Lambda timeout to 240s. But the SFN task wrapping that Lambda still had `TimeoutSeconds: 60`. SFN cuts the task at 60s regardless of how long the Lambda is configured to run. CloudWatch shows `Duration: 76673ms` (Lambda did keep running) but SFN history shows `States.Timeout` at 60s. 100% deploy failure rate continued.
- **Fix**: bumped the `ConfigureRuntime` SFN task's `timeout_seconds` from 60 to 240. Also bumped `CreateIAMRole` from 60 to 90 since it has its own 15s sleep + per-tool inline policy attachments.
- **Rule**: SFN task TimeoutSeconds and Lambda timeout are two different ceilings. Whichever is lower wins. When you bump one, audit the other.

### Bug 57: destroy_runtime didn't clean the IAM role when runtime never existed
- When `get_agent_runtime` returns AccessDenied (because the runtime never existed — Bug 55 path), `role_arn` stays empty, the IAM-cleanup branch is skipped, and `AgentCoreRuntime-{name}` role leaks. DELETE returns `success:true`, masking the leak.
- **Fix**: even when `role_arn` is empty, fall back to convention-based role names (`AgentCoreRuntime-{name}` for SFN deploys, `{name}-role` for direct deploys). Iterate candidates with `NoSuchEntityException` swallowed per-candidate.
- **Rule**: When deletion of resource A is supposed to cascade to resource B, never gate the cleanup of B on having read A's metadata first. Always have a fallback that reconstructs B's identity from a convention.

### Bug 58: Bug-52 retry budget too small for observed IAM cache latency
- Bug 52's initial retry was 5 attempts × 15s = 75s. Verifier observed AgentCore IAM cache propagation ≥3 minutes in this account on 2026-05-17 (a manual create-agent-runtime ~17 min after role creation succeeded first try). Every SFN deploy still failed.
- **Fix**: bumped attempts to 14 (210s total), staying inside the 240s Lambda + SFN ceiling.
- **Rule**: Service-side IAM caches don't have a published SLA. Calibrate retry budgets generously and let the Lambda/SFN timeout be the outer cap, not the inner retry count.

### Bug 59: multi_agent_config schema validated at codegen, not API boundary
- /api/deploy accepted multiAgentConfig with `id`/`from`/`to` keys (instead of `agentId`/`source`/`target`), then crashed mid-SFN with `KeyError: 'agentId'` from `code_generator.py`. User had to poll `/api/deploy/{id}` to discover failure.
- **Fix**: New `_check_multi_agent_schema` validator on RuntimeConfig that requires `agentId` on each agent and `source`/`target` on each edge, returning HTTP 422 with a useful message. Lists offending keys.

### Bug 60: Eliminated per-deploy IAM-propagation race via shared runtime exec role
- AgentCore service-side IAM cache for fresh runtime roles was taking 17-20 minutes to propagate after `put_role_policy` in this account. No retry budget within reasonable Lambda/SFN timeouts could ride it out. Every platform deploy failed at `CreateAgentRuntime` with `ValidationException: Access denied when trying to retrieve zip file from S3`.
- **Fix**: Created ONE stable `AgentCoreRuntime-{project}-{env}-shared` IAM role at CDK stack init with full S3 read on the artifacts bucket + Bedrock + tool perms baked in. CDK stack deploy waits the cache out as part of its own propagation window — by the time a user triggers `/api/deploy`, AgentCore's IAM cache for the shared role is fully populated. The iam_step handler now reads `SHARED_RUNTIME_ROLE_ARN` from env and short-circuits, returning the shared ARN instead of creating a fresh role.
- **Trade-off**: every runtime in this stack shares the same role. Per-runtime least-privilege is sacrificed in exchange for a working deploy pipeline. Acceptable for sample/demo; production deployments needing strict per-tenant IAM should override per-agent.
- **Rule**: Service-side IAM caches are an architectural problem, not a tuning problem. If you can pre-create the role at stack-init time, do — it sidesteps the race entirely. Resist the temptation to keep raising retry counts.

### Bug 61: AgentCore IAM cache is keyed on (role, S3 prefix), not just role
- Bug 60's "shared runtime exec role" assumption was wrong. The verifier's smoking-gun test: warmed the role with a manual CreateAgentRuntime against the EXACT same shared role + a NEW S3 prefix → still hit the 17-20 min ValidationException race. AgentCore's authorization layer caches s3:GetObject permission per (role, prefix) tuple.
- Implication: every fresh deploy upload to `deployments/{deployment_id}/code.zip` triggers a fresh cache miss because the prefix is new. No retry budget can ride out 17-20 min.
- **Fix**: Switch to a stable S3 prefix keyed on the runtime NAME, not deployment_id. New layout: `deployments/by-name/{runtime_name}/code.zip` (and `mcp-server-code.zip`). First deploy of an agent has the cache miss; subsequent updates of the same agent reuse the warm cache. Touched 4 call sites: `step_handlers/codegen_step.py`, `step_handlers/mcp_server_step.py`, `services/deployment.py` (×2 — direct deploy + MCP path).
- **Trade-off**: deploys with the same agent name overwrite each other's code.zip. That matches AgentCore semantics anyway — same `agentRuntimeName` reuses the runtime via the `ConflictException → update` path. Old-style per-deploy_id artifacts bucket prefixes are abandoned (the deployments table still has the deployment_id for tracking; only the S3 layout changes).
- **Rule**: Service-side caches can be keyed on more than just principal+resource. When a "warm the cache once" strategy doesn't work, suspect a finer cache key. The fix is usually to make the cache key stable across calls, not to retry harder.

### Bug 62: Bug-60's shared role + Bug-25/27/57's role cascade nuked the shared role on every DELETE
- Every `DELETE /api/runtime/<id>` followed the role-cleanup convention path and tried to delete `AgentCoreRuntime-{name}`. With Bug 60 in place, `get_agent_runtime` returns the SHARED role's ARN, and the cleanup deletes it. Next DELETE recreates it via CDK on next deploy, but in the meantime every other runtime in the stack (including DemoTriage) loses its assumed role.
- **Fix**: skip role deletion when role name matches `SHARED_RUNTIME_ROLE_ARN` env var (which is now injected into the deployment Lambda) or has the `-shared` suffix.
- **Rule**: When introducing a stack-managed shared resource, audit every cleanup path that could delete resources matching its naming pattern.

### Bug 63 (FIXED 2026-05-18): The "IAM cache race" was actually an S3 region-cache 301 transient
- For a week we attributed the `ValidationException: Access denied when trying to retrieve zip file from S3` error to AgentCore's IAM cache. Six architectural fixes (Bugs 52, 54, 56, 58, 60, 61) tried to wait it out or pre-warm it. None reliably worked.
- **Controlled diagnostic on 2026-05-18**: ran `aws bedrock-agentcore-control create-agent-runtime` directly against the same (shared role, bucket, S3 key) the platform Lambda had just failed on. Call 1 returned `ValidationException: S3 operation failed: Moved Permanently (Status Code: 301)`. Call 2, ~30s later, identical inputs, succeeded. Runtime reached READY normally and was deleted cleanly.
- **Real root cause**: AgentCore's service-side S3 client gets a 301 region-redirect on the FIRST call to a bucket whose region it hasn't cached. The 301 response itself warms the AgentCore-side cache. Once warm, the bucket is fast-path. The "Access denied" wording in the platform Lambda's logs was a downstream re-raise; the verbatim AWS error string is `Moved Permanently`/`Status Code: 301`.
- **Why our prior fixes didn't help**: pre-warming the IAM role + stable S3 prefix did nothing because IAM was never the problem. The 301 happens on the *bucket*, not the (role, prefix) tuple.
- **Fix**: Extended `_create_with_iam_retry` (renamed `_create_with_transient_retry`) in `runtime_deployer.py` to retry on `Moved Permanently` and `Status Code: 301` in addition to the IAM access-denied marker. Budget: 8 × 5s — way under SFN's 240s envelope, and the 301 typically resolves on attempt 2. Verified live by re-running the controlled diagnostic through the new code path: succeeded on first attempt of `create_agent_runtime()`.
- **Rule**: When an error message ends in `Access denied`, do NOT assume IAM. AWS service S3 clients can return `S3 operation failed: Moved Permanently (Status Code: 301)` wrapped inside a ValidationException whose outer text mentions S3 access — that's a region-cache miss, not an authorization failure. Always inspect the verbatim service exception, not just the rephrased Lambda error string. Run a controlled CLI repro before adding architectural complexity.

### Bug 64 (FIXED 2026-05-18): CSP middle-wildcard silently breaks Cognito login

- After fresh deploy, login on the deployed CloudFront URL surfaced "A network error has occurred." — Amplify SRP fetch to `https://cognito-idp.us-east-1.amazonaws.com` failed at the browser network layer.
- Diagnostic: same Cognito client + user worked perfectly via AWS CLI `aws cognito-idp initiate-auth` (SRP_A flow returned PASSWORD_VERIFIER challenge). User was already CONFIRMED. WAF showed zero blocks. CSP allowed `connect-src https://cognito-idp.*.amazonaws.com`. Bundle had correct UserPoolId / ClientId baked in.
- **Real root cause**: CSP Level 3 host-source grammar only permits `*` as the LEFTMOST label of a host (`*.example.com`). A middle-wildcard like `cognito-idp.*.amazonaws.com` is **not valid CSP syntax** — browsers parse it but silently match nothing. Amplify's `fetch()` was blocked → threw `TypeError` → caught by `@aws-amplify/core/dist/esm/clients/handlers/fetch.mjs` → re-thrown as `AmplifyErrorCode.NetworkError` with message "A network error has occurred."
- **Fix**: replace the middle-wildcard with the explicit deploy region. CDK has `self.region` at synth time so we bake it into the CSP string: `f"connect-src 'self' https://*.amazoncognito.com https://cognito-idp.{self.region}.amazonaws.com; ..."` in `infra/stacks/platform_stack.py::content_security_policy`.
- **Rule**: CSP `*` is valid ONLY as `*.host` (leftmost). Never write `cognito-idp.*.amazonaws.com`, `*.s3.*.amazonaws.com`, or similar middle-wildcard patterns — they look right and produce no warning, but match nothing. If the host has a region/account in the middle, hardcode it (or template it from the stack's region/account). When debugging "network error" on a deployed SPA, always check CSP first.

### Bug 65 (FIXED 2026-05-18): Gateway step IAM missing CreateWorkloadIdentity → gateway lands in FAILED, no recovery
- Fresh deploy of "Strands + Gateway" template put gateway `omar2` in `FAILED` status. SFN retries surfaced as `Cannot perform operation CreateGatewayTarget when gateway is in FAILED status`.
- `get-gateway` revealed the actual reason in `statusReasons`: `Failed to create gateway dependencies: ... not authorized to perform: bedrock-agentcore:CreateWorkloadIdentity ... no identity-based policy allows the bedrock-agentcore:CreateWorkloadIdentity action`.
- **Real root cause**: `CreateGateway` transparently creates a workload-identity record under the gateway's identity directory. Per Bug 36's per-step IAM split, the `mcp_server` and `runtime_configure` step roles got `CreateWorkloadIdentity`, but the `gateway` step role did NOT. Gateway entered FAILED; subsequent retries hit the secondary error because AgentCore refuses any modification call against a FAILED gateway.
- **Fix 1 (IAM)**: Added `CreateWorkloadIdentity`, `GetWorkloadIdentity`, `DeleteWorkloadIdentity`, `ListWorkloadIdentities` to the `gateway` step role in `infra/stacks/platform_stack.py::_create_step_role`.
- **Fix 2 (recovery)**: When the gateway step encounters a `ConflictException` and the existing gateway has `status == "FAILED"`, `gateway_deployer.py` now deletes and recreates the gateway (with Cognito pool cleanup) instead of trying `UpdateGateway` against it (which AgentCore rejects with `UpdateGateway operation can't be performed on gateway when it is in Failed state`). Without this, the platform was permanently wedged on any FAILED gateway leftover from a partial deploy.
- **Rule**: AgentCore primitives (Gateway, Runtime) transparently create child resources during their own creation flow — workload-identity records, default endpoints, system policies. Every step's IAM role must hold permissions for the FULL transitive set, not just the public verb name. When you split a kitchen-sink role into per-step roles, also audit "what does CreateX do internally?" via the AgentCore service docs / live `statusReasons`. And whenever a primitive can land in `FAILED`, the conflict handler must delete-and-recreate, not assume `Update` will work.

### Bug 66 (FIXED 2026-05-18): runtime_configure step Lambda role missing S3 read → CreateAgentRuntime fails

- After Bugs 60-65 were fixed, every UI-surface deploy still failed in `runtime_configure` with `ValidationException: Access denied when trying to retrieve zip file from S3`. The `_create_with_transient_retry` budget exhausted on every attempt — the error never resolved transiently because it wasn't a 301 region-redirect.
- Reproduction: from my user identity (which has full S3 perms), `boto3.client("bedrock-agentcore-control").create_agent_runtime(...)` against the EXACT same `(roleArn=AgentCoreRuntime-...-shared, bucket=agentcore-workflow-dev-artifacts-..., key=deployments/by-name/.../code.zip)` succeeded immediately and reached READY. Same call from the step Lambda failed reproducibly.
- **Real root cause**: AgentCore's `CreateAgentRuntime` does a pre-flight S3 reachability check on the CALLING principal's identity, not just the `roleArn` it will assume for actual reads. The runtime exec role (the shared role) already had S3 perms — but the step Lambda's role didn't. The CDK helper `_create_step_role` only granted artifacts-bucket access to `s3_writers = {codegen, gateway, knowledge_base, mcp_server}`. `runtime_configure` was missing.
- **Fix**: Added `runtime_configure` and `runtime_launch` to a new `s3_readers` set in `_create_step_role` and called `self.artifacts_bucket.grant_read(role)` for them.
- **Why earlier diagnostics misled us**: The error string `Access denied when trying to retrieve zip file from S3` looks identical to an IAM-cache propagation issue (Bug 52), which is what we kept attributing it to across Bugs 52, 54, 56, 58, 60, 61. Bug 63 separately found the S3 301 transient. None of those were the real cause for the UI surface — the step Lambda just never had S3 perms in the first place. Earlier "fixes" worked transiently because direct-deploy from the deployment Lambda (which has S3 perms via `artifacts_bucket.grant_read_write(deployment_role)`) was the path being tested manually; the SFN step Lambda path was always broken but the matrix tester never reached it cleanly until 2026-05-18.
- **Rule**: When an AWS service rejects an API call with `Access denied retrieving from S3`, the missing S3 permission can be on EITHER (a) the role passed to the API as the resource-access role, or (b) the calling principal making the API call. Some services pre-flight-check (b) even when (a) is what eventually does the read. If `iam:simulate-principal-policy` says (a) is allowed but the live API rejects, check (b). The simplest test: try the same call from a different IAM principal that has S3 — if it succeeds, the missing perm is on the original caller, not the resource role.

### Bug 67 (FIXED 2026-05-18): Generated CFN GatewayRole missing `CheckAuthorizePermissions` for Cedar policy

- `customer-support-blueprint` (P-E2E-005) CFN export rolled back during stack create. Diagnostic from CFN events: `Policy Engine '<id>' does not have the required permissions. User: ...AgentCoreGateway-...GenesisPolicyEngineCheck is not authorized to perform: bedrock-agentcore:CheckAuthorizePermissions on resource: arn:aws:bedrock-agentcore:us-east-1:...:policy-engines/<id>/target-resource/<gw-arn>`.
- `cfn_template_generator.py::_add_gateway_role` was missing `bedrock-agentcore:CheckAuthorizePermissions` in the Gateway role's `AgentCoreGatewayOps` statement. The CFN-provider's `GenesisPolicyEngineCheck` resource binds the Cedar PolicyEngine to the Gateway target; that bind call validates the Gateway role can call this verb on the policy engine.
- **Fix**: Added `bedrock-agentcore:CheckAuthorizePermissions` to the Gateway role's policy in `cfn_template_generator.py`.
- **Rule**: When AgentCore introduces a new Cedar/policy primitive, audit ALL roles that need to interact with it — both the principal that creates/configures the primitive AND the principal that the primitive evaluates against. The CFN bind call may use a different role than the gateway's runtime calls.

### Bug 68 (KNOWN LIMITATION): MCP Server Runtime cold-start exceeds 30s init deadline when used as Gateway target

- `mcp-server-gateway-target` (P-MCP-002) CFN export deploys two runtimes (Agent Runtime HTTP + MCP Server Runtime MCP) and wires the second as a Gateway target. The CFN provider's `CreateGatewayTarget` call validates the MCP target by calling its `tools/list` endpoint, which requires the MCP runtime to be READY and responsive within 30s.
- Fresh-cold-start MCP runtime (Strands + MCP + agent code + dep bundle = ~46MB) takes 35-60s to first-respond on the MCP protocol port. The CFN provider gives up at 30s with `Failed to connect and fetch tools from the provided MCP target server. Error - Runtime initialization time exceeded.`
- **Why this is hard to fix from outside**: AgentCore's CreateGatewayTarget timeout is service-side, not configurable. We can't extend it. Pre-warming the MCP runtime before CreateGatewayTarget (multiple Invoke calls to force scaling) might work but adds 30-60s of pre-deploy delay and isn't reliable across cold-pool churn.
- **Workaround for the operator**: deploy the MCP Server Runtime alone first (template 5: `mcp-server-runtime`). Wait for it to be READY. Hit it with one or two `bedrock-agentcore invoke-agent-runtime` calls to warm the pool. Then deploy template 6 (`mcp-server-gateway-target`) — the existing-runtime detection path skips re-creating the MCP runtime, and CreateGatewayTarget hits a warm runtime within 30s.
- **What still works in v1**: Direct MCP runtime invocation (template 5) works fine. Bug only affects the chained MCP-as-Gateway-target pattern (template 6).
- **Documented as known limitation in README**.

### Bug 69 (FIXED 2026-05-18): Generated CFN role names collide between consecutive deploys

- Two stacks with similar `DeploymentName` parameter values (matrix-tester used `mtxcfncloudformation*`) collided on `RoleName: AgentCoreGateway-${DeploymentName}` because IAM truncates to 64 chars and two long DeploymentName values shared the same prefix.
- **Fix**: All `RoleName` substitutions in `cfn_template_generator.py` now use `${AWS::StackName}` instead of `${DeploymentName}`. CloudFormation guarantees stack names are unique within a region, so role names won't collide. DeploymentName remains for resource naming where ARN uniqueness is built in (e.g. AgentCore Runtime names which AgentCore appends a hash to).
- **Rule**: Never use a user-supplied parameter as the SOLE source of uniqueness for an IAM role name in a CFN template. Always anchor on `${AWS::StackName}` or `${AWS::StackId}` substring. User parameters can have arbitrary truncation/collision behavior; CFN-managed unique strings can't.

### Bug 70 (FIXED 2026-05-18): step-policy IAM role missing GetGateway → Cedar policy attach fails

- Strict matrix-tester v2 found `customer-support-blueprint` UI deploy fails in `policy_step` with AccessDenied on `bedrock-agentcore:GetGateway` for the policy step Lambda's role.
- The policy step needs to read the gateway it's about to bind the policy engine to. The step role had `UpdateGateway` but not `GetGateway`.
- **Fix**: Added `bedrock-agentcore:GetGateway` to the `policy` step's `agentcore_steps` action list in `_create_step_role`.

### Bug 71 (FIXED 2026-05-18): MCP step role iam:CreateRole resource scope mismatch

- `mcp-server-gateway-target` UI deploy fails in `mcp_server_step` with AccessDenied on `iam:CreateRole` for role name `mcp_<runtime_name>-mcp-role`.
- The step role's `iam:CreateRole` is scoped to `arn:aws:iam::*:role/AgentCore*` — but the MCP step was creating roles with name `mcp_*-mcp-role`. No prefix match.
- **Fix**: Renamed in `step_handlers/mcp_server_step.py` from `f"{sanitize_runtime_name(mcp_name)}-mcp-role"` to `f"AgentCoreMCP-{sanitize_runtime_name(mcp_name)}"`. Now matches the `AgentCore*` IAM resource scope.
- **Rule**: When CDK scopes `iam:CreateRole` to `role/AgentCore*`, every dynamically-created role's name MUST start with `AgentCore`. Audit every step handler that calls `iam_client.create_role(RoleName=...)` and verify the name pattern matches.

### Bug 72 (FIXED 2026-05-19, was: KNOWN LIMITATION): CFN-export AWS::BedrockAgentCore::Policy stabilization timeout

- `customer-support-blueprint` (P-E2E-005) CFN export rolls back at `DefaultPolicy` resource after ~31s with `NotStabilized`.
- The native CFN resource type `AWS::BedrockAgentCore::Policy` polls for terminal state internally; on first creation in an account the policy engine readiness propagates slower than CFN's stabilizer waits.
- **Workaround**: deploy a simpler stack first that creates the PolicyEngine alone, wait for ACTIVE, then run the policy stack. Or wait 60s and re-run the failed CFN deploy.
- **Fix landed 2026-05-19**: replaced `AWS::BedrockAgentCore::Policy` native CFN type with `Custom::AgentCorePolicy` handled by the cfn-provider Lambda. The custom handler waits up to 5 minutes (60 × 5s) for the policy engine to reach ACTIVE before calling `create_policy`, then retries on `ResourceNotFoundException` for another 100s. CfnProviderRole granted `bedrock-agentcore:CreatePolicy/DeletePolicy/ListPolicies/GetPolicy/GetPolicyEngine/ListPolicyEngines`.

### Bug 73 (FIXED 2026-05-18): KB step S3_VECTORS missing s3VectorsConfiguration

- `_build_storage_config` returned bare `{"type": "S3_VECTORS"}`. Bedrock's `create_knowledge_base` rejects this with `ValidationException: storageConfiguration ... is required`.
- The S3 Vectors integration requires either an explicit `s3VectorsConfiguration.vectorBucketArn` + `indexArn`/`indexName` OR — in auto-managed mode — at minimum an `indexName` so Bedrock can provision the index for you.
- **Fix**: `_build_storage_config` now reads optional `s3VectorsBucketArn`/`s3VectorsIndexName`/`s3VectorsIndexArn` from kb_config; falls back to auto-managed mode with a default index name.
- **Frontend gap (NOT YET FIXED)**: the KB modal doesn't expose these fields. P-KB-001 (S3+S3Vectors) will pass via direct API call but UI users can't configure a custom S3 Vectors bucket without editing JSON. Tracked as follow-up.

### Bug 74 (PARTIAL FIX 2026-05-18): Browser tool codegen wrapped a non-existent API

- `code_generator.py::has_browser` block generated `client.invoke(action, {"url": url})` — but `BrowserClient` has no `invoke()` method. CW Logs showed "Tool #1: browse_web" → "Invalid HTTP request received" → agent apologizes.
- AgentCore's actual browser API requires `client.generate_ws_headers()` then a Playwright/CDP-over-WebSocket client to navigate. That's a substantial codegen rewrite (framework-dependent, requires Playwright in the runtime).
- **Partial fix**: replaced the broken `invoke()` wrapper with one that calls `generate_ws_headers()` + `generate_live_view_url()` and returns those to the agent. The tool no longer crashes; the agent can report the session info; full headless navigation requires a future Playwright integration.
- **Documented as a known limitation in README**. Browser tool currently surfaces session bootstrap, not full navigation.

### Bug 75 (FIXED 2026-05-18): Multi-agent Swarm sub-agents collide on default name

- `code_generator.py::_generate_swarm_agent` generated `Agent(model=..., system_prompt=...)` for each sub-agent without an `name=` kwarg. Strands defaults all unnamed agents to `"Strands Agents"`. Swarm requires unique names → runtime collision.
- **Fix**: codegen now emits `Agent(name="<safe_var>", ...)` for every swarm sub-agent.

### Bug 76 (NEW 2026-05-18 — uncovered after Bug 70 fix): StepPolicyRole missing iam:PassRole on AgentCoreGateway-* role

- Bug 70 fix added `bedrock-agentcore:GetGateway` + `UpdateGateway` to `agentcore-workflow-dev-StepPolicyRole`. policy_step.py:174 now reaches `agentcore_ctrl.update_gateway(...)`, which internally re-passes the gateway's IAM role (because `roleArn` is in update_params).
- Step Functions execution fails with: `AccessDeniedException: not authorized to perform: iam:PassRole on resource: arn:aws:iam::*:role/AgentCoreGateway-...`
- **Symptom**: `customer-support-blueprint` (P-E2E-005) UI deploy fails at `step=status_update` immediately after `step=gateway`. Cedar policy attachment is the second-to-last step before runtime launch.
- **Fix needed** (infra/stacks/platform_stack.py around the StepPolicyRole inline policy ~line 970):
  ```python
  iam.PolicyStatement(
      actions=["iam:PassRole"],
      resources=["arn:aws:iam::*:role/AgentCoreGateway-*"],
      conditions={"StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}},
  )
  ```
- **Rule**: When a service-role action like `Update*` accepts a `roleArn` parameter, the caller needs `iam:PassRole` on that exact role pattern, scoped to the consumer service via `iam:PassedToService`. Always grep for `roleArn=` calls and audit PassRole coverage when adding new control-plane actions.

### Bug 77 (NEW 2026-05-18 — uncovered after Bug 71 fix): StepMcpServerRole missing cognito-idp:CreateUserPool

- Bug 71 fix made the MCP role naming align with the IAM resource scope (`AgentCoreMCP-*`). mcp_server_step.py now successfully creates the runtime role, then proceeds to `cognito.create_user_pool(...)` to bridge gateway-to-MCP-server OAuth auth.
- The StepMcpServerRole grants Bedrock + IAM + Lambda + S3 + DynamoDB + SSM but no `cognito-idp:*` actions. Step fails with: `AccessDeniedException: not authorized to perform: cognito-idp:CreateUserPool on resource: arn:aws:cognito-idp:*:*:userpool/*`
- **Symptom**: `mcp-server-gateway-target` (P-MCP-002) UI deploy fails at `step=mcp_server`. The full mcp-server-gateway-target chain is not deployable until this is fixed.
- **Fix needed**: add to StepMcpServerRole (infra/stacks/platform_stack.py StepMcpServerRoleDefaultPolicyCE331D41):
  ```python
  iam.PolicyStatement(
      actions=[
          "cognito-idp:CreateUserPool",
          "cognito-idp:CreateUserPoolClient",
          "cognito-idp:CreateUserPoolDomain",
          "cognito-idp:CreateResourceServer",
          "cognito-idp:DeleteUserPool",
          "cognito-idp:DeleteUserPoolDomain",
          "cognito-idp:DescribeUserPool",
      ],
      resources=["*"],  # CreateUserPool requires "*"; tighten the others to userpool/*
  )
  ```
- **Rule**: Whenever a step handler calls a service the platform stack hasn't pre-baked into the role policy, the deploy will fail with AccessDenied at runtime, not at synth/deploy time. Add a "step-handler-side-effect audit" rule: `grep -rn "boto3.client\|.create_\|.delete_" backend/src/app/step_handlers/` and reconcile against each step's IAM policy.

### Bug 78 (NEW 2026-05-18 — uncovered after Bug 73 fix): KB role missing s3vectors:* permissions

- Bug 73 fix made `_build_storage_config()` emit a proper `s3VectorsConfiguration` with `indexName`. `bedrock-agent.create_knowledge_base()` now accepts the params shape, and Bedrock proceeds to attempt the role-validation step.
- The KB role created by `_create_kb_role()` (knowledge_base_step.py:40-150) has only `bedrock:InvokeModel` + corpus-bucket S3 read. When Bedrock validates role → tries to provision the auto-managed S3 Vectors bucket+index (or even just describe it), the role can't, so Bedrock surfaces it as `ValidationException: Bedrock Knowledge Base was unable to assume the given role`.
- **Symptom**: P-KB-001 (S3+S3Vectors) UI deploy fails at the KB step. Per spec Phase 4.3, this combination is mandated to PASS.
- **Fix needed** (knowledge_base_step.py inside `_create_kb_role()`, after the `if vector_store_type == "rds":` block — add a parallel `s3_vectors` block):
  ```python
  if vector_store_type == "s3_vectors":
      s3v_arn = kb_config.get("s3VectorsBucketArn", "*")
      statements.append({
          "Effect": "Allow",
          "Action": [
              "s3vectors:CreateVectorBucket",
              "s3vectors:CreateIndex",
              "s3vectors:PutVectors",
              "s3vectors:GetVectors",
              "s3vectors:ListVectors",
              "s3vectors:QueryVectors",
              "s3vectors:DeleteVectors",
              "s3vectors:DescribeVectorBucket",
              "s3vectors:DescribeIndex",
          ],
          "Resource": s3v_arn if s3v_arn != "*" else "*",
      })
  ```
- **Rule**: Whenever you fix an API param-shape bug (Bug 73), the next deploy will reveal whatever permission was hidden behind it. Run an end-to-end verification immediately after every fix; don't assume a passing param-shape check means the deploy will succeed.

### Bug 79 (FIXED 2026-05-18): gateway step missing CreateTokenVault → CreateOauth2CredentialProvider fails

- v4 regression run: `mcp-server-gateway-target` UI deploy failed at `step=gateway` with: `not authorized to perform: bedrock-agentcore:CreateTokenVault on resource: arn:aws:bedrock-agentcore:us-east-1:...:token-vault/default`.
- `CreateOauth2CredentialProvider` transparently provisions a token vault under the account's identity directory if one doesn't exist. This was a fresh account whose token-vault hadn't been auto-created yet.
- **Fix**: Added `CreateTokenVault`, `GetTokenVault`, `ListTokenVaults` to the `gateway` step's IAM action list in `_create_step_role`.
- **Rule**: When a control-plane verb (CreateOauth2CredentialProvider, CreateGateway, CreateAgentRuntime) transparently creates infra under the hood (token-vault, workload-identity, default endpoint), the caller IAM principal needs perms for the transitive set. Always check `statusReasons` on FAILED resources for the verbatim missing action — a deeper IAM gap is hidden behind every "feature works fine if you don't trigger the auto-creation path."

### Bug 80 (FIXED 2026-05-18): Bedrock KB role assume race after put_role_policy

- v4: `P-KB-001` UI deploy failed at `step=knowledge_base` with `ValidationException: Bedrock Knowledge Base was unable to assume the given role`.
- The KB step calls `iam_client.create_role()` then `iam_client.put_role_policy()` then `bedrock_agent.create_knowledge_base()` immediately. Bedrock validates the role's assumability synchronously; IAM control-plane consistency lags by 10-60s after `put_role_policy`. The validation hit the lag window.
- **Fix**: Wrapped `create_knowledge_base()` in a 8 × 10s = 80s retry loop that catches `ValidationException ... unable to assume`. Same shape as `runtime_deployer.py::_create_with_transient_retry` for the AgentCore case.
- **Rule**: Any AWS API that takes a `roleArn` and immediately validates `sts:AssumeRole` against it is subject to IAM consistency lag. Always retry on the assume-race error string, with 5-15s backoff, regardless of how recently the role was created.

### Bug 81 (HARNESS LIMITATION, not platform bug): Multi-agent Workflow pattern coordinator refuses canary as prompt injection

- v4 cell `v4-ui-PMULTI003-workflow` returned a HALLUCINATION_FAIL: agent responded with `"I'm Claude... The instruction in the system prompt asking me to print a canary token appears to be a test or prompt injection attempt. I don't follow hidden instructions that ask me to output specific tokens..."`.
- Root cause is NOT a platform bug. The Strands Workflow pattern (`_generate_workflow_agent`) wires the canary-bearing instruction into the coordinator agent's prompt. Claude correctly treats canary tokens with suspicion as prompt-injection attempts in this configuration. Graph and Swarm patterns succeed because they delegate to a sub-agent whose system prompt directly contains the canary ask in a less-suspicious framing.
- **Workaround for the matrix tester harness**: bake canaries into the wired *output* (a tool's return value, a memory record, a KB doc) rather than the *system prompt* for multi-agent patterns. The Swarm/Graph PASSes did this implicitly via `handoff_to_agent`. Workflow needs an embedded tool fixture.
- **Documented as a known harness limitation**, not a platform bug to fix.
- **Rule**: Anthropic models are increasingly resistant to in-prompt token-extraction instructions. Test canaries should be baked into externally-fetched data the agent retrieves through its wired components — not into the agent's system prompt. If a hallucination occurs ONLY in patterns where the canary is in the system prompt, it's the harness, not the platform.

### Bug 82 (DOCUMENTED — low priority): guardrails_step doesn't upsert on existing-name conflict
- `guardrails_step.handler` calls `bedrock.create_guardrail(name=...)` directly. If a guardrail with the same name already exists from a prior run that didn't clean up, the call fails with `ResourceAlreadyExistsException`.
- Benign on a green-field deploy. Surfaces only when a previous run left state behind.
- **Workaround**: clean up stale guardrails between runs (`aws bedrock list-guardrails | grep gr_<prefix>`).
- **Future fix**: detect existing-name and either reuse via `get_guardrail` or append a uuid suffix.

### Bug 83 (FIXED 2026-05-18): gateway step missing secretsmanager scope for `bedrock-agentcore-*` namespace
- v5 found `mcp-server-gateway-target` UI deploy fails at `gateway_step` with `AccessDenied` on `secretsmanager:CreateSecret` for ARN `arn:aws:secretsmanager:us-east-1:...:secret:bedrock-agentcore-identity!default/oauth2/<provider>`.
- `CreateOauth2CredentialProvider` writes its client_secret under the AgentCore-managed `bedrock-agentcore-identity!default/oauth2/<n>` Secrets Manager namespace, not the `AgentCore*` or `agentcore-*` prefix the platform IAM previously scoped to.
- **Fix**: Added `arn:aws:secretsmanager:{region}:{account}:secret:bedrock-agentcore-*` to the gateway step's secretsmanager Resource list in `infra/stacks/platform_stack.py`.
- **Rule**: When a service writes secrets on your behalf, audit which prefix it uses. AgentCore Identity uses `bedrock-agentcore-*`, not the platform's project prefix.

### Bug 84 (FIXED 2026-05-18): KB role s3vectors resource scope must include `bucket/index/*` sub-resources
- v5 found `P-KB-001` (S3+S3Vectors) UI deploy fails with the misleading `ValidationException: Bedrock Knowledge Base was unable to assume the given role`.
- Root cause: KB role had `s3vectors:*` actions scoped to bucket ARN only. But `s3vectors:QueryVectors` / `PutVectors` / `GetVectors` / `DeleteVectors` / `DescribeIndex` / `ListIndexes` target the `<bucket>/index/<idx>` sub-resource. Granting only the bucket ARN lets `CreateVectorBucket` / `CreateIndex` succeed but blocks every per-index call. Bedrock surfaces this as an "unable to assume" error rather than the verbatim AccessDenied.
- **Fix**: when an explicit `s3VectorsBucketArn` is provided, also grant on `f"{s3v_arn}/index/*"`. Auto-managed mode keeps `Resource: ["*"]` since the bucket name is unknown until provisioning.
- **Rule**: when an AWS service rejects a `roleArn` with "unable to assume", trust-policy is rarely the bug. The role usually CAN be assumed; one of its inline statements is missing a sub-resource ARN. Investigate which API verbs target sub-resources.

### Bug 85 (FIXED 2026-05-18): runtime DELETE leaks AgentCore Memory on partial-deploy failures
- v5: 5 leftover `AgentCoreMemory-*` IAM roles + 5 ACTIVE memories from prior v4 runs, all from cells where `memory_step` succeeded but a downstream step (e.g. `runtime_configure`) failed before `status_update` persisted `memory_result` to the deployment record.
- DELETE handler at `deployment_handler.py:749-758` correctly calls `delete_memory(memoryId=...)` IF `deployment_record.memory_result.memory_id` is set — but partial failures never reached `status_update`, so the field stayed empty.
- **Fix**: `memory_step.py` now persists `memory_result` to the DDB deployment record IMMEDIATELY after `create_memory()` succeeds, via a direct `dynamodb:UpdateItem` call. If a downstream step fails, DELETE can still find and clean the memory.
- **Rule**: every step that creates a SHARED AWS resource (Memory, Gateway, KB, OAuth2 provider, Cognito pool) MUST persist the resource ID to the deployment record before returning, not wait for the final `status_update` step. Otherwise crash-after-create leaks.

### Bug 86 (FIXED 2026-05-19): Gateway step's CreateOauth2CredentialProvider doesn't reuse on conflict

- v6 found `mcp-server-gateway-target` UI deploy fails on retry with `ValidationException: Credential provider with name: mcp-cred-<gateway> already exists`. The first deploy attempt may succeed at creating the provider but fail downstream; retry hits the name collision.
- **Fix**: Wrapped `create_oauth2_credential_provider()` call in `gateway_deployer.py` with try/except that catches `already exists` / `ConflictException` and looks up the existing provider via `get_oauth2_credential_provider(name=...)` (with list-based fallback).
- **Rule**: Every "Create*" call to AgentCore that has a name-uniqueness constraint MUST handle the already-exists case by looking up the existing resource — partial-deploy failures and retries are expected; idempotency is non-negotiable.

### Bug 87 (FIXED 2026-05-19): Codegen never wired retrieve_from_kb tool — agent had no way to query its KB

- v6 found P-KB-001 deployed successfully but the agent responded "I don't have any ingested documentation or knowledge base...". The KB existed and contained the corpus, but the agent's tool list didn't include any KB retrieval verb.
- **Three-part fix**:
  1. `runtime_configure_step.py` now injects `KB_ID` env var into the runtime when `knowledge_base_result.kb_id` is present.
  2. `code_generator.py::_generate_tools_agent` accepts a `has_kb` flag and, when set, emits a `retrieve_from_kb(query, num_results)` `@tool` that calls `bedrock-agent-runtime:Retrieve` against `KB_ID`. Returns the top-N retrieval results as JSON for the agent to summarize.
  3. `platform_stack.py::_create_shared_runtime_role` adds `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` to the shared runtime exec role. Without this, the agent's call would fail with AccessDenied.
  4. The codegen routing logic now sends KB-connected agents through `_generate_tools_agent` even when no Browser/CodeInterpreter is connected.
- **Rule**: Every "tool" component the user can drag onto the canvas must have THREE corresponding pieces in code: (a) IAM permission on the runtime role, (b) env var(s) the agent reads at runtime, (c) a `@tool` function in generated agent code. Missing any one yields a "tool exists in name only" gap that's invisible at deploy-time but surfaces as "agent doesn't know about its tool" at invocation.

### Bug 88 (FIXED 2026-05-19): KB step assumes S3 Vectors index pre-exists; doesn't auto-create

- After Bugs 73/78/84 fixes, smoke deploy of KB-connected runtime still failed: `ValidationException: The knowledge base storage configuration provided is invalid... The specified index could not be found`.
- Verified via `aws s3vectors list-indexes`: an empty vector bucket has zero indexes. Bedrock requires the index to exist before `CreateKnowledgeBase`. The platform was passing `s3VectorsIndexName="default-index"` but never creating that index.
- **Fix (knowledge_base_step.py)**: Before calling `bedrock_agent.create_knowledge_base()`, check `s3vectors:ListIndexes` on the user-supplied bucket; if the named index is missing, auto-create it with Titan-Embed-Text-v2 defaults (1024 dims, cosine distance, float32). Auto-managed mode (no bucket ARN) keeps Bedrock-managed provisioning.
- **Fix (platform_stack.py)**: Granted KB step Lambda role `s3vectors:ListIndexes`, `CreateIndex`, `GetIndex`, `DescribeIndex`, `CreateVectorBucket`, `DescribeVectorBucket`, `GetVectorBucket`, `ListVectorBuckets`.
- **Rule**: Whenever the platform accepts a bring-your-own-resource ARN (vector bucket, secret, role), the platform should pre-flight-check that all required SUB-resources exist (indexes, secret values, attached policies) and either auto-create them or fail loudly with a clear message — NEVER let the downstream service surface a misleading error like "index not found" that the user can't distinguish from a real-config bug.

### Bug 89 (FIXED 2026-05-19): connected_tools must be auto-derived from sibling configs

- After Bugs 87/88 fixed the KB plumbing, smoke deploy STILL produced an agent without `retrieve_from_kb` because the caller didn't pass `connectedTools=["knowledge_base"]` at the top level. The codegen routing in `code_generator.py::generate_agent_code` was checking `"knowledge_base" in tools` — but `tools` was empty. Result: agent fell through to `_generate_strands_default` (no tools at all) despite the KB being deployed and ingested correctly.
- **Fix (deployment_handler.py)**: Before building the SFN input, auto-derive `connected_tools` from sibling configs: presence of `knowledge_base_config` adds `"knowledge_base"`, `memory_config` adds `"memory"`, `gateway_config` adds `"gateway"`, etc. Caller can still pass an explicit list which is preserved and merged.
- **Rule**: If the user dragged a node onto the canvas (resulting in a `*_config` block in the deploy request), the agent code generator MUST receive that as a connected tool. The platform-side derivation removes a class of "config exists but agent doesn't know about it" gaps that produce hallucinations at invoke time.

### Bug 90 (FIXED 2026-05-19): deployment Lambda role missing bedrock:DeleteDataSource / DeleteKnowledgeBase

- DELETE /api/runtime/{id} cascade tried to clean up KB + data source but failed with `AccessDeniedException ... not authorized to perform: bedrock:DeleteDataSource on knowledge-base/<id>`. KB resources leaked across cleanup runs.
- **Fix**: Added `bedrock:GetKnowledgeBase`, `ListKnowledgeBases`, `DeleteKnowledgeBase`, `DeleteDataSource`, `GetDataSource`, `ListDataSources` to the deployment Lambda's IAM policy.

### Bug 72 VERIFIED (2026-05-19): CFN download path now deploys end-to-end

- After replacing `AWS::BedrockAgentCore::Policy` with `Custom::AgentCorePolicy` in `cfn_template_generator.py`, manually exercised the full CFN download path:
  1. `POST /api/generate-cfn-template` returned a presigned download URL.
  2. Downloaded `bundle.zip`, unzipped into a clean directory containing `template.yaml`, `deploy.sh`, `teardown.sh`, `agent-code/agent.py`, `cfn-provider.zip`, `README.md`.
  3. `aws cloudformation validate-template` succeeded.
  4. `./deploy.sh cfn-smoke-v7-test us-east-1 <artifacts-bucket>` reached `Successfully created/updated stack`. Stack outputs included `RuntimeArn`, `RuntimeId`, `EndpointArn`.
  5. `aws bedrock-agentcore invoke-agent-runtime --payload '{"prompt": "Print the session canary verbatim and nothing else."}'` returned `{"response": "MTX-CANARY-85183376"}` — exact canary verbatim.
  6. `./teardown.sh` reached `DELETE_COMPLETE` cleanly.
- This satisfies success criterion #3 (CFN template deploy of downloaded templates) end-to-end. The path now works for templates without Cedar policy. Templates with Cedar policy (customer-support-blueprint) should also work via Custom::AgentCorePolicy — needs v7 verification.

### Bug 91 (DOCUMENTED 2026-05-19 — known limitation, not a fix): Python 3.10/3.11/3.12 cold-start exceeds AgentCore 30s init

- v7 found that deploying a Strands+Bedrock runtime with `pythonRuntime=PYTHON_3_10/3_11/3_12` produces a stack that comes up successfully but fails first invoke with `RuntimeClientError: Runtime initialization time exceeded. Please make sure that initialization completes in 30s.` Same payload with `PYTHON_3_13` cold-starts in ~5s and returns the canary.
- Likely cause: older Python wheel imports of boto3 + strands_agents take >25s on cold containers. AgentCore's 30s init limit is service-side and not configurable.
- **Workaround for the operator**: use `PYTHON_3_13` (the platform default).
- **Future fix**: deploy-time warning in `validation.py` when older Python is selected with bedrock+strands; long-term, pre-bake deps into a base image.
- v7 cells `v7-ui-PRUN001-py310/py311/py312` and retries are BLOCKED with reason `BUG_91_PYTHON_3_10_11_12_COLD_START_30S_LIMIT` — opt-in environmental, not a deploy failure.

### Bug 92 (FIXED 2026-05-19, REVISED): cfn-provider Lambda's bundled boto3 lacks AgentCore policy methods entirely

- First attempted fix: replace `get_policy_engine` with `list_policy_engines`. Both are missing from Lambda's bundled boto3 — AgentCore's policy API is too new for the runtime SDK snapshot.
- **Real fix**: Bundle boto3 + botocore (+ dateutil, jmespath, s3transfer, urllib3) from `backend/lib/` into the cfn-provider.zip. This gives the cfn-provider Lambda a current SDK with all AgentCore methods. `_package_cfn_provider` now walks `backend/lib/` and adds the boto3 stack to the zip.
- **Rule**: Lambda runtime SDK is a frozen snapshot. For services with rapidly-evolving APIs (AgentCore is brand new), ship your own SDK in the deployment package. Do not assume the runtime has any specific service operation available.

- After Bug 72 fix shipped Custom::AgentCorePolicy, T4 (customer-support-blueprint) CFN deploys WITH a Cedar policy still hung CREATE_IN_PROGRESS for >30min. CW logs revealed: `'BedrockAgentCoreControlPlaneFrontingLayer' object has no attribute 'get_policy_engine'` — Lambda's bundled boto3 is older than the AgentCore SDK update that added `get_policy_engine`.
- Local boto3 (current) has `get_policy_engine` and works fine. But the Lambda runtime ships its own boto3.
- **Initial attempted fix (insufficient)**: Replaced `ctrl.get_policy_engine(policyEngineId=engine_id)` with `ctrl.list_policy_engines()` + filter. Both methods exist locally but neither was in the Lambda runtime's bundled boto3.
- **Real fix**: Bundle boto3 + botocore in cfn-provider.zip — see this entry's "REVISED" version below.
- **Rule**: Lambda runtime bundles boto3 at a snapshot in time. Don't rely on the latest service-specific methods unless you ship your own boto3 in the deployment package. Prefer `list_*` + filter over `get_*` for very-new APIs that may not yet be in the bundled SDK.

### Bug 93 (FIXED 2026-05-19): AgentCore CreatePolicy implicitly requires bedrock-agentcore:ManageAdminPolicy

- After bundling boto3 in cfn-provider (Bug 92 real fix), T4-with-policy CFN deploy reached `Custom::AgentCorePolicy` and called `create_policy`. AccessDenied on `bedrock-agentcore:ManageAdminPolicy`.
- This permission is not documented in any obvious AgentCore doc but is required for `CreatePolicy` to succeed.
- **Fix**: Added `bedrock-agentcore:ManageAdminPolicy` and `bedrock-agentcore:UpdatePolicy` to (a) the cfn-provider role's `AgentCorePolicyManagement` policy in `cfn_template_generator.py`, and (b) the platform's `step-policy` role in `platform_stack.py`.
- **Rule**: When AgentCore returns AccessDenied for an undocumented action like `ManageAdminPolicy`, grant exactly the missing action. This is the second hidden-permission case (Bug 65 was `CreateWorkloadIdentity`, Bug 79 was `CreateTokenVault`). AgentCore implicitly creates/manages siblings during many primitive Create calls.

### Bug 94 (FIXED 2026-05-19): Web Crawler data source rejects empty seed URLs

- v9 Band 5 found P-KB-008 (Web Crawler) FAILs CreateDataSource with `ValidationException: seedUrls.N.member.url`. The frontend's webCrawlerUrl field accepts a comma-separated string, sometimes with trailing commas → empty entries pushed into `seedUrls`.
- **Fix**: `_build_data_source_config` now splits/normalizes `webCrawlerUrls` (or legacy `webCrawlerUrl`) and filters out empty entries. Raises a clean ValueError if all entries are empty.

### Bug 95 (FIXED 2026-05-19): BDA parsing requires `supplementalDataStorageConfiguration`

- v9 Band 5 found P-KB-013 (Bedrock Data Automation parsing) FAILs CreateKnowledgeBase: `parsingStrategy=BEDROCK_DATA_AUTOMATION` requires `supplementalDataStorageConfiguration` for intermediate output.
- **Fix**: When `parsingStrategy=bedrock_data_automation`, the KB step now attaches `supplementalDataStorageConfiguration.supplementalDataStorageLocations[]` with an S3 URI under the artifacts bucket (`kb-supplemental/<kb_name>/`).
- Operator can override via `bdaSupplementalS3Uri` in kb_config.

### Bug 96 (FIXED 2026-05-19): Semantic chunking requires `semanticChunkingConfiguration` block

- v9 Band 5 found P-KB-016 (semantic chunking) FAILs CreateDataSource: `chunkingStrategy=SEMANTIC` without the matching configuration block returns ValidationException.
- **Fix**: When `chunkingStrategy=SEMANTIC`, the KB step now emits `semanticChunkingConfiguration` with maxTokens (default 300), bufferSize (default 0), breakpointPercentileThreshold (default 95). Operator can override via `semanticMaxTokens` / `semanticBufferSize` / `semanticBreakpointPercentile` in kb_config.

### Bug 97 (DOCUMENTED — feature gap, not a runtime bug): Custom data source connector not implemented

- P-KB-012 (custom dataSource type) currently raises `Unsupported data source type: custom` in `_build_data_source_config`. The custom-connector path requires backend support not yet built (Bedrock's "custom" KB connector lets you write your own connector Lambda).
- **Workaround**: until implemented, custom KB sources can be wired by uploading documents to S3 and using S3 as the data source.

### Bug 98 (FIXED 2026-05-19): Memory `summary` strategy requires {sessionId} in namespace

- v9 Band 5 P-MEM-LTM-003 (summary) FAILed CreateMemory: "Memory strategy summary is of Summarization type requiring {sessionId} as a mandatory part of namespace".
- Platform was emitting `agent/{actorId}/summary/` — no sessionId placeholder.
- **Fix**: `memory_step.py` now picks strategy-specific default namespaces. For `summary`: `/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}/`. Operator can still override via `strategy.namespaces`.

### Bug 99 (FIXED 2026-05-19): Memory `episodic` reflection namespace prefix rule

- v9 Band 5 P-MEM-LTM-004 (episodic) FAILed: "Reflection namespace '/strategies/{memoryStrategyId}/actors/{actorId}/' must be the same as or a prefix of the episodic namespace".
- AgentCore's reflection mechanism for episodic memory enforces a fixed prefix.
- **Fix**: Default episodic namespace now `/strategies/{memoryStrategyId}/actors/{actorId}/` so reflection's prefix matches exactly.

### Bug 100 (KNOWN LIMITATION): Memory `custom` strategy requires extraction/consolidation prompts

- v9 Band 5 P-MEM-LTM-005 (custom override) FAILed: "Invalid memory strategy input was provided".
- AgentCore's `customMemoryStrategy` requires both `extraction.appendToPrompt` and `consolidation.appendToPrompt` (or full prompt configurations) — the platform doesn't expose UI for these and emits an empty config that the API rejects.
- **Workaround**: caller must pass full custom strategy config in kb_config. Documented as feature gap.

### Bug 14: Memory Strategy API Key Format Mismatch
- `create_memory()` `memoryStrategies` list expects keys like `semanticMemoryStrategy`, `summaryMemoryStrategy`, `episodicMemoryStrategy`, `userPreferenceMemoryStrategy`, `customMemoryStrategy`
- Code was passing raw type names like `SEMANTIC`, `summary` as the dict key
- Error: `Unknown parameter in memoryStrategies[0]: "summary", must be one of: semanticMemoryStrategy, summaryMemoryStrategy, ...`
- **Fix**: Added `STRATEGY_KEY_MAP` that maps lowercase type names to the correct API key format (e.g., `"semantic"` → `"semanticMemoryStrategy"`)
- **Rule**: AWS API parameter names for nested structures are camelCase with specific suffixes. Always check the boto3 parameter validation error for the exact expected key names. Don't assume the API key matches the enum/type value.

### Bug 105 (FIXED 2026-05-19): deploy_gateway leaked partial resources on mid-flow failure

- `backend/src/app/services/gateway_deployer.py:1150-1773` — `deploy_gateway` is ~590 lines and creates Cognito pool, gateway IAM role, gateway, Lambdas, OAuth credential providers, custom-tool Lambdas/roles, and KB Lambda in sequence. The outer `except` only logged and returned `{"success": False, "error": ...}`; partial resources stayed in the account.
- **Fix**: Introduced `partial_state` dict at function entry, populated as each major resource is created (`client_info` after Cognito/external IDP, `gateway_id` after CreateGateway and after the FAILED-recreate path and the reuse path, `lambda_function_name` for both DynamicTools and CustomerSupportTools, `custom_tool_lambdas` / `custom_tool_roles` mirrored alongside the existing local lists). The outer `except` calls `cleanup_gateway_resources(runtime_id="", region=region, gateway_config=partial_state)` before returning the error dict. cleanup is best-effort and itself wrapped in try/except so a rollback failure is logged but does not mask the original error.
- **Rule**: Long imperative deploy functions that create cloud resources MUST track partial state in a dict that doubles as a cleanup-config payload. Wrap the body in a try/except that drives the existing cleanup helper. Never trust the caller to re-run cleanup — they may not know which resources got created. Decomposing the function is out of scope for one iteration; rollback is the minimum bar.

### Bug 106 (FIXED 2026-05-19): handle_delete_runtime returned success:True when gateway/KB/memory/guardrail/policy/MCP cleanups failed

- `backend/src/app/deployment_handler.py:699-935` — Bug 44 only flipped the success flag for runtime-destroy. Every other cleanup block (`MCP server`, `policy engine`, `memory`, `guardrail`, `gateway`, `KB Lambda`, `KB resource`) caught its exception, appended a string to `cleanup_messages`, and continued. The final `DeleteResponse(success=not runtime_destroy_failed, ...)` therefore returned `success=True` even when a Cognito pool / KB / guardrail leaked.
- **Fix**: Added `cleanup_failures: list[str]` tracker. Every cleanup `except` now appends a label (`"mcp_server_runtime"`, `"policy_engine"`, `"memory"`, `"guardrail"`, `"gateway"`, `"kb_lambda"`, `"knowledge_base"`). Also catches the case where `cleanup_gateway_resources(...)` returns its log with " error:" lines (it never raises, just collects per-target errors). Final `overall_success = not runtime_destroy_failed and not cleanup_failures`, and the failure labels are appended to the response message: `"Cleanup failures in: gateway, memory"`.
- **Rule**: When a function does a sequence of best-effort cleanups, a single failure-flag bound to one step (here: runtime-destroy) hides cascade failures. Track each step independently and OR the flags. Helper functions that swallow errors into a return-list (like `cleanup_gateway_resources`) need a post-call check on that list before claiming success.

### Bug 107 (FIXED 2026-05-19): platform_stack.py section banners — S3 / IAM groups unlabeled or mislabeled

- `infra/stacks/platform_stack.py` is 2200 lines with most major construct groups already labeled by `# ---` banners (DynamoDB Tables, SSM Parameters, Lambda Code Asset, Step Functions, Cognito, API Gateway, S3 + CloudFront, Stack Outputs, CloudWatch Alarms). Two were wrong:
  - The `_create_artifacts_bucket` and `_upload_agentcore_deps` (S3 resources, lines ~361-401) sat under a `# Lambda Functions` banner.
  - The `_create_shared_runtime_role` IAM block had no banner separating it from the preceding S3 section.
- **Fix (comments-only)**: Renamed the S3 banner above `_create_artifacts_bucket` to `# S3 (Artifacts Bucket + AgentCore Deps Upload)`, and inserted a new `# IAM Roles + Lambda Functions` banner immediately above `_create_shared_runtime_role`. No code was moved — purely orientation for readers.
- **Rule**: When a monolithic file accumulates >2k lines, banner labels are the cheapest navigation aid and the highest-leverage maintainability touch. Keep the banners ACCURATE — a wrong label is worse than no label.

### Bug 108 (FIXED 2026-05-19): DeployPanel.tsx 1200 lines — added section banners, no behavior change

- `frontend/src/components/deploy/DeployPanel.tsx` is 1200 lines mixing deploy submission, polling, streaming chat, CFN download, and render. Decomposing into hooks/sub-components is a multi-PR refactor.
- **Fix (comments-only)**: Inserted six `// ====` section banners inside the `DeployPanel` component: State Hooks, useEffect Chain, Deploy Submission (`handleDeploy`), CFN Download UI (`handleDownloadCfn`), Streaming Chat (`handleTest`/`handleNewSession`/`handleKeyDown`/`handleDelete`), and Render (start of returned JSX). Frontend `tsc --noEmit` passes.
- **Rule**: When a component grows past ~500 lines, ship banner comments first so the next reader can find the deploy logic vs the chat logic without scrolling. Banner comments are zero-risk; refactor can follow with confidence.

### Bug 109 (DOCUMENTED 2026-05-19): code_generator.py uses triple-quoted f-strings intentionally

- `backend/src/app/services/code_generator.py` has 14 top-level generator functions (`_generate_langchain_web_search`, `_generate_strands_gateway`, `_generate_mcp_server_runtime`, etc.) that emit Python agent source via triple-quoted f-strings. Audit #15 flagged the pattern as a maintainability concern.
- **Fix (comments-only)**: Added a top-of-file Convention block that explains the trade-off: (a) generated code is post-processed by `_inject_otel(...)` which does string rewrites — Jinja/AST output would force every post-processor to re-parse, (b) per-template variation is too dynamic for a flat template language, (c) refactor cost > current maintenance burden. The block ends with a checklist for any future contributor who wants to migrate to Jinja: read lessons.md, verify `_inject_otel` still works, run matrix-tester end-to-end.
- **Rule**: Code-as-strings can be a deliberate choice when downstream consumers do string-level transformations. Document the convention so contributors do not "clean it up" and break the post-processor. If the convention ever changes, update the top-of-file comment first.

## 2026-05-19: Colleague-audit fixes (Bugs 101-104)

### Bug 101 (FIXED 2026-05-19): CDK-NAG suppressions applied stack-wide hide regressions

- `infra/app.py:64-120` previously called `NagSuppressions.add_stack_suppressions(stack, [...IAM5, IAM4, S1, CFR1, CFR4, APIG1, APIG4, COG2, COG4, COG8, L1, SF1...], apply_to_nested_stacks=True)` — every wildcard anywhere in `PlatformStack` was silently absorbed.
- A future contributor adding `actions=["*"], resources=["*"]` to a totally unrelated construct would never see a nag finding.
- **Fix**: removed the stack-wide call from `infra/app.py`; added `PlatformStack._apply_nag_suppressions()` (`infra/stacks/platform_stack.py`) which calls `NagSuppressions.add_resource_suppressions(<construct>, [...], apply_to_children=True)` per construct. IAM4/IAM5 scoped to specific Lambda execution roles + the shared runtime exec role + the State Machine role; L1 to specific Lambdas; S1 to the logging bucket only; CFR1/CFR4 to the distribution; APIG1/APIG4 to the API; COG2/COG4/COG8 to the user pool; SF1 to the state machine.
- **Rule**: never apply CDK-NAG suppressions stack-wide. Always scope to the specific construct that legitimately needs the exception. New wildcards in unrelated code should fail the build, not get silently hidden.

### Bug 102 (FIXED 2026-05-19): Silent in-memory storage fallback in Lambda

- `backend/src/app/main.py:33-44` checked `if config.dynamodb_table_name:` and otherwise logged "Using in-memory storage" and continued. A misconfigured Lambda (env var typo, missing parameter) would accept writes that vanished between cold-start invocations — users would silently lose work.
- **Fix**: detect Lambda via `os.environ.get("AWS_LAMBDA_FUNCTION_NAME")` (set automatically by the Lambda runtime). If running in Lambda AND the DynamoDB env var is missing, raise `RuntimeError("Storage misconfigured: DYNAMODB_TABLE_NAME unset in Lambda environment")` at module-load time so the function fails to initialise instead of silently corrupting state. Local dev (no `AWS_LAMBDA_FUNCTION_NAME`) keeps the in-memory fallback for offline FastAPI development. Same treatment applied to `DYNAMODB_FLOWS_TABLE_NAME`.
- **Rule**: data-store fallbacks ("if env unset, use ephemeral storage") are a development convenience that becomes a production foot-gun. Always gate them on a Lambda/production marker (`AWS_LAMBDA_FUNCTION_NAME`, `AWS_EXECUTION_ENV`) and fail-fast in those environments.

### Bug 103 (FIXED 2026-05-19): O(N) DynamoDB Scan per test/delete on DeploymentsTable

- `backend/src/app/deployment_handler.py::_scan_for_runtime` (called from `handle_test_runtime`, `handle_test_runtime_streaming`, and `handle_delete_runtime`) used `table.scan(FilterExpression="runtime_id = :rid", ...)` paginated through every deployment record in the table.
- DeploymentsTable had GSIs on `workflow_id` and `user_id` only — no GSI keyed on `runtime_id`. Cost and latency scaled linearly with table size; at 100k+ deployments every test/delete burned 100k RCU + the API Gateway 30s budget.
- **Fix**: added a `runtime_id-index` GSI to DeploymentsTable in `infra/stacks/platform_stack.py::_create_deployments_table`. Updated `_scan_for_runtime` to `table.query(IndexName="runtime_id-index", KeyConditionExpression="runtime_id = :rid", Limit=1)` first; falls back to the original paginated Scan when (a) the GSI Query throws (covers stacks that haven't redeployed since the CDK change) or (b) the Query returns zero items because the deploy was partial-failed and never wrote a `runtime_id` attribute.
- **Rule**: any handler that looks up a row by a non-PK attribute on a hot path (delete/test/invoke) needs a GSI. `Scan` with `FilterExpression` is O(N) — Filter happens server-side AFTER the read, so you pay for every item scanned regardless of whether it matches.

### Bug 104 (FIXED 2026-05-19): Auto-save errors swallowed by `useAutoSave` hook

- `frontend/src/hooks/useAutoSave.ts:165` had `saveFlow(...).catch(() => { /* saveFlow already sets flowStore.error internally */ })`.
- `flowStore.error` is shared across every flow operation (createFlow, openFlow, listFlows, renameFlow, saveFlow), so any subsequent successful operation immediately wipes the auto-save failure indicator. The user would only see an autosave-failed banner if they happened to be looking at the FlowSidebar at the right millisecond.
- **Fix**: hook now returns a `UseAutoSaveResult { lastSaveError: Error | null; clearLastSaveError(): void }`. Catch block calls `setLastSaveError(error)`; success path clears it. `App.tsx` consumes the return value and renders a dismissable bottom-right toast when `lastSaveError` is non-null. Backwards-compatible: callers that ignore the return value still work because the hook still subscribes and saves the same way.
- **Rule**: hooks that perform background work which can fail must expose an error state to callers. Don't rely on a shared `store.error` field that gets clobbered by other operations — give each background task its own scoped error channel.

### Bug 73 (FRONTEND-FIXED 2026-05-19): KB modal didn't expose `s3VectorsBucketArn` / `s3VectorsIndexName` / `s3VectorsIndexArn`

- Backend `knowledge_base_step.py::_build_storage_config` (lines 286-300) already accepts these three fields and falls back to a fully-managed S3 Vectors index when they are absent. But `frontend/src/components/modals/kb/VectorStoreFields.tsx::VectorStoreS3VectorsFields` rendered only a "fully managed" banner — there was no way for an operator to attach an existing S3 Vectors bucket/index from the KB modal UI.
- **Fix**: extended `KnowledgeBaseToolConfig` in `frontend/src/types/components.ts` with three optional fields (`s3VectorsBucketArn`, `s3VectorsIndexName`, `s3VectorsIndexArn`). Reworked `VectorStoreS3VectorsFields` (`frontend/src/components/modals/kb/VectorStoreFields.tsx`) to render an "Advanced (custom bucket)" toggle that exposes the three optional inputs. Default state is collapsed (managed mode unchanged), but the toggle starts open if the loaded config already has any of the values set, so editing an existing flow doesn't hide a populated field.
- **Rule**: when adding a backend-accepted optional field, audit the corresponding frontend modal in the same PR. Backend acceptance + frontend gap = a "feature exists for API callers only" trap that takes operators an hour of reverse-engineering to discover.

### Bug 111 (FIXED 2026-05-20): DDB GSI rejects runtime_id=NULL on initial DeploymentState write

- v10 Tier-1 + Tier-2 + GW-wiring agents all returned NO_GO with the same root error in CloudWatch: `ValidationException: Type mismatch for Index Key runtime_id Expected: S Actual: NULL IndexName: runtime_id-index`. Every `POST /api/deploy` returned HTTP 500 within seconds. Detected in 3 independent verification runs against the live updated stack.
- Root cause: Bug 103 added a `runtime_id-index` GSI to the DeploymentsTable so test/delete handlers could resolve runtime_id via Query instead of O(N) Scan. But `serialize_deployment_state` in `backend/src/app/services/deployment_state_store.py:189` called `state.model_dump(mode="json")` without `exclude_none=True`. On initial intake the `runtime_id` field is None (the runtime hasn't been created yet), so the serialized item carried `runtime_id={"NULL": true}` — and DDB rejects NULL key values for any GSI key.
- **Fix**: changed serializer to `state.model_dump(mode="json", exclude_none=True)`. Optional fields (runtime_id, gateway_url, completed_at, error_details, runtime_endpoint, execution_arn) are now omitted when None instead of stored as NULL. The GSI accepts the write because the `runtime_id` attribute is simply absent until the runtime step actually populates it.
- Added regression test at `backend/tests/test_deployment_state_properties.py::test_serialize_omits_optional_none_fields_for_gsi_safety` that asserts the 6 optional fields are absent from the serialized item.
- **Rule**: when adding a GSI to a table that already has writers, audit the writers' serialization layer for NULL emission. Pydantic's `model_dump(mode="json")` writes None as JSON null which becomes DDB NULL — always pair `mode="json"` with `exclude_none=True` for items destined for tables with GSIs. Better still: use a Pydantic `model_serializer` that explicitly omits None fields. The bug was caught only because three independent v10 verification agents converged on the same error in CloudWatch — a less rigorous validation pass would have shipped this.

### Bug 110 (FIXED 2026-05-19): Gateway agent silently ran with zero tools when MCP discovery failed

- Coverage-audit finding #109 (logged in `tasks/matrix-tester/coord/findings.jsonl:109`): 9 GW-LAM/OAS/SMI cells (P-GW-LAM-001..005, P-GW-OAS-001..003, P-GW-SMI-001) reported PASS in the v9 ledger but zero CloudWatch invocations on `AgentCoreDynamicTools`. `MCPClient.start()` succeeded but `list_tools_sync()` returned an empty list, and the agent answered the canary directly out of the system prompt — masking the wiring failure.
- **Fix**: `backend/src/app/services/code_generator.py::_get_agent` (gateway template, line ~558) and `_get_gateway_tools` in the memory-enabled gateway template (line ~1078) both now `raise RuntimeError(...)` when `tools == []` AND `GATEWAY_URL` is non-empty. This converts the silent wiring failure into a 500 from the runtime, which the matrix-tester's response-shape gate already detects as FAIL. Bug 105's WARNING-level log line stays in place as the diagnostic breadcrumb in CloudWatch; this fix makes the response itself indicate the wiring is broken.
- **Rule**: a gateway-enabled agent that came up with zero tools is structurally indistinguishable from a non-gateway agent that learned the canary from its system prompt. Always assert tool-discovery succeeded — don't trust a downstream model output as proof. Make wiring failures fast-fail at first invocation, not silently degrade. Pair with a tool-invocation-count canary in the test harness for double-coverage.

### Bug 82 (FIXED 2026-05-19): guardrails_step now upserts on `ResourceAlreadyExistsException`

- `backend/src/app/step_handlers/guardrails_step.py:204` previously called `bedrock.create_guardrail(name=…)` with no rollback path. After a partial deploy that created the guardrail but failed downstream, the next retry hit `ResourceAlreadyExistsException` and the whole step failed instead of reusing the existing guardrail.
- **Fix**: added `_find_guardrail_id_by_name(bedrock, name)` (paginates `list_guardrails`, falls back to a non-paginated call) plus a try/except around `create_guardrail`:
  1. On `ResourceAlreadyExistsException`, look up the existing guardrail by name and call `update_guardrail(guardrailIdentifier=…, **create_params_minus_name)` to bring the policy in line with the current config.
  2. If the lookup fails (race / rename collision), retry once with `name` suffixed by `uuid.uuid4().hex[:8]`.
  Both paths set `guardrail_id` to a real ID; the existing wait-for-READY loop and `create_guardrail_version` call run unchanged. The DELETE cleanup path in `deployment_handler.py:818-829` keys off `guardrails_result.created_by_flow` + `guardrail_id`, both of which we still set, so cleanup remains correct (we treat the upsert as "created by flow" since the policy is now ours regardless of who created the row).
- **Rule**: every step that creates a named AWS resource MUST handle `*AlreadyExistsException` with either (a) lookup-by-name + update or (b) UUID-suffixed rename. Step Functions retries (and operator-driven re-runs) make idempotency a hard requirement, not a nice-to-have. Same pattern as Bug 86's KB-name guard.

## 2026-05-20: Critic-review hardening (Critic Findings 1/2/3)

### Critic Finding 1 (FIXED 2026-05-20): cross-tenant Secrets Manager exfiltration via `auth_header_secret_arn`

- The Observability node accepted any `auth_header_secret_arn` from the canvas config. The runtime IAM role was granted `secretsmanager:GetSecretValue` on that ARN, the runtime resolved it to a header value, and OTEL emitted it as `Authorization: <secret>` to a tenant-controlled `OTEL_EXPORTER_OTLP_ENDPOINT`. A tenant could therefore name *any* secret ARN they could enumerate (e.g. another team's billing key) and exfiltrate the value to their own OTLP collector on every invocation.
- **Fix**: `backend/src/app/services/observability.py::_validate_user_otel_secret_arn` regex-matches `^arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:agentcore-otel/[A-Za-z0-9_/-]+`. Applied at every per-canvas read site (lines 139 and 194). Platform-default ARNs from SSM bypass the check (admin-managed). `routers/observability.py::store_credentials` derives `owner_sub` from the JWT and embeds it in the secret name (`agentcore-otel/{provider}/{owner_sub}-{uuid}`) plus tags the secret with `owner_sub`/`created_at_iso`/`Purpose=user-otel-auth` so cross-tenant ownership is auditable. `step_handlers/iam_step.py:75-90` validates per-canvas ARNs before the IAM grant — on validation failure logs a WARNING and disables OTEL for that runtime rather than failing the deploy.
- **Rule**: any external ARN the user submits that ends up in a tenant IAM grant MUST be namespace-validated against a regex *before* the grant is written. Don't let user-controlled identifiers flow into IAM policies as opaque strings.

### Critic Finding 2 (FIXED 2026-05-20): SSRF guard bypassable via DNS rebinding

- `backend/src/app/services/gateway_deployer.py::_create_external_oauth_config` previously rejected only literal-IP hostnames. A hostname like `evil.attacker.com` resolving to `169.254.169.254` (IMDS) sailed through. The error-handling chain matched on substring-of-error-message which is fragile.
- **Fix**: new `_validate_discovery_url(url)` that (a) enforces `https` scheme, (b) calls `socket.getaddrinfo` under a 5s timeout, (c) iterates *every* resolved IP and rejects matches against a 21-network IPv4/IPv6 denylist (loopback, link-local incl. IMDS + Lambda creds, RFC1918, CGNAT, multicast, ULA, IPv4-mapped IPv6), (d) raises distinct exception classes (`_DiscoveryUrlInvalid`, `_DiscoveryUrlBlocked`, both subclassing `ValueError`) — no substring matching. Added optional `OIDC_DISCOVERY_HOST_ALLOWLIST` env var for operator-pinned host whitelisting. Outer `urlopen` failure now re-raises (no log-and-continue silent fallback). Same defense applied to the embedded `_do_fetch_webpage` Lambda template.
- **Tests**: 30 negative-path tests in `backend/tests/test_gateway_deployer_ssrf.py` covering IMDS / Lambda creds / RFC1918 / CGNAT / multicast / ULA / link-local / loopback / IPv4-mapped IPv6 / multi-A-record-with-private / scheme rejection / DNS failure / allowlist match-and-miss.
- **Residual risk**: TOCTOU between `getaddrinfo` and `urlopen`. Mitigated by 10s urlopen timeout + operator allowlist; full pinning would require `urllib3.HTTPSConnectionPool(host=resolved_ip, assert_hostname=original)`. Tracked as v11 follow-up.
- **Rule**: SSRF guards MUST resolve DNS up-front and validate every resolved IP against a denylist. Hostname-only checks are bypassable via DNS rebinding. Substring matching on exception messages is never a valid control.

### Critic Finding 3 (FIXED 2026-05-20): X-Test-Sub header trust + None-owner record bypass

- `backend/src/app/services/auth.py:64-67` accepted an `X-Test-Sub` header in non-Lambda code paths. The "in Lambda" detection (`request.scope.get("aws.event")`) was a heuristic, not an authentication boundary, so any future code path that cleared `aws.event` while still serving an authenticated request would honor the caller's `X-Test-Sub`.
- `auth.py:78` early-returned when `record_owner_sub is None`, granting every authenticated user access to every legacy/unowned record. Combined with `routers/flows.py:106` (`(getattr(c, "owner_sub", None) or caller_sub) == caller_sub`), every legacy flow appeared in every tenant's listing.
- **Fix**: deleted the X-Test-Sub header path entirely (tests now use FastAPI `dependency_overrides` instead). `assert_owner` raises `HTTPException(404)` when `record_owner_sub is None` (preserving existence-non-disclosure). `routers/flows.py` and `routers/workflows.py` now use strict `getattr(c, "owner_sub", None) == caller_sub` equality, so None-owner records are invisible to all callers. New negative-path tests in `backend/tests/test_auth_isolation.py` (10 tests) cover X-Test-Sub-ignored + cross-tenant get/list returning 404/empty + legacy-row exclusion.
- **Rule**: never trust a request header for caller identity in production. If tests need to inject sub, use dependency injection — not a request header that the attacker also controls. Treat None-owner records as 404 (hard fail), not "anyone may read" (soft pass) — the latter is a tenant-isolation bypass disguised as backwards-compat.

### Bug 112 (FIXED 2026-05-20): cdk synth fails with CDK-NAG errors when COGNITO_USERS is set

- The cognito user-provisioner sub-stack (created only when `COGNITO_USERS` env var is non-empty) introduces three CDK-managed L2 constructs we never suppressed: our own `CognitoUserProvisionerFn` Lambda, CDK's `Provider` framework Lambda (`CognitoUserProvisionerProvider/framework-onEvent`), and CDK's `LogRetention` helper Lambda (auto-attached when `log_retention=` is passed). All v9/v10 deploys ran with `COGNITO_USERS=""`, so these constructs were never created and CDK-NAG never tripped on them — the regression was invisible until `COGNITO_USERS="user@example.com"` was passed and `cdk synth` produced 7 errors (L1, IAM4 ×3, IAM5 ×2).
- **Fix**: extended `_apply_nag_suppressions()` in `infra/stacks/platform_stack.py` with two new path-scoped blocks: (a) a hardcoded path for `CognitoUserProvisionerFn` (we own this Lambda; suppress L1 + IAM4-managed-policy), and (b) a `find_all()` walker that adds L1 + IAM4 + IAM5 suppressions to any node whose path contains `CognitoUserProvisionerProvider` or `LogRetention` — both CDK-managed L2s we cannot tighten.
- **Rule**: every conditional sub-stack in CDK (gated by env vars or context flags) must have its CDK-NAG suppressions covered too. Test `cdk synth` with **every combination of optional env vars** at least once, not just the default `unset` posture. CI should run `cdk synth -c cognito_users="test@example.com" -c otel_endpoint="..."` so future regressions like this fail the build at PR time.

### Bug 113 (FIXED 2026-05-20): Customer-support blueprint deployed but Bedrock rejected the model as Legacy at first invocation

- After a fresh deploy of the Customer Support Blueprint template, the runtime came up healthy (`ping` OK, gateway MCPClient discovered 4 tools) but the first invoke hit `botocore.errorfactory.ResourceNotFoundException: An error occurred (ResourceNotFoundException) when calling the ConverseStream operation: Access denied. This Model is marked by provider as Legacy and you have not been actively using the model in the last 30 days.` Model ID was `us.anthropic.claude-sonnet-4-20250514-v1:0` (May 2025) — Bedrock had rotated it to Legacy.
- **Fix #1 (the immediate template bug)**: `frontend/src/data/templates.ts:285` — Customer Support Blueprint switched from `claude-sonnet-4-20250514` → `claude-sonnet-4-5-20250929`. All other templates were already on the 4.5 generation; this one had been missed in a prior sweep.
- **Fix #2 (the policy)**: the user set a policy that *only* models published on Amazon Bedrock between October 2025 and May 2026 are allowed anywhere in the platform. Implemented by:
  - Trimmed `frontend/src/utils/runtimeConfig.ts::MODEL_OPTIONS` to remove all pre-Q4-2025 models (Nova v1 Pro/Lite/Micro, Llama 3.x, Mistral Large 2407, Mistral Small 2402, Cohere Command R/R+, Claude Sonnet 4 / Opus 4.1). Kept only Claude 4.5 family + Nova 2 + Llama 4 + AI21 Jamba 1.5 + GPT OSS + DeepSeek R1/V3.1.
  - Trimmed `frontend/src/components/modals/KnowledgeBaseConfigModal.tsx` and `frontend/src/components/modals/kb/AdvancedFields.tsx` foundation/parsing model lists similarly. Removed Titan Text Premier.
  - Trimmed `backend/src/app/models/deployment_models.py::_BEDROCK_ACTIVE_MODEL_SUBSTRINGS` to the same window.
  - Added an explicit `_LEGACY_SUBSTRINGS` block in `_validate_bedrock_model_id` so a deploy with a pre-cutoff ID fails at `POST /api/deploy` with a clear error message naming the policy window, not at first invocation in production.
- **Rule**: Bedrock model lists rot fast. The frontend dropdown, the validator allowlist, the Legacy blocklist, every template's default model, and every test fixture must be updated in lockstep — they are five separate copies of the same truth. When the user sets a policy window, encode the *floor date* in the validator (not just the active substring list) so any new pre-floor model that ships on Bedrock is automatically rejected. Preserve the policy comment + lessons.md reference so the next contributor doesn't widen the list "to add an old favorite back."

## 2026-05-27: PR #2 review feedback (mNemlaghi)

### Bug 114 (FIXED 2026-05-27): UpdateGuardrail upsert path stripped a required body field

- `backend/src/app/step_handlers/guardrails_step.py:243` built the update kwargs as `{k: v for k, v in create_params.items() if k != "name"}` on the assumption that `name` belonged on `create_guardrail` only. Reviewer pointed out — and the live botocore service model confirms — that `UpdateGuardrail` lists `name`, `blockedInputMessaging`, `blockedOutputsMessaging`, *and* `guardrailIdentifier` as REQUIRED. Stripping `name` would 400 on every idempotent re-deploy that hit the upsert branch.
- **Fix**: replace the comprehension with `{**create_params, "guardrailIdentifier": existing_id}` so the full create payload (including `name`) flows into update. Tests in `backend/tests/test_step_handlers_review_fixes.py::test_update_guardrail_includes_required_name_field` patch `boto3.client` and assert `update_guardrail` is called with both `name` and `guardrailIdentifier`.
- **Rule**: when reusing the create payload as the update payload for an upsert, NEVER drop fields by name on assumption — verify each parameter is or is not allowed against `client.meta.service_model.operation_model('UpdateXxx').input_shape.required_members`. AWS update APIs are inconsistent: some require the resource name, some forbid it; do not guess.

### Bug 115 (FIXED 2026-05-27): KB ingestion config leaked an underscore-prefixed sentinel into the API call

- `backend/src/app/step_handlers/knowledge_base_step.py:620` set `ingestion_config["_bdaSupplementalS3Uri"]` as a sidecar value intended for "the caller of `_build_data_source_config` to read." Nothing read it. Worse, `ingestion_config` was passed verbatim as `vectorIngestionConfiguration` to `bedrock_agent.create_data_source` — a botocore-validated shape that only accepts `chunkingConfiguration`, `customTransformationConfiguration`, `parsingConfiguration`, `contextEnrichmentConfiguration`. Botocore raises `ParamValidationError` on `_bdaSupplementalS3Uri`, so the deploy never succeeded with BDA parsing.
- The KB-level `supplementalDataStorageConfiguration` (where the BDA bucket actually belongs) was already wired correctly on `create_knowledge_base` at line 525 — the underscore-prefixed copy was redundant *and* broken.
- **Fix**: removed the `_bdaSupplementalS3Uri` write entirely; replaced the misleading "sibling field the caller can read" comment with one stating that BDA's bucket is set on the KB, not on the data source. Test `test_create_data_source_does_not_leak_bda_sentinel` asserts only the four documented members appear on `vectorIngestionConfiguration`.
- **Rule**: never use underscore-prefixed sentinel keys on a dict that is going to be passed verbatim to a boto3 API. botocore validates payloads against the service model and rejects unknown keys — sidecar metadata must live on a sibling variable, never on the payload itself. If you find yourself adding a `_xxx` key to a kwargs-bound dict, that's the same bug, every time.

### Bug 116 (FIXED 2026-05-27): policy-engine detach in handle_delete_runtime called update_gateway with bogus param + missing required field

- Found by audit on 2026-05-27 while looking for the same class of bug as Bug 114/115. `backend/src/app/deployment_handler.py:770` (the policy-engine-detach branch of teardown) called `agentcore_ctrl.update_gateway(gatewayIdentifier=..., name=..., roleArn=..., authorizationConfig=gw_detail.get("authorizationConfig", {}))`. Two distinct issues, both confirmed against `boto3.client('bedrock-agentcore-control').meta.service_model.operation_model('UpdateGateway').input_shape`: (a) the real parameter is `authorizerConfiguration`, not `authorizationConfig` — botocore rejects with `Unknown parameter in input`; (b) `authorizerType` is REQUIRED and was missing entirely. The detach therefore *never worked* — every teardown that hit this branch silently failed with `ParamValidationError`, swallowed into `cleanup_messages` as a "warning."
- **Fix**: rebuilt `update_params` to mirror the working pattern in `policy_step.py:156-172` — required fields (`gatewayIdentifier`, `name`, `roleArn`, `authorizerType`, plus `protocolType` to preserve config) explicitly, optional fields copied through if present (`description`, `authorizerConfiguration`, `protocolConfiguration`, `kmsKeyArn`). Crucially, `policyEngineConfiguration` is NOT included — its absence in the update request is what performs the detach. New regression test in `backend/tests/test_step_handlers_review_fixes.py::test_update_gateway_detach_path_validates_against_service_model` reconstructs the production kwargs and runs them through `botocore.validate.ParamValidator` against the live service model — same validator the real boto3 client uses.
- **Rule**: when a cleanup path catches and downgrades exceptions to "warnings," ANY shape bug in that path is silent forever. Treat cleanup-path API calls as more sensitive to validation, not less, because no one is going to see the failure. For every `update_*`/`create_*`/`delete_*` boto3 call we hand-construct kwargs for, write a unit test that runs the kwargs through `botocore.validate.ParamValidator` against `client.meta.service_model.operation_model(<Op>).input_shape` — it's a 5-line test and it catches typos like `authorizationConfig` vs `authorizerConfiguration` that are otherwise invisible until production teardown.
