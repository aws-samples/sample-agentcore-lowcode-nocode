# Task 12: AgentCore Optimization — Quality Loop Integration

## Problem Statement

**AgentCore Optimization** (preview May 4, 2026) closes the "observe → evaluate → improve" loop that enterprises need but NOBODY in the market offers natively:
- Generates recommendations from production traces (not guesswork)
- Validates with batch evaluations (offline regression testing)
- Confirms with A/B testing on live traffic (statistical significance)
- Auto-rollback if metrics degrade

This is a **massive differentiator** — no competitor (n8n, Flowise, Langflow, Dify) has automated agent quality optimization. Microsoft Copilot Studio has basic analytics but no recommendation engine. Google has evaluations but no closed-loop optimization.

## Key Concepts

1. **Configuration Bundles**: Versioned, immutable snapshots of agent config (system prompt, model ID, tool descriptions). Components keyed by runtime ARN. Versions form a chain via `parentVersionIds` (like git commits). Branches organize lineage (e.g., `mainline`, `experiment-1`).

2. **Recommendations**: Point at CloudWatch Log group → Optimization reads traces → generates optimized system prompt or tool descriptions for a specified evaluator. Writes result as a new bundle version.

3. **Batch Evaluation**: Run agent against curated dataset using new bundle. Compare aggregate scores to baseline. Wire into CI/CD.

4. **A/B Testing**: Gateway splits live traffic between two variants at configured percentage. Online evaluation scores every session. Reports confidence intervals + p-values. Promote winner or rollback.

## API Surface

```python
# Configuration Bundles
create_configuration_bundle(bundleName, components=[{resourceArn, configuration}])
update_configuration_bundle(bundleId, components=[...])  # Creates new version
get_configuration_bundle(bundleId, versionId=None)  # Latest if no version
list_configuration_bundles()
delete_configuration_bundle(bundleId)

# Recommendations  
create_recommendation(
    bundleId=...,
    logGroupArn=...,           # CloudWatch Log group with traces
    evaluatorId=...,           # Built-in or custom evaluator to optimize for
    targetField="systemPrompt" # or "toolDescriptions"
)
get_recommendation(recommendationId)

# A/B Tests (via Gateway)
create_ab_test(
    gatewayId=...,
    controlVariant={bundleVersionId: "...", weight: 90},
    treatmentVariant={bundleVersionId: "...", weight: 10},
    evaluatorIds=[...],
    durationMinutes=1440  # 24 hours
)
get_ab_test_results(testId)  # confidence intervals, p-values
promote_variant(testId, variantId)  # Set winner as default
```

## Files to Create/Modify

### New Backend Files

1. **`backend/src/app/models/optimization_models.py`**
```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum

class BundleComponent(BaseModel):
    resource_arn: str
    configuration: Dict[str, Any]  # {systemPrompt, modelId, toolDescriptions, ...}

class ConfigurationBundle(BaseModel):
    bundle_id: str
    bundle_name: str
    version_id: str
    parent_version_ids: List[str] = []
    branch: str = "mainline"
    components: List[BundleComponent]
    created_at: str = ""

class RecommendationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Recommendation(BaseModel):
    recommendation_id: str
    bundle_id: str
    status: RecommendationStatus
    target_field: str  # "systemPrompt" or "toolDescriptions"
    evaluator_id: str
    original_value: Optional[str] = None
    recommended_value: Optional[str] = None
    improvement_rationale: Optional[str] = None
    new_bundle_version_id: Optional[str] = None
    created_at: str = ""

class ABTestVariant(BaseModel):
    variant_id: str
    bundle_version_id: str
    weight: int  # 0-100 traffic percentage
    
class ABTestStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"

class ABTest(BaseModel):
    test_id: str
    gateway_id: str
    control: ABTestVariant
    treatment: ABTestVariant
    evaluator_ids: List[str]
    status: ABTestStatus
    duration_minutes: int
    results: Optional[Dict] = None  # confidence intervals, p-values
    winner: Optional[str] = None
    created_at: str = ""
```

2. **`backend/src/app/services/optimization_service.py`**
```python
# Service wrapping AgentCore Optimization APIs:
# - Create/manage configuration bundles
# - Generate recommendations from production traces
# - Run batch evaluations against bundles
# - Create and manage A/B tests via Gateway
# - Promote winning variants
# - Rollback to previous bundle versions
```

