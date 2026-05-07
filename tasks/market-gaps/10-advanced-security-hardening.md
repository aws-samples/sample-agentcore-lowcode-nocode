# Task 10: Advanced Security Hardening (RBAC, Audit Trail, DLP)

## Problem Statement

Enterprise AI agent platforms require three security pillars that we completely lack:

1. **RBAC (Role-Based Access Control)**: Our platform has Cognito authentication but **no authorization** — any authenticated user can do anything. Microsoft Copilot Studio offers per-agent RBAC, environment-level permissions, and DLP policies.

2. **Audit Trail**: No record of who did what. Enterprise compliance (SOC2, HIPAA) requires immutable audit logs of all agent operations. We have CloudWatch logs but no structured audit trail.

3. **Data Loss Prevention (DLP)**: Agents can freely output PII, proprietary data, or regulated information with no controls. Microsoft enforces DLP policies on all Copilot Studio agents.

Market evidence:
- 80% of Fortune 500 have lost control of their AI infrastructure (guptadeepak.com, 2026)
- Only 21% of enterprises have AI visibility needed for security (Akto, 2025)
- SOC2 Type II now specifically asks about AI system controls

## Proposed Solution

### 1. RBAC System
```
Roles:
├── Platform Admin    — Full control, manage users/roles, view all deployments
├── Agent Creator     — Create, deploy, test agents in their workspace
├── Agent Operator    — Deploy, monitor, rollback (no create/edit)
├── Agent Tester      — Invoke test panel only
└── Viewer            — Read-only access to configs and analytics

Permissions (resource-level):
├── workflow:create, workflow:read, workflow:update, workflow:delete
├── deployment:create, deployment:read, deployment:delete, deployment:rollback
├── trigger:create, trigger:read, trigger:delete
├── approval:approve, approval:reject
├── marketplace:publish, marketplace:install
├── analytics:read
└── admin:manage-users, admin:manage-roles, admin:approve-marketplace
```

### 2. Audit Trail
Every significant action logged with:
- WHO (user ID, email, IP address)
- WHAT (action type, resource type, resource ID)
- WHEN (timestamp, ISO 8601)
- WHERE (source IP, user agent)
- RESULT (success/failure, error detail)
- CONTEXT (before/after state for mutations)

### 3. DLP
- Detect PII in agent inputs and outputs
- Block or mask sensitive data patterns
- Configurable policies per deployment
- Alert on DLP violations

## AWS Services

- **Amazon Cognito Groups**: Role assignment
- **DynamoDB**: `AuditLog` table (immutable, append-only)
- **Amazon CloudTrail**: API-level audit (automatic with API Gateway)
- **Amazon Comprehend**: PII detection for DLP
- **Amazon Bedrock Guardrails**: PII anonymization (from Task 06)
- **SNS**: Alert on security events
- **S3 + Glacier**: Long-term audit log archival
- **KMS**: Encrypt audit logs at rest

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/rbac_models.py`**
```python
from pydantic import BaseModel
from typing import List, Optional, Dict
from enum import Enum

