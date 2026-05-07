# Task 09: Agent & Tool Marketplace

## Problem Statement

- **n8n**: 1,100+ community-contributed integrations (nodes)
- **Dify**: Template marketplace with community contributions
- **Microsoft Copilot Studio**: 1,400+ Power Platform connectors + Teams App Store
- **Google Vertex AI**: Partner-built agents marketplace (Adobe, Atlassian, Salesforce, etc.)

Our platform has a **partially-built registry** (PublishWizard, AdminApprovalTable, RecordCard, InstallConfigModal) but it's incomplete. Users cannot:
- Discover and install community-built agents
- Share their agents with other teams
- Browse reusable tools/MCP servers
- Rate or review shared content

The agent marketplace is emerging as the "App Store moment" for AI — Deloitte WSJ (2025) calls it "the equivalent of an app store where users can subscribe to deployable agentic AI."

## Proposed Solution

Complete the registry into a full marketplace with:
1. **Publish**: Package and publish agents/tools to the marketplace
2. **Discover**: Browse, search, filter by category/rating/use-case
3. **Install**: One-click install into your canvas
4. **Review**: Rate, review, and report published items
5. **Govern**: Admin approval workflow before items are visible

## AWS Services

- **DynamoDB**: `MarketplaceItems` table (published agents/tools)
- **S3**: Package storage (agent bundles, tool code, icons)
- **CloudFront**: CDN for marketplace assets
- **Cognito**: Publisher identity
- **Lambda**: Marketplace API (search, install, publish)
- **OpenSearch Serverless** (optional): Full-text search for marketplace

## Files to Create/Modify

### New Files

1. **`backend/src/app/models/marketplace_models.py`**
```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum

class ItemType(str, Enum):
    AGENT_TEMPLATE = "agent_template"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    WORKFLOW = "workflow"
    KNOWLEDGE_BASE = "knowledge_base"

class ItemStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"

class MarketplaceItem(BaseModel):
    item_id: str
    item_type: ItemType
    name: str
    display_name: str
    description: str
    long_description: Optional[str] = None  # Markdown
    version: str = "1.0.0"
    author: str
    author_id: str
    icon_url: Optional[str] = None
    categories: List[str] = []  # ["productivity", "customer-support", "data-analysis"]
    tags: List[str] = []
    status: ItemStatus = ItemStatus.DRAFT
    # Content
    workflow_json: Optional[Dict] = None  # For templates
    tool_code: Optional[str] = None       # For tools
    requirements: List[str] = []          # AWS services needed
    model_requirements: List[str] = []    # Models needed
    # Metrics
    install_count: int = 0
    rating_average: float = 0.0
    rating_count: int = 0
    # Metadata
    created_at: str = ""
    updated_at: str = ""
    published_at: Optional[str] = None
    # Install config
    configuration_schema: Optional[Dict] = None  # JSON Schema for install-time config
    
class ReviewEntry(BaseModel):
    review_id: str
    item_id: str
    user_id: str
    rating: int  # 1-5
    title: str
    body: str
    created_at: str
    helpful_count: int = 0

class PublishRequest(BaseModel):
    item_type: ItemType
    name: str
    display_name: str
    description: str
    long_description: Optional[str] = None
    categories: List[str]
    tags: List[str] = []
    workflow_json: Optional[Dict] = None
    tool_code: Optional[str] = None
    configuration_schema: Optional[Dict] = None
```

2. **`backend/src/app/routers/marketplace.py`**
```python
# Endpoints:
# GET    /api/marketplace/items              - Browse/search marketplace
# GET    /api/marketplace/items/{id}         - Get item details
# POST   /api/marketplace/items              - Publish new item
# PUT    /api/marketplace/items/{id}         - Update item
# DELETE /api/marketplace/items/{id}         - Unpublish item
# POST   /api/marketplace/items/{id}/install - Install into workspace
# GET    /api/marketplace/items/{id}/reviews - Get reviews
# POST   /api/marketplace/items/{id}/reviews - Add review
# GET    /api/marketplace/categories         - List categories
# GET    /api/marketplace/featured           - Featured/trending items
# POST   /api/marketplace/items/{id}/report  - Report inappropriate item
# --- Admin ---
# GET    /api/marketplace/admin/pending      - Items pending review
# POST   /api/marketplace/admin/{id}/approve - Approve item
# POST   /api/marketplace/admin/{id}/reject  - Reject item
```

