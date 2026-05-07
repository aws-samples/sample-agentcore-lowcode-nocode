# Task 05: A2A (Agent-to-Agent) Protocol Support

## Problem Statement

**Google's A2A protocol** (launched April 2025, 100+ enterprise partners including AWS, Microsoft, Salesforce, SAP, ServiceNow) is becoming the standard for cross-vendor agent interoperability. Our platform currently supports multi-agent patterns (Graph/Swarm/Workflow) but ONLY within the same deployment — agents cannot:
- Discover and communicate with external agents
- Expose themselves as A2A-compatible services
- Participate in enterprise A2A ecosystems

Key facts:
- A2A uses standard web tech: JSON-RPC 2.0, HTTP/HTTPS, SSE
- Complements MCP: MCP = agent-to-tools, A2A = agent-to-agent
- Linux Foundation governance (vendor-neutral)
- Google Vertex AI, Microsoft, Salesforce all support it
- AWS is a validator partner

## Proposed Solution Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Our Platform                           │
│                                                          │
│  ┌─────────────┐      ┌──────────────────┐              │
│  │ Agent A     │─────▶│ A2A Server       │◀── External  │
│  │ (Runtime)   │      │ (/.well-known/    │    Agents    │
│  └─────────────┘      │  agent.json)     │              │
│                        └──────────────────┘              │
│                                                          │
│  ┌─────────────┐      ┌──────────────────┐              │
│  │ Agent B     │◀─────│ A2A Client       │───▶ External │
│  │ (Runtime)   │      │ (discover &      │    Agents    │
│  └─────────────┘      │  delegate)       │              │
│                        └──────────────────┘              │
└─────────────────────────────────────────────────────────┘
```

### A2A Core Concepts
- **Agent Card** (`/.well-known/agent.json`): Declares agent capabilities, skills, authentication
- **Tasks**: Structured work units with lifecycle (submitted → working → completed/failed)
- **Messages**: Communication within tasks (text, files, structured data)
- **Streaming**: SSE for real-time progress updates
- **Push Notifications**: Webhook callbacks for async completion

## AWS Services

- **API Gateway**: A2A endpoint (`/.well-known/agent.json` + JSON-RPC routes)
- **Lambda**: A2A protocol handler (JSON-RPC 2.0 processing)
- **DynamoDB**: Task state storage (A2A task lifecycle)
- **EventBridge**: Internal event routing for async tasks
- **Secrets Manager**: Authentication credentials for external agents

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/a2a_models.py`**
```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum

class A2ATaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: List[str] = []
    examples: List[str] = []  # Example prompts

class AgentCard(BaseModel):
    """A2A Agent Card - published at /.well-known/agent.json"""
    name: str
    description: str
    url: str  # Base URL for this agent's A2A endpoint
    version: str = "1.0.0"
    protocol_version: str = "0.2"
    capabilities: Dict[str, bool] = {
        "streaming": True,
        "push_notifications": True,
        "state_transition_history": True
    }
    skills: List[AgentSkill] = []
    authentication: Dict[str, Any] = {"schemes": ["bearer"]}
    
class A2ATask(BaseModel):
    id: str
    session_id: Optional[str] = None
    state: A2ATaskState = A2ATaskState.SUBMITTED
    messages: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
    created_at: str = ""
    updated_at: str = ""

class A2AMessage(BaseModel):
    role: str  # "user" or "agent"
    parts: List[Dict[str, Any]]  # [{type: "text", text: "..."}, {type: "file", ...}]
```

2. **`backend/src/app/routers/a2a.py`**
```python
# A2A Protocol endpoints (JSON-RPC 2.0):
# GET  /.well-known/agent.json          - Agent Card discovery
# POST /a2a                              - JSON-RPC endpoint
#   Methods:
#   - tasks/send         - Send a task to this agent
#   - tasks/get          - Get task status
#   - tasks/cancel       - Cancel a task
#   - tasks/sendSubscribe - Send task + subscribe to updates (SSE)
```

