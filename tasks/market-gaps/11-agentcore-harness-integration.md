# Task 11: AgentCore Harness — Full Canvas Integration

## Problem Statement

The **AgentCore Managed Harness** (preview, free tier) collapses Runtime + Gateway + Memory + Identity + Browser + Code Interpreter + orchestration into a single declarative `CreateHarness` API call. Our platform currently makes users wire all these separately via the canvas — 5-8 nodes for what should be ONE configuration.

**What the Harness gives us for free:**
- Stateful sessions in secure, isolated microVMs per session
- Own filesystem and shell per agent (write and execute code)
- Persistent short-term and long-term memory + files across sessions
- Any model: Bedrock, OpenAI, Google Gemini — switch mid-session without losing context
- Tools via Gateway, MCP servers, or built-in browser & code interpreter
- Custom environments (source code, dependencies, tools)
- Shell commands directly on the session (no model reasoning, no token cost)
- Automatic OpenTelemetry tracing via AgentCore Observability
- Powered by Strands Agents (our open-source framework)

**Current state in project:**
- `backend/src/app/services/harness_deployer.py` — boto3 wrapper with CreateHarness, UpdateHarness, GetHarness, DeleteHarness, ListHarnesses
- `backend/src/app/models/harness_models.py` — HarnessConfig, HarnessModelProvider, HarnessStatus, HarnessToolSpec
- `tasks/harness-patterns-catalog.md` — Detailed 15-pattern integration plan (P1-P15)
- CDK custom resource pattern documented (P13)
- NO frontend Harness node exists yet
- NO invoke/chat integration for Harness data plane
- NO Harness deployment option in the deploy flow

## Proposed Solution

Add "Harness" as a **first-class root canvas node** (peer to Runtime) that users can drop and configure as a one-stop agent deployment.

## CreateHarness API Parameters

```python
CreateHarness(
    harnessName="my-agent",
    executionRoleArn="arn:aws:iam::...",
    model={
        "modelId": "anthropic.claude-sonnet-4-20250514",
        "provider": "BEDROCK"  # or OPENAI, GEMINI
    },
    systemPrompt=[{"text": "You are a helpful assistant..."}],
    tools=[
        {"type": "AGENTCORE_GATEWAY", "gatewayArn": "..."},
        {"type": "AGENTCORE_CODE_INTERPRETER"},
        {"type": "AGENTCORE_BROWSER"},
        {"type": "MCP_SERVER", "mcpServerArn": "..."},
        {"type": "INLINE_TOOL", "toolSpec": {...}, "handler": "..."}
    ],
    skills=[{"path": "/path/to/skill"}],
    allowedTools=["*"],  # or specific glob patterns
    memory={"agentCoreMemoryConfiguration": {"arn": "..."}},
    environment={"containerImage": "...", "environmentVariables": {...}},
    authorizerConfiguration={...},
    maxIterations=50,
    maxTokens=4096,
    timeoutSeconds=300,
    truncation={"strategy": "SLIDING_WINDOW"}
)
```

## Files to Create/Modify

### New Frontend Files

1. **`frontend/src/components/nodes/HarnessNode.tsx`**
```typescript
// New root canvas node — similar to RuntimeNode but represents a Harness
// Visual: distinct color/icon from Runtime to differentiate
// Connections: accepts sub-nodes (Memory, Gateway, Code Interpreter, Browser, Skills)
// Status badge: pending → creating → ready → failed
```

2. **`frontend/src/components/modals/HarnessConfigurationModal.tsx`**
```typescript
// Tabs:
// 1. Model — provider selector (Bedrock/OpenAI/Gemini), model ID, temperature
// 2. System Prompt — multi-line editor with variable support
// 3. Tools — checkboxes for built-in (Code Interpreter, Browser), 
//            MCP server selector, inline tool definitions
// 4. Execution — maxIterations, maxTokens, timeoutSeconds, truncation strategy
// 5. Environment — container image URI, env vars, custom skills path
// 6. Memory — toggle + strategy selector (reuses existing MemoryConfigurationModal)
// 7. Identity — authorizerConfiguration for outbound auth
```

3. **`frontend/src/components/deploy/HarnessDeployPanel.tsx`**
```typescript
// Deploy panel variant for Harness deployments:
// - Single-step creation (no multi-step SFN needed!)
// - Status: Creating → Ready
// - Test panel: InvokeHarness via bearer JWT
// - Shows Harness ARN, endpoint URL
// - Shell access button (run commands on the session)
```

### New Backend Files

