# Task 07: Environment Promotion (Dev → Staging → Prod)

## Problem Statement

Our platform deploys to a single environment. Enterprise teams need:
- **Dev**: Rapid iteration, testing with synthetic data
- **Staging**: Production-like, integration testing, approval gates
- **Production**: Live traffic, monitoring, rollback-ready

Competitors:
- **n8n**: Environment variables per environment, deployment to different instances
- **Microsoft Copilot Studio**: Draft → Test → Published lifecycle
- **Google Vertex AI**: Endpoint traffic splitting, staged rollout
- **Dify**: Workspace separation, publish/draft modes

Our `deploy.sh` supports `ENVIRONMENT_NAME` but there's:
- No UI for promoting between environments
- No approval gates between stages
- No config difference management per environment
- No traffic shifting during production rollout

## Proposed Solution Architecture

```
┌─────────┐     ┌─────────────┐     ┌──────────┐     ┌────────────┐
│   Dev   │────▶│   Staging   │────▶│   Prod   │────▶│  Traffic   │
│ (auto)  │     │ (approval)  │     │ (canary) │     │  (100%)    │
└─────────┘     └─────────────┘     └──────────┘     └────────────┘
     │                │                    │
     ▼                ▼                    ▼
  Dev Stack      Staging Stack        Prod Stack
  (separate)     (separate)          (separate)
```

## AWS Services

- **AWS CDK**: Multi-stack deployment (one per environment)
- **CodePipeline** (optional): CI/CD orchestration
- **Lambda Aliases**: `dev`, `staging`, `prod` aliases per function
- **API Gateway Stages**: Separate stages per environment
- **SSM Parameter Store**: Environment-specific configuration
- **DynamoDB**: Promotion history and approval tracking
- **SNS**: Notifications for pending promotions

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/environment_models.py`**
```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum

class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

class PromotionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTING = "promoting"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

class EnvironmentConfig(BaseModel):
    environment: Environment
    deployment_id: str
    version: int
    model_config_overrides: Dict[str, Any] = {}  # e.g., different model in prod
    environment_variables: Dict[str, str] = {}
    traffic_percentage: int = 100  # For canary (0-100)
    auto_rollback_threshold: Optional[float] = None  # Error rate % to trigger rollback

class PromotionRequest(BaseModel):
    deployment_id: str
    source_environment: Environment
    target_environment: Environment
    version: int
    change_description: str
    requires_approval: bool = True
    canary_percentage: int = 10  # Start with 10% traffic in prod
    canary_duration_minutes: int = 30  # Monitor for 30 min before full rollout

class PromotionRecord(BaseModel):
    promotion_id: str
    deployment_id: str
    source: Environment
    target: Environment
    version: int
    status: PromotionStatus
    requested_by: str
    requested_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    completed_at: Optional[str] = None
    canary_metrics: Optional[Dict] = None  # Metrics during canary period
    rollback_reason: Optional[str] = None
```

2. **`backend/src/app/routers/environments.py`**
```python
# Endpoints:
# GET    /api/environments/{deployment_id}             - Get all environments status
# POST   /api/environments/{deployment_id}/promote     - Request promotion
# POST   /api/environments/{deployment_id}/approve     - Approve pending promotion
# POST   /api/environments/{deployment_id}/reject      - Reject pending promotion
# POST   /api/environments/{deployment_id}/rollback    - Rollback production
# GET    /api/environments/{deployment_id}/history     - Promotion history
# PUT    /api/environments/{deployment_id}/{env}/config - Update env-specific config
```

3. **`backend/src/app/services/promotion_service.py`**
```python
# Service that:
# - Validates promotion readiness (tests pass, no pending changes)
# - Creates promotion requests with approval gates
# - Executes promotion (deploy to target environment)
# - Manages canary rollout (Lambda alias weighted routing)
# - Monitors canary metrics (error rate, latency)
# - Auto-rollback if thresholds breached
# - Sends notifications for pending approvals
```

4. **`frontend/src/components/environments/EnvironmentPanel.tsx`**
```typescript
// Environment promotion UI:
// - Three-column view: Dev | Staging | Prod
// - Each column shows: version deployed, status, last deploy time
// - "Promote →" buttons between columns
// - Pending approval badges with approve/reject actions
// - Canary progress indicator (% traffic, time remaining)
// - Environment-specific config editor
```

5. **`frontend/src/components/environments/PromotionWizard.tsx`**
```typescript
// Step-by-step promotion flow:
// 1. Select source → target
// 2. Review changes (diff from current target)
// 3. Configure canary (% traffic, duration, auto-rollback threshold)
// 4. Add change description
// 5. Submit (goes to approval if staging→prod)
```

6. **`frontend/src/components/environments/CanaryMonitor.tsx`**
```typescript
// Real-time canary monitoring:
// - Traffic split visualization (pie chart: canary vs stable)
// - Live metrics: error rate, latency, token usage
// - Threshold lines on charts
// - "Promote to 100%" or "Rollback" buttons
// - Auto-rollback countdown if threshold breached
```

### Modified Files

7. **`infra/stacks/main_stack.py`**
   - Support multi-environment deployment (parameterized stack)
   - Add `Promotions` DynamoDB table
   - Lambda alias support with weighted routing
   - SSM parameters per environment

8. **`scripts/deploy.sh`**
   - Accept `ENVIRONMENT_NAME` for multi-env deploy
   - Create environment-specific resources
   - Support promoting between environments

9. **`backend/src/app/services/deployment.py`**
   - Tag deployments with environment
   - Store environment-specific config overrides

## Deployment Instructions

1. Modify CDK to support environment parameter on all resources
2. Add Promotions DynamoDB table
3. Add promotion service and routes
4. Deploy dev stack: `ENVIRONMENT_NAME=dev ./scripts/deploy.sh`
5. Deploy staging stack: `ENVIRONMENT_NAME=staging ./scripts/deploy.sh`
6. Test: Deploy to dev → promote to staging → approve → promote to prod with canary

## Testing Requirements

### Unit Tests
- Promotion state machine (valid transitions)
- Canary percentage validation (0-100)
- Auto-rollback threshold logic
- Environment config override merging

### Integration Tests
- Promote dev→staging: version appears in staging DDB
- Approve promotion: Lambda alias updated
- Canary: weighted routing configured correctly
- Auto-rollback: error rate exceeds threshold → rollback triggered

### E2E Tests
- Full promotion lifecycle: dev → staging (auto) → prod (approval + canary)
- Rollback from prod → previous version serves traffic
- Canary auto-rollback: inject errors → system auto-reverts

## Security Requirements

- [ ] Prod promotions REQUIRE approval from authorized users
- [ ] Canary rollback is automatic (no human needed in emergency)
- [ ] Environment configs don't leak prod secrets to dev
- [ ] Promotion audit trail (who approved, when, why)
- [ ] Separate IAM roles per environment (dev can't touch prod resources)
- [ ] Staging uses synthetic/anonymized data (not prod data)

## Acceptance Criteria

- [ ] Three environments visible in UI (Dev, Staging, Prod)
- [ ] One-click promote from Dev → Staging
- [ ] Staging → Prod requires approval
- [ ] Canary rollout starts at configured % (default 10%)
- [ ] Auto-rollback triggers when error rate > threshold
- [ ] Promotion history shows full audit trail
- [ ] Environment-specific model configs supported (cheaper model in dev)
- [ ] Each environment has isolated resources (separate DDB tables, Lambdas)