3. **`backend/src/app/services/marketplace_service.py`**
```python
# Service that:
# - Manages item lifecycle (draft → review → published)
# - Packages agent/tool for distribution
# - Validates published items (security scan, schema validation)
# - Handles installation (clone workflow, configure, test)
# - Computes trending/featured rankings
# - Manages reviews and ratings
```

4. **`frontend/src/pages/MarketplacePage.tsx`**
```typescript
// Full marketplace page:
// - Hero banner with search bar
// - Category navigation (sidebar or top tabs)
// - Featured/trending section
// - Grid of item cards (icon, name, description, rating, installs)
// - Filter: type (agent/tool/workflow), rating, recently updated
// - Sort: popular, newest, highest rated
```

5. **`frontend/src/components/marketplace/ItemCard.tsx`**
```typescript
// Compact card:
// - Icon + name
// - Short description (2 lines max)
// - Author name
// - Star rating + install count
// - Item type badge
// - "Install" button
```

6. **`frontend/src/components/marketplace/ItemDetail.tsx`**
```typescript
// Full item page:
// - Header: icon, name, author, type badge, version
// - Long description (markdown rendered)
// - Screenshots/preview of canvas layout
// - "Install" button (opens config modal if schema defined)
// - Reviews section with star distribution
// - "Write Review" form
// - Related items
// - Requirements: list of AWS services/models needed
```

7. **`frontend/src/components/marketplace/PublishFlow.tsx`**
```typescript
// Multi-step publish wizard:
// 1. Select what to publish (current workflow, specific tool, template)
// 2. Fill metadata (name, description, categories, icon)
// 3. Configure installation schema (what users configure on install)
// 4. Preview how it will appear in marketplace
// 5. Submit for review
```

### Modified Files

8. **`infra/stacks/main_stack.py`**
   - Add DynamoDB tables: `MarketplaceItems`, `MarketplaceReviews`
   - Add S3 bucket for marketplace assets (icons, packages)
   - Add marketplace Lambda handler
   - Add CloudFront behavior for marketplace assets

9. **`frontend/src/App.tsx`** (or router)
   - Add `/marketplace` route
   - Add "Marketplace" nav item with badge (new items count)

10. **`frontend/src/components/palette/ComponentPalette.tsx`**
    - Add "From Marketplace" section showing installed items
    - "Browse More" link to marketplace page

## Deployment Instructions

1. Add marketplace DynamoDB tables and S3 bucket to CDK
2. Add marketplace API routes
3. Seed with initial items (convert existing 7 templates to marketplace items)
4. Deploy: `./scripts/deploy.sh`
5. Test: Browse marketplace → install template → verify appears in canvas

## Testing Requirements

### Unit Tests
- Item model validation
- Search/filter logic
- Rating calculation (weighted average)
- Security scan for published code

### Integration Tests
- Publish item → pending review → approve → visible in marketplace
- Install item → workflow created in user's workspace
- Search by keyword → relevant results returned
- Rating: submit review → average updated

### E2E Tests
- Full publish flow: create agent → publish → review → approve → another user installs
- Marketplace search finds items by name, description, category
- Installation configures item correctly with user-provided values

## Security Requirements

- [ ] Published code scanned for malicious patterns (no `exec`, no network calls to non-AWS)
- [ ] Admin approval REQUIRED before items visible publicly
- [ ] Publishers verified (Cognito identity)
- [ ] Install doesn't grant excessive permissions (sandboxed)
- [ ] Reviews moderated (no spam, no offensive content)
- [ ] Package integrity: SHA-256 hash verified on install
- [ ] Rate limiting on publish/review endpoints

## Acceptance Criteria

- [ ] Marketplace page shows browsable grid of items
- [ ] Search finds items by name, description, tags
- [ ] Filter by type, category, rating works
- [ ] One-click install adds item to user's workspace
- [ ] Publish wizard packages current workflow for sharing
- [ ] Admin approval required before publishing
- [ ] Reviews and ratings displayed on item detail page
- [ ] Existing 7 templates migrated to marketplace format
- [ ] Install count increments on each installation
