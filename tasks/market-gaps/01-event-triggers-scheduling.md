# Task 01: Event Triggers & Agent Scheduling

## Problem Statement

**Every single competitor** offers event-driven triggers and scheduling for agents:
- **n8n**: Cron triggers, webhook triggers, 1,100+ event integrations
- **Dify**: Scheduled runs, API triggers, webhook endpoints
- **Microsoft Copilot Studio**: Event-driven triggers from Dataverse, Power Automate, Teams events
- **Google Vertex AI**: EventArc triggers, Cloud Scheduler, Pub/Sub events

Our platform currently only supports **manual invocation** via the in-canvas test panel. Users cannot:
- Schedule agents to run at specific times
- Trigger agents from external events (webhooks, S3 uploads, SNS messages)
- Run agents on a recurring schedule (daily reports, hourly monitoring)

This is the #1 requested feature for any production agent platform.

## Proposed Solution Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ EventBridge     │───▶│ Trigger Lambda   │───▶│ AgentCore       │
│ Scheduler       │    │ (Router)         │    │ Runtime         │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              ▲
┌─────────────────┐           │
│ API Gateway     │───────────┤  (webhook triggers)
│ /triggers/{id}  │           │
└─────────────────┘           │
                              │
┌─────────────────┐           │
│ SNS/SQS/S3     │───────────┘  (event triggers)
│ EventBridge    │
└─────────────────┘
```

## AWS Services

- **Amazon EventBridge Scheduler**: Cron and rate-based scheduling
- **Amazon EventBridge Rules**: Event pattern matching (S3, SNS, custom events)
- **API Gateway**: Webhook endpoint for external triggers
- **DynamoDB**: Trigger configuration storage (table: `AgentTriggers`)
- **Lambda**: Trigger router that invokes the correct AgentCore Runtime

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/trigger_models.py`**
```python
from pydantic import BaseModel
from enum import Enum
from typing import Optional, Dict, Any

class TriggerType(str, Enum):
    SCHEDULE = "schedule"      # Cron or rate expression
    WEBHOOK = "webhook"        # HTTP POST trigger
    EVENT = "event"            # EventBridge event pattern
    S3 = "s3"                  # S3 object created/deleted
    SNS = "sns"                # SNS message received

class TriggerConfig(BaseModel):
    trigger_id: str
    deployment_id: str
    runtime_id: str
    trigger_type: TriggerType
    name: str
    description: Optional[str] = None
    enabled: bool = True
    # Schedule-specific
    schedule_expression: Optional[str] = None  # "cron(0 9 * * ? *)" or "rate(1 hour)"
    # Webhook-specific
    webhook_path: Optional[str] = None
    webhook_secret: Optional[str] = None
    # Event-specific
    event_pattern: Optional[Dict[str, Any]] = None
    # S3-specific
    s3_bucket: Optional[str] = None
    s3_prefix: Optional[str] = None
    s3_events: Optional[list] = None  # ["s3:ObjectCreated:*"]
    # Input template
    input_template: Optional[str] = None  # Jinja2 template for agent input
    # Metadata
    user_id: str = ""
    created_at: str = ""
    last_triggered: Optional[str] = None
    trigger_count: int = 0

class TriggerCreate(BaseModel):
    deployment_id: str
    runtime_id: str
    trigger_type: TriggerType
    name: str
    description: Optional[str] = None
    schedule_expression: Optional[str] = None
    webhook_path: Optional[str] = None
    event_pattern: Optional[Dict[str, Any]] = None
    s3_bucket: Optional[str] = None
    s3_prefix: Optional[str] = None
    s3_events: Optional[list] = None
    input_template: Optional[str] = None

class TriggerUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    schedule_expression: Optional[str] = None
    input_template: Optional[str] = None
```

2. **`backend/src/app/routers/triggers.py`**
```python
# FastAPI router with these endpoints:
# POST   /api/triggers              - Create a trigger
# GET    /api/triggers              - List triggers for user
# GET    /api/triggers/{trigger_id} - Get trigger details
# PUT    /api/triggers/{trigger_id} - Update trigger
# DELETE /api/triggers/{trigger_id} - Delete trigger
# POST   /api/triggers/{trigger_id}/test - Manually fire trigger
# GET    /api/triggers/{trigger_id}/history - Get trigger execution history
```

