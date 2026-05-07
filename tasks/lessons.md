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

## 2026-05-07: Market Gaps Execution

### Lesson: CloudFront SPA Fallback Masks API Errors
- CloudFront is configured so 403/404 from any origin rewrite to `/index.html` (for SPA routing).
- Result: `GET /api/does-not-exist` through CloudFront returns `text/html` with HTTP 200 — not the JSON 404 the Lambda produced.
- Integration tests and curl-based bug-bashing MUST hit the raw API Gateway URL when verifying error codes.
- **Rule**: For HTTP-status-sensitive tests, use the API Gateway URL (stack output `ApiGatewayUrl`), not CloudFront.

### Lesson: Deploy script default region is the caller's AWS CLI default
- `./scripts/deploy.sh` reads `AWS_REGION` env var, defaulting to `us-east-1` only inside the script's own variable.
- If AWS CLI's profile has a default region of `us-west-2`, early steps use that and fail.
- **Rule**: Always run with `AWS_REGION=us-east-1 ./scripts/deploy.sh` explicitly.

### Lesson: EventBridge Scheduler requires dedicated invoke role
- `scheduler:CreateSchedule` with a Lambda target needs `RoleArn` pointing to a role that Scheduler can assume (principal `scheduler.amazonaws.com`) AND that has `lambda:InvokeFunction` on the target.
- The caller Lambda needs `iam:PassRole` with `iam:PassedToService=scheduler.amazonaws.com` condition — otherwise the API returns cryptic "user is not authorized to perform: iam:PassRole".
- **Rule**: When introducing a new service that uses PassRole, always add the PassedToService condition and least-privilege it to just that service.

### Bug 14: Memory Strategy API Key Format Mismatch
- `create_memory()` `memoryStrategies` list expects keys like `semanticMemoryStrategy`, `summaryMemoryStrategy`, `episodicMemoryStrategy`, `userPreferenceMemoryStrategy`, `customMemoryStrategy`
- Code was passing raw type names like `SEMANTIC`, `summary` as the dict key
- Error: `Unknown parameter in memoryStrategies[0]: "summary", must be one of: semanticMemoryStrategy, summaryMemoryStrategy, ...`
- **Fix**: Added `STRATEGY_KEY_MAP` that maps lowercase type names to the correct API key format (e.g., `"semantic"` → `"semanticMemoryStrategy"`)
- **Rule**: AWS API parameter names for nested structures are camelCase with specific suffixes. Always check the boto3 parameter validation error for the exact expected key names. Don't assume the API key matches the enum/type value.