3. **`backend/src/app/services/a2a_server.py`**
```python
# A2A Server implementation:
# - Generates agent card from deployment configuration
# - Processes incoming JSON-RPC requests
# - Maps A2A tasks to AgentCore Runtime invocations
# - Handles streaming responses via SSE
# - Manages task lifecycle in DynamoDB
```

4. **`backend/src/app/services/a2a_client.py`**
```python
# A2A Client for outbound agent communication:
# - Discover external agents (fetch agent card from URL)
# - Send tasks to external agents
# - Subscribe to task updates
# - Handle async completion callbacks
# - Retry logic for transient failures
```

5. **`backend/src/app/services/a2a_tool.py`**
```python
# Strands tool for agents to delegate to external A2A agents:
# @tool
# def delegate_to_agent(agent_url, task_description, wait_for_completion=True):
#     """Delegate a subtask to an external A2A-compatible agent."""
```

6. **`frontend/src/components/a2a/A2AConfigPanel.tsx`**
```typescript
// A2A configuration for a deployment:
// - Toggle: "Expose as A2A agent" (creates /.well-known/agent.json)
// - Agent Card editor: name, description, skills
// - Authentication configuration
// - External agents registry: add URLs of agents to delegate to
// - Test: send a task to an external agent from the UI
```

7. **`frontend/src/components/canvas/A2ANode.tsx`**
```typescript
// New canvas node: "External Agent (A2A)"
// - Configure: agent URL, authentication
// - Shows discovered skills from agent card
// - Wire to Runtime: agent can delegate tasks to this external agent
```

### Modified Files

8. **`backend/src/app/services/code_generator.py`**
   - When A2A node connected: add `delegate_to_agent` tool
   - Include A2A client in generated agent code

9. **`infra/stacks/main_stack.py`**
   - Add DynamoDB table: `A2ATasks` (PK: task_id)
   - Add API Gateway routes for A2A endpoints
   - Add Lambda for A2A protocol handling

10. **`frontend/src/components/palette/ComponentPalette.tsx`**
    - Add "External Agent (A2A)" node to palette

## Deployment Instructions

1. Add A2A protocol Lambda and routes to CDK
2. Add A2A task DynamoDB table
3. Expose `/.well-known/agent.json` route on API Gateway
4. Deploy: `./scripts/deploy.sh`
5. Test: Deploy agent → enable A2A → fetch agent card → send task via curl

## Testing Requirements

### Unit Tests
- Agent Card generation from deployment config
- JSON-RPC request parsing and routing
- Task lifecycle state machine (valid transitions only)
- A2A client: discover agent, send task, parse response

### Integration Tests
- Deploy agent with A2A enabled → `/.well-known/agent.json` returns valid card
- Send JSON-RPC `tasks/send` → task created → agent invoked → response returned
- Cancel task → state transitions to "canceled"
- Streaming: subscribe → receive SSE updates → completion

### E2E Tests
- Deploy Agent A (A2A server) → Deploy Agent B (A2A client) → B delegates to A → response flows back
- External agent simulation: mock A2A server → our agent delegates → receives result

## Security Requirements

- [ ] A2A endpoints require authentication (Bearer token or OAuth2)
- [ ] Agent card does not expose internal details (no Lambda ARNs, no DynamoDB tables)
- [ ] Task data encrypted in transit (TLS) and at rest (DynamoDB encryption)
- [ ] Rate limiting on A2A endpoints (prevent abuse)
- [ ] External agent URLs validated (HTTPS only, no internal IPs)
- [ ] Task timeout enforced (prevent infinite delegation chains)
- [ ] Maximum delegation depth (prevent circular delegation)

## Acceptance Criteria

- [ ] Agent Card published at `/.well-known/agent.json` with correct schema
- [ ] External client can send tasks via JSON-RPC and receive responses
- [ ] SSE streaming works for long-running tasks
- [ ] New "External Agent (A2A)" node in component palette
- [ ] Connecting A2A node → agent can delegate subtasks
- [ ] Authentication enforced on A2A endpoints
- [ ] Task lifecycle tracked in DynamoDB with state transitions
- [ ] Compatible with A2A protocol spec v0.2 (a2a-protocol.org)
