# Task 02: Human-in-the-Loop Workflows

## Problem Statement

**n8n, Microsoft Copilot Studio, and Dify all offer human-in-the-loop** — the ability for an agent to pause execution, request human approval/input, and resume after receiving it. This is critical for:
- High-stakes actions (sending emails, modifying databases, financial transactions)
- Content review before publishing
- Escalation when agent confidence is low
- Compliance requirements (human oversight of AI decisions)

Key competitor capabilities:
- **n8n**: Built-in "Wait for Approval" node, form-based input collection, multi-user approval chains
- **Microsoft Copilot Studio**: Approval flows via Power Automate, Teams-based approvals
- **Google ADK**: Deterministic guardrails with human checkpoints
- **Dify**: Human annotation for quality feedback loops

Our platform has **zero human-in-the-loop capability**. Agents run to completion with no ability to pause, escalate, or request approval.

## Proposed Solution Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Agent       │────▶│ HITL Lambda   │────▶│ DynamoDB        │
│ Runtime     │     │ (pause agent) │     │ (pending items) │
└─────────────┘     └──────────────┘     └─────────────────┘
                                                   │
                    ┌──────────────┐               │
                    │ Frontend     │◀──────────────┘
                    │ Approval UI  │
                    └──────────────┘
                           │
                    ┌──────────────┐     ┌─────────────────┐
                    │ Approve API  │────▶│ Resume Agent    │
                    │ /approve     │     │ (continue exec) │
                    └──────────────┘     └─────────────────┘
```

## AWS Services

- **DynamoDB**: `AgentApprovals` table (pending/approved/rejected items)
- **Lambda**: HITL handler (creates approval requests, resumes agents)
- **API Gateway**: Approval endpoints
- **SNS** (optional): Email/SMS notifications for pending approvals
- **Step Functions**: Wait-for-callback pattern (task token)
- **SES** (optional): Email approval links

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/approval_models.py`**
```python
from pydantic import BaseModel
from enum import Enum
from typing import Optional, Dict, Any, List

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    TIMED_OUT = "timed_out"

class ApprovalType(str, Enum):
    BINARY = "binary"          # Approve/Reject
    CHOICE = "choice"          # Multiple options
    FORM = "form"              # Structured input
    REVIEW = "review"          # Content review with edit

class ApprovalRequest(BaseModel):
    approval_id: str
    deployment_id: str
    runtime_id: str
    session_id: str
    approval_type: ApprovalType
    title: str
    description: str
    context: Dict[str, Any]  # What the agent was doing
    proposed_action: str      # What the agent wants to do
    options: Optional[List[str]] = None  # For CHOICE type
    form_schema: Optional[Dict] = None   # For FORM type
    content_to_review: Optional[str] = None  # For REVIEW type
    status: ApprovalStatus = ApprovalStatus.PENDING
    timeout_minutes: int = 60
    created_at: str = ""
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution: Optional[Dict[str, Any]] = None
    task_token: Optional[str] = None  # Step Functions callback token

class ApprovalResponse(BaseModel):
    approval_id: str
    decision: ApprovalStatus  # approved or rejected
    feedback: Optional[str] = None
    edited_content: Optional[str] = None  # For REVIEW type
    form_data: Optional[Dict] = None      # For FORM type
    selected_option: Optional[str] = None  # For CHOICE type
```

2. **`backend/src/app/routers/approvals.py`**
```python
# Endpoints:
# GET    /api/approvals              - List pending approvals for user
# GET    /api/approvals/{id}         - Get approval details
# POST   /api/approvals/{id}/resolve - Approve/reject
# GET    /api/approvals/stats        - Counts by status
# POST   /api/approvals/{id}/reassign - Reassign to another user
```

3. **`backend/src/app/services/hitl_service.py`**
```python
# Service that:
# - Creates approval requests in DynamoDB
# - Pauses agent execution (stores task token)
# - Resumes agent when approval received
# - Handles timeouts (auto-reject after N minutes)
# - Sends notifications (SNS/SES)
# - Tracks approval metrics
```