3. **`backend/src/app/services/trigger_manager.py`**
```python
# Service that:
# - Creates EventBridge Scheduler rules for schedule triggers
# - Creates API Gateway routes for webhook triggers  
# - Creates EventBridge rules for event triggers
# - Manages trigger lifecycle (enable/disable/delete)
# - Invokes AgentCore Runtime when triggered
```

4. **`backend/src/app/step_handlers/trigger_step.py`**
```python
# Step Functions handler that provisions triggers during deployment
```

5. **`frontend/src/components/triggers/TriggerPanel.tsx`**
```typescript
// UI panel in the deploy section showing:
// - List of active triggers for the deployment
// - "Add Trigger" button with type selector
// - Trigger configuration forms (schedule, webhook, event)
// - Enable/disable toggle
// - Execution history with timestamps and status
// - "Test Trigger" button for manual invocation
```

6. **`frontend/src/components/triggers/ScheduleBuilder.tsx`**
```typescript
// Visual cron expression builder
// Presets: Every minute, Every hour, Daily at 9am, Weekly on Monday, etc.
// Custom mode with cron expression input and human-readable preview
```

7. **`frontend/src/components/triggers/WebhookConfig.tsx`**
```typescript
// Shows the webhook URL (auto-generated)
// Webhook secret for verification
// "Copy URL" button
// Request/response format documentation
// Test with curl example
```

### Modified Files

8. **`infra/stacks/main_stack.py`** (or equivalent CDK file)
   - Add DynamoDB table: `AgentTriggers` (PK: trigger_id, GSI: deployment_id)
   - Add Lambda: `trigger-router` (receives events, invokes correct Runtime)
   - Add API Gateway route: `POST /api/webhooks/{trigger_id}`
   - Add IAM role for EventBridge to invoke trigger-router Lambda
   - Add IAM permissions for trigger-router to invoke AgentCore Runtimes

9. **`backend/src/app/main.py`**
   - Register triggers router

10. **`frontend/src/components/deploy/DeployPanel.tsx`**
    - Add "Triggers" tab after deployment completes
    - Show trigger count badge

## Deployment Instructions

1. Add new DynamoDB table to CDK stack
2. Add trigger-router Lambda to CDK stack  
3. Add webhook API Gateway route
4. Run `cdk deploy`
5. Frontend: add trigger components, rebuild and upload

## Testing Requirements

### Unit Tests
- `backend/tests/test_trigger_models.py` - Validate all trigger types
- `backend/tests/test_trigger_manager.py` - Mock boto3 calls
- `frontend/src/components/triggers/TriggerPanel.test.tsx`

### Integration Tests
- Create schedule trigger → verify EventBridge rule exists
- Create webhook trigger → POST to webhook URL → verify agent invoked
- Disable trigger → verify EventBridge rule disabled
- Delete trigger → verify all AWS resources cleaned up

### E2E Tests
- Deploy agent → create cron trigger → wait for execution → check logs
- Deploy agent → create webhook → curl webhook → verify response
- Deploy agent → create S3 trigger → upload file → verify agent ran

## Security Requirements

- [ ] Webhook endpoints require HMAC signature verification
- [ ] Trigger creation requires authenticated user (Cognito)
- [ ] Users can only manage triggers for their own deployments
- [ ] EventBridge rules use least-privilege IAM (only invoke specific Lambda)
- [ ] Webhook secrets stored in Secrets Manager, not DynamoDB
- [ ] Rate limiting on webhook endpoints (API Gateway throttling)
- [ ] Input templates sanitized (no code injection)
- [ ] Trigger execution history is immutable (append-only)

## Acceptance Criteria

- [ ] User can create a schedule trigger from the UI (cron or rate)
- [ ] User can create a webhook trigger and receive the URL
- [ ] Webhook receives POST → agent is invoked → response returned
- [ ] Schedule trigger fires at correct time (±1 min tolerance)
- [ ] Trigger execution history shows last 100 invocations
- [ ] Disabling a trigger stops it from firing
- [ ] Deleting a deployment cleans up all associated triggers
- [ ] CDK-NAG passes with new resources
- [ ] All new Lambdas have X-Ray tracing and CloudWatch alarms