4. **`backend/src/app/step_handlers/harness_deploy_step.py`**
```python
# Step handler that:
# - Builds CreateHarness params from canvas state
# - Calls harness_deployer.create_or_lookup_harness (P7 idempotency)
# - Polls until READY status (12× × 5s budget)
# - Returns harness ARN + invoke endpoint
```

5. **`backend/src/app/services/harness_invoker.py`**
```python
# Data plane invoker (P6 from patterns catalog):
# - InvokeHarness via raw HTTPS + bearer JWT
# - Supports streaming responses (SSE)
# - Session management (X-Amzn-Bedrock-AgentCore-Runtime-Session-Id)
# - Shell command execution (non-model, no token cost)
```

6. **`backend/src/app/routers/harness.py`**
```python
# Endpoints:
# POST   /api/harness/deploy          - Create harness from canvas config
# GET    /api/harness/{id}/status      - Get harness status
# POST   /api/harness/{id}/invoke      - Invoke harness (proxy to data plane)
# POST   /api/harness/{id}/shell       - Run shell command on session
# DELETE /api/harness/{id}             - Delete harness
# GET    /api/harness/list             - List user's harnesses
```

### Modified Files

7. **`frontend/src/components/palette/ComponentPalette.tsx`**
   - Add "Harness (Managed Agent)" as a top-level node in palette
   - Show feature comparison tooltip: "One node = Runtime + Gateway + Memory + Tools"

8. **`frontend/src/data/templates.ts`**
   - Add new templates using Harness: "Quick Start Agent (Harness)", "Code Assistant (Harness)"
   - These are dramatically simpler than existing templates (1 node vs 4-6)

9. **`infra/stacks/main_stack.py`**
   - Add IAM permissions for `bedrock-agentcore-control:CreateHarness`, `UpdateHarness`, `GetHarness`, `DeleteHarness`, `ListHarnesses`
   - Add IAM for data plane invoke
   - CDK custom resource for Harness lifecycle (P13)
   - Region gating: only enable in us-west-2, us-east-1, ap-southeast-2, eu-central-1

10. **`backend/src/app/services/code_generator.py`**
    - When deploying via Harness: NO code generation needed! The harness IS the orchestration.
    - Only generate code for Runtime-based deployments (backward compat)

## Key Implementation Notes (From harness-patterns-catalog.md)

- **P7 Idempotency**: `create_or_lookup_harness` catches `ConflictException` and returns existing ARN
- **P9 Name Bridge**: Harness names must match `[a-zA-Z][a-zA-Z0-9_]{0,63}` — convert canvas node IDs
- **P10 Region Gating**: Only 4 regions supported in preview. Hide Harness node if region not supported.
- **P6 Invoke Path**: Data plane uses raw HTTPS + bearer JWT. boto3 has no bearer-token path — must sign requests manually.
- **P8 Ordered Teardown**: Delete Harness before deleting Gateway targets it references.

## Deployment Instructions

1. Add Harness IAM permissions to CDK step Lambda role
2. Add region check (SSM parameter or env var)
3. Add Harness node to frontend palette
4. Add Harness deploy route and invoker
5. Deploy: `./scripts/deploy.sh`
6. Test: Drop Harness node → configure → deploy → invoke via chat

## Testing Requirements

### Unit Tests
- HarnessConfig model builds correct CreateHarness params
- Region gating hides node in unsupported regions
- Name normalization (canvas IDs → valid harness names)

### Integration Tests
- CreateHarness → poll until READY → invoke → get response
- Update harness (change model) → verify updated
- Delete harness → confirm cleaned up
- ConflictException handling (idempotent create)

### E2E Tests
- Drop Harness node → configure model + tools → deploy → chat works
- Harness with Code Interpreter → execute code in chat → output returned
- Harness with Browser → browse URL → content returned
- Harness with Memory → multi-session → memory persists

## Security Requirements

- [ ] Execution role follows least-privilege (only bedrock:InvokeModel + specific tools)
- [ ] Bearer JWT tokens scoped per session
- [ ] Region gating prevents deploy to unsupported regions
- [ ] Shell access requires explicit opt-in
- [ ] Environment variables don't contain secrets (use SSM references)
- [ ] Harness ARN not exposed in frontend (only proxy via backend)

## Acceptance Criteria

- [ ] "Harness" node available in component palette
- [ ] Configuration modal covers all CreateHarness parameters
- [ ] One-click deploy creates a working Harness agent
- [ ] Chat panel works with Harness (streaming responses)
- [ ] Shell command execution works from UI
- [ ] Harness with Code Interpreter executes Python
- [ ] Harness with Browser navigates web pages
- [ ] Delete cleans up all resources
- [ ] Backward compatible: Runtime-based deployments still work
- [ ] Templates include "Quick Start (Harness)" for simple 1-node agent