4. **`backend/src/app/services/hitl_tool.py`**
```python
# A Strands tool that agents can call:
# @tool
# def request_human_approval(title, description, proposed_action, approval_type="binary"):
#     """Pause execution and request human approval before proceeding."""
#     # Creates approval request, returns task token
#     # Agent loop stops here until callback received
```

5. **`frontend/src/components/approvals/ApprovalInbox.tsx`**
```typescript
// Approval inbox showing:
// - Pending approvals list with badges
// - Each item shows: agent name, action proposed, context, timestamp
// - Quick approve/reject buttons
// - Expand for full details
// - Approval history
```

6. **`frontend/src/components/approvals/ApprovalDetail.tsx`**
```typescript
// Detailed approval view:
// - Full context of what the agent was doing
// - Proposed action with preview
// - For REVIEW type: editable content area
// - For FORM type: dynamic form renderer
// - Approve/Reject buttons with optional feedback
// - "Request more info" option
```

7. **`frontend/src/components/canvas/HitlNode.tsx`**
```typescript
// New canvas node type: "Human Approval"
// - Drag onto canvas between steps
// - Configure: approval type, timeout, assignee
// - Visual indicator on canvas when approval pending (orange pulse)
```

### Modified Files

8. **`backend/src/app/services/code_generator.py`**
   - Add `request_human_approval` tool to generated agent code when HITL node is connected

9. **`infra/stacks/main_stack.py`**
   - Add DynamoDB table: `AgentApprovals` (PK: approval_id, GSI: deployment_id+status)
   - Add Lambda for HITL handling
   - Add TTL on approval items (auto-expire after 7 days)

10. **`frontend/src/data/templates.ts`**
    - Add new template: "Agent with Human Approval" (demonstrates HITL pattern)

11. **`frontend/src/components/palette/ComponentPalette.tsx`**
    - Add "Human Approval" node to the component palette

## Deployment Instructions

1. Add HITL DynamoDB table and Lambda to CDK
2. Register `request_human_approval` as a built-in tool for code generation
3. Add approval routes to API Gateway
4. Deploy with `./scripts/deploy.sh`
5. Test: Deploy template agent → trigger action → approval appears in UI → approve → agent resumes

## Testing Requirements

### Unit Tests
- Approval model validation (all types)
- HITL service: create, resolve, timeout
- Code generator includes HITL tool when node connected

### Integration Tests
- Create approval → pending in DDB → approve → callback fires
- Timeout: create approval → wait → auto-rejected
- Reject: agent receives rejection and handles gracefully
- Concurrent: multiple approvals for same agent session

### E2E Tests
- Deploy agent with HITL → trigger → approval appears → approve → agent completes
- Deploy agent → trigger → approval appears → reject → agent handles rejection
- Webhook trigger → agent pauses → email notification sent → approve via link

## Security Requirements

- [ ] Only the assigned approver (or admin) can resolve approvals
- [ ] Task tokens are one-time-use (can't approve same request twice)
- [ ] Approval links (if email-based) expire and use HMAC signatures
- [ ] Context data in approvals doesn't expose secrets
- [ ] Rate limiting on approval resolution endpoint
- [ ] Audit log of all approval decisions (who, when, what)

## Acceptance Criteria

- [ ] New "Human Approval" node available in component palette
- [ ] Connecting it to a Runtime adds the HITL tool to generated code
- [ ] When agent calls `request_human_approval`, execution pauses
- [ ] Pending approval appears in the frontend within 2 seconds
- [ ] Approving resumes the agent with the decision context
- [ ] Rejecting resumes the agent with rejection reason
- [ ] Timeout auto-rejects after configured minutes
- [ ] Approval history is preserved and viewable
- [ ] Works with all deployment patterns (direct, SFN, template)
