# Task 06: Bedrock Guardrails Integration

## Problem Statement

Amazon Bedrock Guardrails is **our own AWS service** for content filtering, and we're not using it! This is embarrassing from a competitive standpoint:
- **48% of cybersecurity pros** rank agentic AI as the #1 attack vector of 2026
- Only 34% of enterprises have AI-specific security controls
- OWASP Top 10 for LLMs lists prompt injection and insecure output handling as top risks

Competitors:
- **Microsoft Copilot Studio**: Built-in DLP, content moderation, topic blocking
- **Google Vertex AI**: Safety filters, grounding attribution, responsible AI toolkit
- **Dify**: Input/output moderation, sensitive word filtering

Our platform has a Cedar-based policy engine but **no content-level guardrails** — no prompt injection detection, no PII filtering, no topic blocking, no output safety checks.

## Proposed Solution

Integrate **Amazon Bedrock Guardrails** natively into the platform:
1. Create guardrails via the UI (topic filters, content filters, PII detection, word filters)
2. Automatically apply guardrails to agent invocations
3. Show blocked/filtered content in conversation UI
4. Dashboard for guardrail violations

## AWS Services

- **Amazon Bedrock Guardrails**: Content filtering, topic denial, PII detection, word filters
- **CloudWatch**: Guardrail invocation metrics
- **DynamoDB**: Guardrail configuration per deployment

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/guardrail_models.py`**
```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ContentFilter(BaseModel):
    type: str  # "SEXUAL", "VIOLENCE", "HATE", "INSULTS", "MISCONDUCT", "PROMPT_ATTACK"
    input_strength: str = "HIGH"   # NONE, LOW, MEDIUM, HIGH
    output_strength: str = "HIGH"

class TopicFilter(BaseModel):
    name: str
    definition: str  # Description of what to block
    examples: List[str] = []  # Example phrases to block
    type: str = "DENY"

class PiiFilter(BaseModel):
    type: str  # "ADDRESS", "EMAIL", "PHONE", "SSN", "CREDIT_CARD", etc.
    action: str = "ANONYMIZE"  # ANONYMIZE or BLOCK

class WordFilter(BaseModel):
    text: str

class GuardrailConfig(BaseModel):
    guardrail_id: Optional[str] = None  # Bedrock guardrail ID (after creation)
    name: str
    description: str = ""
    content_filters: List[ContentFilter] = []
    topic_filters: List[TopicFilter] = []
    pii_filters: List[PiiFilter] = []
    word_filters: List[WordFilter] = []
    blocked_input_message: str = "I cannot process this request due to content policy."
    blocked_output_message: str = "I cannot provide this response due to content policy."
```

2. **`backend/src/app/services/guardrails_manager.py`**
```python
# Service that:
# - Creates Bedrock Guardrails via CreateGuardrail API
# - Updates guardrail versions
# - Deletes guardrails on deployment cleanup
# - Applies guardrails to model invocations (guardrailIdentifier + guardrailVersion)
# - Tracks violations in DynamoDB
```

3. **`backend/src/app/routers/guardrails.py`**
```python
# Endpoints:
# POST   /api/guardrails                    - Create guardrail config
# GET    /api/guardrails/{deployment_id}    - Get guardrail for deployment
# PUT    /api/guardrails/{deployment_id}    - Update guardrail
# DELETE /api/guardrails/{deployment_id}    - Delete guardrail
# GET    /api/guardrails/{id}/violations    - Get violation history
# POST   /api/guardrails/test              - Test text against guardrail
```

4. **`backend/src/app/step_handlers/guardrails_step.py`** (enhance existing)
```python
# Enhanced step handler:
# - Creates Bedrock Guardrail with configured filters
# - Returns guardrail ID and version
# - Stores in deployment state for code generation
```

5. **`frontend/src/components/modals/GuardrailsConfigurationModal.tsx`** (enhance existing)
```typescript
// Enhanced modal with tabs:
// Tab 1: Content Filters
//   - Sliders for each content type (Sexual, Violence, Hate, etc.)
//   - Separate input/output strength levels
//   - "Prompt Attack" filter toggle (critical for prompt injection!)
//
// Tab 2: Topic Filters  
//   - Add custom topics to deny (e.g., "competitor discussion", "stock advice")
//   - Natural language definition + examples
//
// Tab 3: PII Detection
//   - Checkboxes for PII types (email, phone, SSN, credit card, etc.)
//   - Action per type: ANONYMIZE or BLOCK
//
// Tab 4: Word Filters
//   - Blocklist of specific words/phrases
//   - Import from file option
//
// Tab 5: Test
//   - Input text field
//   - "Test Guardrail" button
//   - Shows what would be blocked/anonymized
```

6. **`frontend/src/components/guardrails/ViolationLog.tsx`**
```typescript
// Violations dashboard:
// - Timeline of blocked requests
// - Filter by type (content, topic, PII, word)
// - Each entry: timestamp, type, blocked text (redacted), action taken
// - Daily violation count chart
```

### Modified Files

7. **`backend/src/app/services/code_generator.py`**
   - When Guardrails node connected: add `guardrailIdentifier` and `guardrailVersion` to Bedrock model invocation config
   - Apply guardrails via `ApplyGuardrail` API for non-Bedrock providers

8. **`backend/src/app/services/deployment.py`**
   - Add guardrail creation to deployment flow
   - Add guardrail deletion to cleanup flow

9. **`infra/stacks/main_stack.py`**
   - Add IAM permissions: `bedrock:CreateGuardrail`, `bedrock:UpdateGuardrail`, `bedrock:DeleteGuardrail`, `bedrock:ApplyGuardrail`, `bedrock:GetGuardrail`
   - Add DynamoDB table: `GuardrailViolations` (PK: deployment_id, SK: timestamp)

## Deployment Instructions

1. Add Bedrock Guardrails IAM permissions to CDK
2. Add violations DynamoDB table
3. Enhance guardrails step handler
4. Modify code generator to pass guardrail config
5. Deploy: `./scripts/deploy.sh`
6. Test: Create guardrail → deploy agent → send blocked content → verify blocked

## Testing Requirements

### Unit Tests
- Guardrail config model validation
- Code generator adds guardrail params when node connected
- Violation logging format

### Integration Tests
- Create guardrail via API → Bedrock guardrail exists
- Invoke agent with guardrail → prompt injection blocked
- PII detection → credit card number anonymized in output
- Delete deployment → guardrail cleaned up

### E2E Tests
- Deploy agent with content filters → send violent content → blocked
- Deploy agent with PII filter → response contains SSN → anonymized
- Deploy agent with topic filter → ask about blocked topic → denied
- Violation log shows all blocked attempts

## Security Requirements

- [ ] Guardrail configs stored securely (no exposure of filter rules to end users)
- [ ] Prompt attack filter enabled by DEFAULT on all new deployments
- [ ] Violation logs do not store full blocked content (privacy)
- [ ] Only deployment owner can view violations
- [ ] Guardrail cannot be bypassed by agent (applied at infrastructure level)

## Acceptance Criteria

- [ ] Guardrails configuration modal has all 4 filter types
- [ ] "Prompt Attack" detection enabled by default
- [ ] PII anonymization works (test with fake SSN, credit card)
- [ ] Topic denial works (custom topics block correctly)
- [ ] Content filter works (violence, hate speech blocked at configured level)
- [ ] Violation log shows blocked attempts with timestamp
- [ ] Test panel lets users verify guardrail before deploying
- [ ] Guardrails work with all 13 model providers (via ApplyGuardrail API)
- [ ] Deployment cleanup removes Bedrock guardrail resource