3. **`backend/src/app/routers/optimization.py`**
```python
# Endpoints:
# --- Configuration Bundles ---
# POST   /api/optimization/bundles                    - Create bundle
# GET    /api/optimization/bundles                    - List bundles
# GET    /api/optimization/bundles/{id}               - Get bundle (latest version)
# GET    /api/optimization/bundles/{id}/versions      - List versions
# PUT    /api/optimization/bundles/{id}               - Update (creates new version)
# DELETE /api/optimization/bundles/{id}               - Delete bundle
#
# --- Recommendations ---
# POST   /api/optimization/recommendations            - Generate recommendation
# GET    /api/optimization/recommendations/{id}       - Get recommendation status/result
# POST   /api/optimization/recommendations/{id}/apply - Apply recommendation (create new version)
#
# --- A/B Testing ---
# POST   /api/optimization/ab-tests                   - Start A/B test
# GET    /api/optimization/ab-tests/{id}              - Get test status + results
# POST   /api/optimization/ab-tests/{id}/promote      - Promote winner
# POST   /api/optimization/ab-tests/{id}/rollback     - Rollback (stop test)
# GET    /api/optimization/ab-tests                   - List active tests
#
# --- Batch Evaluation ---
# POST   /api/optimization/evaluations                - Run batch evaluation
# GET    /api/optimization/evaluations/{id}           - Get evaluation results
```

### New Frontend Files

4. **`frontend/src/pages/OptimizationPage.tsx`**
```typescript
// Full optimization dashboard with sections:
// 1. Configuration Bundles — version tree visualization, diff between versions
// 2. Recommendations — generate, review, apply/reject
// 3. A/B Tests — active tests with live metrics, promote/rollback buttons
// 4. Evaluation History — batch evaluation results over time
```

5. **`frontend/src/components/optimization/BundleManager.tsx`**
```typescript
// Bundle version management:
// - Tree/timeline view of versions (like git log)
// - Each version shows: config diff from parent, creation timestamp, who created
// - "Create from current" button (snapshot current agent config)
// - "Restore version" button (revert to previous)
// - Branch selector (mainline, experiment-1, etc.)
```

6. **`frontend/src/components/optimization/RecommendationPanel.tsx`**
```typescript
// Recommendation workflow:
// - "Generate Recommendation" button with evaluator selector
// - Shows: original prompt vs recommended prompt (diff view)
// - Improvement rationale from the service
// - "Apply" button (creates new bundle version)
// - "Reject" button (discards)
// - "Run Batch Eval First" button (validate before applying)
```

7. **`frontend/src/components/optimization/ABTestPanel.tsx`**
```typescript
// A/B test management:
// - Active test card: control vs treatment, traffic split, time remaining
// - Live metrics: evaluation scores per variant with confidence intervals
// - Statistical significance indicator (green = significant, gray = needs more data)
// - "Promote Treatment" and "Rollback" buttons
// - History of past tests with results
```

### Modified Files

8. **`infra/stacks/main_stack.py`**
   - Add IAM permissions for AgentCore Optimization APIs
   - Add IAM for CloudWatch Logs read (for recommendations)

9. **`frontend/src/App.tsx`**
   - Add `/optimization` route
   - Add "Optimization" nav item

10. **`backend/src/app/main.py`**
    - Register optimization router

## Deployment Instructions

1. Add Optimization IAM permissions to CDK
2. Add optimization routes and service
3. Add frontend optimization page
4. Deploy: `./scripts/deploy.sh`
5. Test: Deploy agent → invoke 20+ times → generate recommendation → review → run A/B test

## Testing Requirements

### Unit Tests
- Bundle model validation (version chain, branch naming)
- Recommendation status transitions
- A/B test weight validation (control + treatment = 100)

### Integration Tests
- Create bundle → update → verify version chain
- Generate recommendation → poll until complete → verify output
- Create A/B test → verify gateway traffic split configured
- Promote variant → verify default updated

### E2E Tests
- Full loop: deploy agent → invoke → create bundle → generate recommendation → batch eval → A/B test → promote

## Security Requirements

- [ ] Only deployment owner can create/manage bundles for their agents
- [ ] Recommendations don't expose raw trace content in the frontend
- [ ] A/B test promotion is audited (who promoted, when, test results)
- [ ] Bundle version history is immutable (no delete of individual versions)
- [ ] IAM scoped to specific agent resources (not all optimization APIs)

## Acceptance Criteria

- [ ] Configuration bundles can be created from current agent config
- [ ] Version history shows all config changes over time
- [ ] Recommendations generate improved prompts from production traces
- [ ] Diff view clearly shows original vs recommended
- [ ] A/B tests split traffic at configured percentage
- [ ] Test results show confidence intervals and p-values
- [ ] "Promote" switches default to winning variant
- [ ] "Rollback" reverts to previous version immediately
- [ ] Batch evaluation runs against curated test dataset
- [ ] All evaluator scores visible in dashboard (goal success, helpfulness, safety)
