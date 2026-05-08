# Task 13: AWS Agent Registry — Full Integration

## Problem Statement

**AWS Agent Registry** (preview April 2026) is a fully managed catalog and discovery service for agents, tools, MCP servers, agent skills, and custom resources. Our project has partially-built registry components but they're backed by custom DynamoDB tables — we should USE THE MANAGED SERVICE instead.

**What the managed registry gives us:**
- Centralized catalog with structured metadata records
- Native MCP and A2A protocol support (auto-discovery from endpoints)
- Hybrid search (keyword + semantic — "payment processing" finds "billing")
- Built-in approval workflows (draft → pending → published)
- Accessible as an MCP server (Claude Code and Kiro can query it!)
- OAuth-based access for custom discovery UIs
- IAM-based governance (who can publish/discover)
- Lifecycle management (development → deployed → retired)
- CloudTrail integration for audit
- Cross-registry federation (future)

**Current state in project:**
- `backend/src/app/services/registry_client.py` — Partially built client
- `backend/src/app/services/registry_descriptor_builder.py` — Builds descriptor metadata
- `backend/src/app/services/registry_publish_input.py` — Publish input builder
- `backend/src/app/services/registry_index_store.py` — Custom index (REPLACE with managed)
- `backend/src/app/services/registry_authz.py` — Custom auth (REPLACE with managed IAM)
- `frontend/src/components/registry/` — PublishWizard, AdminApprovalTable, RecordCard, RecordDetailDrawer, RegistryPicker, InstallConfigModal

## API Surface

```python
# Registry Management
create_registry(registryName, description, authorizationConfig, approvalConfig)
get_registry(registryName)
list_registries()
delete_registry(registryName)

# Record Management
create_registry_record(
    registryName=...,
    recordName=...,
    descriptorType="MCP_SERVER" | "A2A_AGENT" | "AGENT_SKILL" | "CUSTOM",
    descriptor={...},  # Type-specific metadata
    description=...,
    metadata={...}  # Custom key-value pairs
)
# Auto-sync from endpoint:
create_registry_record(
    registryName=...,
    recordName=...,
    descriptorType="MCP_SERVER",
    endpoint={"url": "https://...", "credentials": {...}}
    # Registry auto-fetches metadata from the MCP endpoint!
)
update_registry_record(registryName, recordName, ...)
get_registry_record(registryName, recordName)
list_registry_records(registryName, status="PUBLISHED" | "PENDING" | "DRAFT")
delete_registry_record(registryName, recordName)

# Approval Workflow
approve_registry_record(registryName, recordName)
reject_registry_record(registryName, recordName, reason)

# Search (hybrid keyword + semantic)
search_registry_records(registryName, query="...", filters={...})
```

## Files to Create/Modify

### Modified Backend Files (Replace Custom with Managed)

1. **`backend/src/app/services/registry_client.py`** — REWRITE
```python
# Replace custom DynamoDB-backed registry with managed AWS Agent Registry APIs:
# - create_registry() — Create org-level registry (one-time setup)
# - publish_record() — Publish agent/tool/MCP server to registry
# - search_records() — Hybrid search with keyword + semantic
# - approve/reject_record() — Admin approval workflow
# - auto_sync_from_endpoint() — Point at MCP/A2A URL, registry pulls metadata
# - get_record_with_install_config() — Fetch record + invocation details for install
```

2. **`backend/src/app/services/registry_index_store.py`** — DELETE (replaced by managed search)

3. **`backend/src/app/routers/registry.py`** — UPDATE
```python
# Endpoints mapping to managed registry:
# POST   /api/registry/setup                    - Create registry (admin, one-time)
# POST   /api/registry/records                  - Publish record (auto/manual)
# GET    /api/registry/records                  - List records (with status filter)
# GET    /api/registry/records/{name}           - Get record details
# PUT    /api/registry/records/{name}           - Update record
# DELETE /api/registry/records/{name}           - Delete record
# POST   /api/registry/records/{name}/approve   - Approve (admin)
# POST   /api/registry/records/{name}/reject    - Reject (admin)
# GET    /api/registry/search?q=...             - Search (hybrid)
# POST   /api/registry/sync                     - Sync from MCP/A2A endpoint
# GET    /api/registry/mcp-endpoint             - Get registry's own MCP server URL
```

### Modified Frontend Files

4. **`frontend/src/components/registry/PublishWizard.tsx`** — UPDATE
```typescript
// Simplified to use managed registry:
// Step 1: Select what to publish (current deployment, tool, MCP server)
// Step 2: Choose descriptor type (MCP_SERVER, A2A_AGENT, AGENT_SKILL, CUSTOM)
// Step 3: Auto-populate metadata from deployment config OR enter manually
// Step 4: Add custom metadata (team, cost center, compliance status)
// Step 5: Submit → goes to PENDING_APPROVAL status
```