class Role(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    AGENT_CREATOR = "agent_creator"
    AGENT_OPERATOR = "agent_operator"
    AGENT_TESTER = "agent_tester"
    VIEWER = "viewer"

class Permission(str, Enum):
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"
    DEPLOYMENT_CREATE = "deployment:create"
    DEPLOYMENT_READ = "deployment:read"
    DEPLOYMENT_DELETE = "deployment:delete"
    DEPLOYMENT_ROLLBACK = "deployment:rollback"
    TRIGGER_CREATE = "trigger:create"
    TRIGGER_READ = "trigger:read"
    TRIGGER_DELETE = "trigger:delete"
    APPROVAL_APPROVE = "approval:approve"
    APPROVAL_REJECT = "approval:reject"
    MARKETPLACE_PUBLISH = "marketplace:publish"
    MARKETPLACE_INSTALL = "marketplace:install"
    ANALYTICS_READ = "analytics:read"
    ADMIN_MANAGE_USERS = "admin:manage-users"
    ADMIN_MANAGE_ROLES = "admin:manage-roles"

# Role → Permission mapping
ROLE_PERMISSIONS: Dict[Role, List[Permission]] = {
    Role.PLATFORM_ADMIN: list(Permission),  # All permissions
    Role.AGENT_CREATOR: [
        Permission.WORKFLOW_CREATE, Permission.WORKFLOW_READ,
        Permission.WORKFLOW_UPDATE, Permission.WORKFLOW_DELETE,
        Permission.DEPLOYMENT_CREATE, Permission.DEPLOYMENT_READ,
        Permission.DEPLOYMENT_DELETE, Permission.DEPLOYMENT_ROLLBACK,
        Permission.TRIGGER_CREATE, Permission.TRIGGER_READ, Permission.TRIGGER_DELETE,
        Permission.MARKETPLACE_PUBLISH, Permission.MARKETPLACE_INSTALL,
        Permission.ANALYTICS_READ,
    ],
    Role.AGENT_OPERATOR: [
        Permission.WORKFLOW_READ,
        Permission.DEPLOYMENT_CREATE, Permission.DEPLOYMENT_READ,
        Permission.DEPLOYMENT_DELETE, Permission.DEPLOYMENT_ROLLBACK,
        Permission.TRIGGER_CREATE, Permission.TRIGGER_READ, Permission.TRIGGER_DELETE,
        Permission.ANALYTICS_READ,
    ],
    Role.AGENT_TESTER: [
        Permission.WORKFLOW_READ, Permission.DEPLOYMENT_READ, Permission.ANALYTICS_READ,
    ],
    Role.VIEWER: [
        Permission.WORKFLOW_READ, Permission.DEPLOYMENT_READ, Permission.ANALYTICS_READ,
    ],
}
```

2. **`backend/src/app/services/rbac_service.py`**
```python
# Service that:
# - Extracts user role from Cognito JWT (custom:role claim or group membership)
# - Checks permissions before each API operation
# - Supports resource-level ownership (user can only access their own resources)
# - Admin override for platform admins
# - Caches role lookups for performance
```

3. **`backend/src/app/middleware/auth_middleware.py`**
```python
# FastAPI middleware/dependency:
# - Validates JWT token from Cognito
# - Extracts user_id, email, role
# - Injects into request context
# - Returns 403 if permission denied
# Usage: @router.get("/workflows", dependencies=[Depends(require_permission(Permission.WORKFLOW_READ))])
```

4. **`backend/src/app/services/audit_service.py`**
```python
# Audit logging service:
# - Writes structured audit events to DynamoDB
# - Fields: event_id, timestamp, user_id, user_email, action, resource_type,
#           resource_id, ip_address, user_agent, result, before_state, after_state
# - Immutable: no update/delete operations on audit table
# - Async write (don't block API responses)
# - Export to S3 for long-term retention
```

5. **`backend/src/app/services/dlp_service.py`**
```python
# DLP service:
# - Scan agent inputs for PII (regex patterns + Comprehend)
# - Scan agent outputs for PII before returning to user
# - Configurable actions: BLOCK, MASK, ALERT, LOG
# - PII types: SSN, credit card, email, phone, address, passport
# - Custom patterns (regex-based, per-deployment)
# - Integration with Bedrock Guardrails (from Task 06)
```

6. **`backend/src/app/routers/admin.py`**
```python
# Admin endpoints (platform_admin only):
# GET    /api/admin/users              - List all users with roles
# PUT    /api/admin/users/{id}/role    - Assign role to user
# GET    /api/admin/audit              - Search audit logs
# GET    /api/admin/audit/export       - Export audit logs (CSV/JSON)
# GET    /api/admin/dlp/violations     - DLP violation report
# PUT    /api/admin/dlp/policies       - Update DLP policies
# GET    /api/admin/security/overview  - Security dashboard data
```

7. **`frontend/src/pages/AdminPage.tsx`**
```typescript
// Admin panel with tabs:
// - Users: list users, assign roles, invite new users
// - Audit Log: searchable table of all actions (filterable by user, action, date)
// - DLP: violation log, policy configuration
// - Security: overview dashboard (auth attempts, blocked actions, etc.)
```

8. **`frontend/src/components/admin/AuditLogViewer.tsx`**
```typescript
// Audit log viewer:
// - Time range filter
// - User filter (dropdown)
// - Action type filter
// - Resource filter
// - Full-text search
// - Export button (CSV)
// - Each row expandable to show full before/after state
```

9. **`frontend/src/components/admin/UserManagement.tsx`**
```typescript
// User management:
// - Table: email, role, last active, deployment count
// - "Change Role" dropdown per user
// - "Invite User" button (adds to Cognito)
// - "Revoke Access" button
```

### Modified Files

10. **ALL existing routers** (`workflows.py`, `deployment.py`, `tools.py`, etc.)
    - Add `Depends(require_permission(...))` to every endpoint
    - Add audit logging to every mutation (create, update, delete)

11. **`infra/stacks/main_stack.py`**
    - Add DynamoDB table: `AuditLog` (PK: date_partition, SK: timestamp#event_id)
    - Add DynamoDB table: `DlpPolicies` (PK: deployment_id)
    - Add Cognito user groups for roles
    - Add KMS key for audit log encryption
    - Add S3 lifecycle rule for audit archival (→ Glacier after 90 days)
    - Add IAM permissions for Comprehend (PII detection)

12. **`frontend/src/App.tsx`**
    - Add `/admin` route (only visible to platform_admin)
    - Show role-based UI (hide buttons user doesn't have permission for)

## Deployment Instructions

1. Add Cognito user groups (one per role) to CDK
2. Add AuditLog and DlpPolicies DynamoDB tables
3. Add RBAC middleware to all API routes
4. Add audit logging to all mutation endpoints
5. Deploy: `./scripts/deploy.sh`
6. Assign yourself platform_admin role in Cognito
7. Test: create viewer user → verify can't create workflows → verify audit log shows denied action

## Testing Requirements

### Unit Tests
- RBAC: each role has correct permissions
- RBAC: permission check correctly allows/denies
- Audit: event format validation
- DLP: PII pattern detection (SSN, credit card, email)

### Integration Tests
- Create user with viewer role → attempt create workflow → 403
- Admin assigns creator role → attempt create workflow → 200
- All mutations appear in audit log with correct metadata
- DLP: agent output with credit card → masked in response

### E2E Tests
- Full RBAC flow: admin creates user → assigns role → user has correct access
- Audit export: admin downloads CSV → all actions present
- DLP: deploy agent → invoke with PII in response → verify masking/blocking

## Security Requirements

- [ ] Audit log table has NO delete/update permissions (append-only)
- [ ] KMS encryption on audit logs (customer-managed key)
- [ ] Audit log retention: 7 years (compliance)
- [ ] Role changes themselves are audited
- [ ] Cognito JWT validated on every request (no caching of auth decisions)
- [ ] Admin actions require MFA (Cognito advanced security)
- [ ] DLP policies cannot be disabled by non-admins
- [ ] Failed auth attempts trigger CloudWatch alarm after 5 failures

## Acceptance Criteria

- [ ] 5 distinct roles working with correct permission boundaries
- [ ] Every API mutation creates an audit log entry
- [ ] Audit log searchable by user, action, date, resource
- [ ] Audit log exportable as CSV/JSON
- [ ] DLP detects SSN, credit card, email patterns
- [ ] DLP can mask or block PII in agent responses
- [ ] Admin panel shows user management with role assignment
- [ ] Non-admin users cannot access admin endpoints
- [ ] UI hides buttons/features user doesn't have permission for
- [ ] CDK-NAG passes with new security resources
