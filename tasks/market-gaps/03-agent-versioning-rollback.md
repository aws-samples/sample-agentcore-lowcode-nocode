# Task 03: Agent Versioning & Rollback

## Problem Statement

**92% of Fortune 500 companies have formal rollback procedures** (lowcodenocode.org, 2025). Yet our platform has **zero versioning support**:
- No way to track changes to agent configurations
- No way to roll back a bad deployment
- No diff between versions
- No deployment history beyond "last active deployment"

Competitors:
- **n8n**: Full workflow versioning, execution history, version diff
- **Dify**: Prompt versioning, model version tracking, publish/draft modes
- **Microsoft Copilot Studio**: Draft/Published states, version history, rollback
- **Google Vertex AI**: Model versioning, endpoint traffic splitting, rollback

Key pain point: When a deployed agent starts behaving badly (model regression, prompt drift, tool failure), there's no way to instantly revert to a known-good version.

## Proposed Solution Architecture

```
┌─────────────────────────────────────────────────────┐
│                 DynamoDB: AgentVersions              │
├─────────────────────────────────────────────────────┤
│ PK: deployment_id                                    │
│ SK: version_number (v1, v2, v3...)                   │
│ Attributes:                                          │
│   - workflow_snapshot (full canvas JSON)              │
│   - agent_code_hash                                  │
│   - model_config (provider, model_id, params)        │
│   - tools_config (list of tools with versions)       │
│   - system_prompt                                    │
│   - deployment_timestamp                             │
│   - deployed_by                                      │
│   - change_description                               │
│   - status (active/rolled-back/archived)             │
│   - lambda_version_arn                               │
└─────────────────────────────────────────────────────┘
```

## AWS Services

- **DynamoDB**: `AgentVersions` table (version history)
- **Lambda Versions & Aliases**: Immutable code snapshots with alias routing
- **S3**: Version artifact storage (full deployment bundles)
- **CloudWatch**: Per-version metrics for comparison

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/version_models.py`**
```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class AgentVersion(BaseModel):
    deployment_id: str
    version: int
    workflow_snapshot: Dict[str, Any]  # Full canvas state
    agent_code: str                    # Generated Python code
    agent_code_hash: str               # SHA-256 for quick comparison
    model_config: Dict[str, Any]       # Provider, model ID, temperature, etc.
    tools_config: List[Dict[str, Any]] # Tool schemas and versions
    system_prompt: str
    memory_config: Optional[Dict] = None
    policy_config: Optional[Dict] = None
    knowledge_base_config: Optional[Dict] = None
    lambda_version_arn: Optional[str] = None
    change_description: str = ""
    deployed_by: str = ""
    deployed_at: str = ""
    status: str = "active"  # active, rolled-back, archived
    metrics_snapshot: Optional[Dict] = None  # Performance at time of rollback

class VersionDiff(BaseModel):
    deployment_id: str
    from_version: int
    to_version: int
    changes: List[Dict[str, Any]]  # [{field, old_value, new_value}]
    
class RollbackRequest(BaseModel):
    deployment_id: str
    target_version: int
    reason: str
```

2. **`backend/src/app/routers/versions.py`**
```python
# Endpoints:
# GET    /api/deployments/{id}/versions           - List all versions
# GET    /api/deployments/{id}/versions/{v}       - Get specific version
# GET    /api/deployments/{id}/versions/diff?from=1&to=2 - Diff two versions
# POST   /api/deployments/{id}/versions/rollback  - Rollback to version
# GET    /api/deployments/{id}/versions/active     - Get currently active version
```

3. **`backend/src/app/services/version_manager.py`**
```python
# Service that:
# - Captures full state snapshot before each deployment
# - Assigns incremental version numbers
# - Computes diffs between versions
# - Executes rollback (re-deploy previous version's code via Lambda alias)
# - Publishes Lambda versions and updates aliases
# - Tracks which version is "active"
```

4. **`frontend/src/components/versions/VersionHistory.tsx`**
```typescript
// Version history panel showing:
// - Timeline of all versions with timestamps
// - Each version: who deployed, change description, status badge
// - "Rollback" button on each non-active version
// - "Compare" button to diff any two versions
// - Active version highlighted in green
```

5. **`frontend/src/components/versions/VersionDiff.tsx`**
```typescript
// Side-by-side diff view showing:
// - System prompt changes (text diff)
// - Model configuration changes
// - Tool additions/removals
// - Canvas layout changes (visual diff)
// - Code changes (syntax-highlighted diff)
```

6. **`frontend/src/components/versions/RollbackModal.tsx`**
```typescript
// Confirmation modal:
// - Shows what will change (diff from current to target)
// - Requires reason text
// - "Rollback" button with loading state
// - Success/failure feedback
```

### Modified Files

7. **`backend/src/app/services/deployment.py`**
   - Before deploying: create version snapshot of current state
   - After deploying: publish Lambda version, update alias
   - Store version in DynamoDB

8. **`backend/src/app/step_handlers/runtime_launch_step.py`**
   - After Lambda deploy: publish version, create/update alias
   - Store `lambda_version_arn` in deployment state

9. **`infra/stacks/main_stack.py`**
   - Add DynamoDB table: `AgentVersions` (PK: deployment_id, SK: version)
   - Add S3 prefix for version artifacts
   - Lambda alias management permissions

10. **`frontend/src/components/deploy/DeployPanel.tsx`**
    - Add "Versions" tab showing history
    - Show current version number in deployment status
    - "Rollback" quick action in deployment header

## Deployment Instructions

1. Add AgentVersions DynamoDB table to CDK
2. Modify deployment service to create snapshots
3. Add Lambda alias management (use `$LATEST` alias for active version)
4. Deploy with `./scripts/deploy.sh`
5. Test: Deploy agent → modify → re-deploy → verify v1 and v2 exist → rollback to v1

## Testing Requirements

### Unit Tests
- Version snapshot capture (all fields populated)
- Diff computation (detect prompt, model, tool changes)
- Rollback request validation
- Version number auto-increment

### Integration Tests
- Deploy → snapshot created in DDB with correct hash
- Deploy v1 → Deploy v2 → Diff shows changes
- Rollback: v2 active → rollback to v1 → Lambda alias points to v1
- Rollback with active triggers (triggers should use alias)

### E2E Tests
- Full cycle: deploy v1 → test → deploy v2 → test → rollback → test v1 behavior
- Version history displays correctly in UI
- Diff view shows meaningful changes

## Security Requirements

- [ ] Only deployment owner can rollback
- [ ] Rollback audit trail (who, when, why, from/to versions)
- [ ] Version snapshots don't store secrets (only references)
- [ ] Lambda versions are immutable (AWS guarantees this)
- [ ] S3 version artifacts encrypted at rest (SSE-S3)

## Acceptance Criteria

- [ ] Every deployment auto-creates a version snapshot
- [ ] Version history shows all past deployments with metadata
- [ ] Diff view clearly shows what changed between versions
- [ ] Rollback instantly switches to previous version (< 5 seconds)
- [ ] After rollback, agent behavior matches the target version
- [ ] Version numbers are sequential and never reused
- [ ] "Active version" badge clearly visible in UI
- [ ] Rollback reason is recorded and visible in history