5. **`frontend/src/components/registry/RegistryBrowser.tsx`** — NEW
```typescript
// Full registry browser (replaces marketplace concept):
// - Search bar with semantic search ("find tools for customer support")
// - Filter by: type (MCP Server, Agent, Skill), status, owner
// - Results grid: cards with name, description, type badge, approval status
// - Click → detail drawer with install instructions
// - "Install to Canvas" button → adds node to current workflow
```

6. **`frontend/src/components/registry/AutoSyncPanel.tsx`** — NEW
```typescript
// For MCP/A2A endpoint auto-registration:
// - Input: endpoint URL
// - Optional: credentials (OAuth, API key)
// - "Sync" button → registry fetches metadata automatically
// - Preview what will be registered
// - Confirm → creates record
```

7. **`frontend/src/components/registry/AdminApprovalTable.tsx`** — UPDATE
```typescript
// Now backed by managed registry approval workflow:
// - List pending records from registry API
// - Each row: name, type, publisher, submitted date
// - Approve/Reject buttons with reason field
// - Auto-refresh when new submissions arrive
```

### New Files

8. **`backend/src/app/services/registry_setup.py`**
```python
# One-time registry setup service:
# - Creates the organization's registry (with chosen auth config)
# - Configures approval policy (auto-approve for admins, require approval for others)
# - Sets up IAM policies for publish/discover access
# - Generates MCP server URL for the registry
# - Stores registry ARN in SSM Parameter Store for other services
```

9. **`backend/src/app/services/registry_auto_publisher.py`**
```python
# Auto-publish agents on successful deployment:
# - After deployment completes → auto-create registry record
# - Descriptor type based on deployment: 
#   - Harness → A2A_AGENT descriptor
#   - Runtime + Gateway → MCP_SERVER descriptor
#   - Tool → AGENT_SKILL descriptor
# - Record includes: invoke endpoint, auth config, capabilities, owner
# - Status: DRAFT (user must explicitly publish to make discoverable)
```

### Modified Files

10. **`infra/stacks/main_stack.py`**
    - Add IAM permissions for Agent Registry APIs (`bedrock-agentcore-control:CreateRegistry`, `CreateRegistryRecord`, `SearchRegistryRecords`, etc.)
    - Add SSM parameter for registry ARN
    - Add IAM for OAuth-based registry access (for external consumers)

11. **`backend/src/app/services/deployment.py`**
    - After successful deployment: call `registry_auto_publisher` to create draft record
    - On delete: mark registry record as "retired"

12. **`frontend/src/components/palette/ComponentPalette.tsx`**
    - Add "From Registry" section that shows installed/available items from the registry
    - "Browse Registry" button → opens RegistryBrowser

## Deployment Instructions

1. Add Agent Registry IAM permissions to CDK
2. Add registry setup route (creates registry on first call)
3. Replace custom index/search with managed APIs
4. Add auto-publish after deployment
5. Deploy: `./scripts/deploy.sh`
6. Test: Deploy agent → verify record appears in registry → search → install

## Testing Requirements

### Unit Tests
- Descriptor builder creates correct shapes per type
- Auto-publish generates correct metadata from deployment
- Search query formatting and result parsing

### Integration Tests
- Create registry → create record → search finds it
- Publish wizard → record in PENDING → admin approves → discoverable
- Auto-sync from MCP endpoint → metadata populated correctly
- Delete deployment → record marked as retired

### E2E Tests
- Deploy agent → auto-registers in registry → another user searches → finds it → installs
- Publish custom tool → approval → shows in palette → drag to canvas → works

## Security Requirements

- [ ] Registry creation requires admin IAM permissions
- [ ] Publish requires authenticated user
- [ ] Search respects IAM policies (users see only approved records)
- [ ] Endpoint credentials stored securely (not in registry metadata)
- [ ] Auto-sync validates endpoint URLs (HTTPS only, no internal IPs)
- [ ] Admin approval required before records become discoverable

## Acceptance Criteria

- [ ] Organization registry created via admin setup
- [ ] Agents auto-register as draft records on deployment
- [ ] Publish wizard submits records for approval
- [ ] Admin can approve/reject from the UI
- [ ] Search finds records by name, description, and semantic query
- [ ] "Install to Canvas" adds registry items to current workflow
- [ ] Auto-sync from MCP endpoint populates metadata automatically
- [ ] Registry accessible as MCP server (verifiable via curl)
- [ ] Custom DynamoDB index code removed (using managed search)
- [ ] CloudTrail logs all registry operations
