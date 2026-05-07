# Task 08: CLI Tool & Programmatic SDK

## Problem Statement

Our platform is **UI-only** — there's no way to:
- Deploy agents from CI/CD pipelines (GitHub Actions, CodePipeline)
- Script agent creation for batch operations
- Integrate with existing development workflows
- Manage agents headlessly in server environments

Competitors:
- **n8n**: Full CLI (`n8n execute`, `n8n export`, `n8n import`), REST API for everything
- **Botpress**: `bp` CLI for project scaffolding, deployment, and testing
- **Dify**: Complete REST API, Python SDK
- **Microsoft Copilot Studio**: Power Platform CLI, Azure CLI extensions
- **Google Vertex AI**: `gcloud` CLI, Python/Go/Java SDKs, Terraform provider

## Proposed Solution

Build a Python CLI (`agentcore-cli`) and SDK (`agentcore-sdk`) that mirrors all UI capabilities.

## Files to Create/Modify

### New Files: CLI

1. **`cli/setup.py`** (or `pyproject.toml`)
```python
# Package: agentcore-cli
# Entry point: `agentcore` command
# Dependencies: click, httpx, rich, pyyaml
```

2. **`cli/agentcore_cli/main.py`**
```python
import click

@click.group()
@click.option('--api-url', envvar='AGENTCORE_API_URL', help='Platform API URL')
@click.option('--token', envvar='AGENTCORE_TOKEN', help='Auth token')
@click.pass_context
def cli(ctx, api_url, token):
    """AgentCore CLI - Manage AI agents from the command line."""
    ctx.obj = {"api_url": api_url, "token": token}

# --- Workflow Commands ---
@cli.group()
def workflow():
    """Manage workflows (agent configurations)."""

@workflow.command("list")
def workflow_list(): ...

@workflow.command("get")
@click.argument("workflow_id")
def workflow_get(workflow_id): ...

@workflow.command("create")
@click.option("--file", "-f", help="YAML/JSON workflow definition")
def workflow_create(file): ...

@workflow.command("export")
@click.argument("workflow_id")
@click.option("--format", type=click.Choice(["json", "yaml", "cfn"]))
def workflow_export(workflow_id, format): ...

@workflow.command("import")
@click.argument("file")
def workflow_import(file): ...

# --- Deployment Commands ---
@cli.group()
def deploy():
    """Deploy and manage agent deployments."""

@deploy.command("create")
@click.argument("workflow_id")
@click.option("--env", default="dev", help="Target environment")
@click.option("--wait/--no-wait", default=True)
def deploy_create(workflow_id, env, wait): ...

@deploy.command("status")
@click.argument("deployment_id")
def deploy_status(deployment_id): ...

@deploy.command("delete")
@click.argument("deployment_id")
def deploy_delete(deployment_id): ...

@deploy.command("rollback")
@click.argument("deployment_id")
@click.option("--version", type=int, required=True)
def deploy_rollback(deployment_id, version): ...

# --- Test Commands ---
@cli.group()
def test():
    """Test deployed agents."""

@test.command("invoke")
@click.argument("deployment_id")
@click.option("--message", "-m", required=True)
@click.option("--session-id", default=None)
def test_invoke(deployment_id, message, session_id): ...

@test.command("batch")
@click.argument("deployment_id")
@click.option("--file", "-f", help="JSON file with test cases")
def test_batch(deployment_id, file): ...

# --- Template Commands ---
@cli.group()
def template():
    """Browse and deploy templates."""

@template.command("list")
def template_list(): ...

@template.command("deploy")
@click.argument("template_id")
def template_deploy(template_id): ...

# --- Trigger Commands ---
@cli.group()
def trigger():
    """Manage agent triggers."""

@trigger.command("create")
@click.argument("deployment_id")
@click.option("--type", type=click.Choice(["schedule", "webhook", "event"]))
@click.option("--schedule", help="Cron expression")
def trigger_create(deployment_id, type, schedule): ...
```

3. **`cli/agentcore_cli/output.py`**
```python
# Rich console output formatting:
# - Tables for list commands
# - JSON/YAML for export commands
# - Progress bars for deployment
# - Colored status indicators
```

### New Files: SDK

4. **`sdk/agentcore_sdk/__init__.py`**
```python
from .client import AgentCoreClient
from .models import Workflow, Deployment, Template, Trigger
```

5. **`sdk/agentcore_sdk/client.py`**
```python
import httpx
from typing import Optional, List, Dict, Any

class AgentCoreClient:
    """Python SDK for the AgentCore Visual Workflow Platform."""
    
    def __init__(self, api_url: str, token: str):
        self.api_url = api_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.Client(base_url=self.api_url, headers=self.headers)
    
    # Workflows
    def list_workflows(self) -> List[Dict]: ...
    def get_workflow(self, workflow_id: str) -> Dict: ...
    def create_workflow(self, workflow: Dict) -> Dict: ...
    def update_workflow(self, workflow_id: str, workflow: Dict) -> Dict: ...
    def delete_workflow(self, workflow_id: str) -> None: ...
    def export_workflow(self, workflow_id: str, format: str = "json") -> str: ...
    def import_workflow(self, data: Dict) -> Dict: ...
    
    # Deployments
    def deploy(self, workflow_id: str, env: str = "dev", wait: bool = True) -> Dict: ...
    def get_deployment(self, deployment_id: str) -> Dict: ...
    def list_deployments(self) -> List[Dict]: ...
    def delete_deployment(self, deployment_id: str) -> None: ...
    def rollback(self, deployment_id: str, version: int) -> Dict: ...
    
    # Testing
    def invoke(self, deployment_id: str, message: str, session_id: Optional[str] = None) -> Dict: ...
    def batch_invoke(self, deployment_id: str, test_cases: List[Dict]) -> List[Dict]: ...
    
    # Triggers
    def create_trigger(self, deployment_id: str, config: Dict) -> Dict: ...
    def list_triggers(self, deployment_id: str) -> List[Dict]: ...
    def delete_trigger(self, trigger_id: str) -> None: ...
    
    # Analytics
    def get_analytics(self, deployment_id: str, period: str = "24h") -> Dict: ...
```

6. **`sdk/agentcore_sdk/models.py`**
```python
# Pydantic models for type-safe SDK usage
# Workflow, Deployment, Trigger, Analytics, etc.
```

7. **`cli/agentcore_cli/config.py`**
```python
# Config file management (~/.agentcore/config.yaml):
# - Multiple profiles (dev, staging, prod)
# - API URL, token, default region
# - `agentcore config set-profile` command
```

### GitHub Actions Integration

8. **`cli/examples/github-action.yml`**
```yaml
name: Deploy Agent
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install AgentCore CLI
        run: pip install agentcore-cli
      - name: Deploy to staging
        env:
          AGENTCORE_API_URL: ${{ secrets.AGENTCORE_API_URL }}
          AGENTCORE_TOKEN: ${{ secrets.AGENTCORE_TOKEN }}
        run: |
          agentcore workflow import agent-config.yaml
          agentcore deploy create $WORKFLOW_ID --env staging --wait
          agentcore test invoke $DEPLOYMENT_ID -m "Hello, are you working?"
```

### Modified Files

9. **`backend/src/app/main.py`**
   - Ensure all API endpoints are documented (OpenAPI spec auto-generated by FastAPI)
   - Add API key authentication option (for CLI/SDK, alongside Cognito)

10. **`infra/stacks/main_stack.py`**
    - Add API key support on API Gateway (usage plans, throttling)

## Deployment Instructions

1. Add API key authentication to API Gateway
2. Deploy backend with new auth option
3. Package CLI as pip-installable: `pip install agentcore-cli`
4. Package SDK as pip-installable: `pip install agentcore-sdk`
5. Test: `agentcore workflow list` → returns workflows
6. Test: `agentcore deploy create <id> --wait` → deploys successfully

## Testing Requirements

### Unit Tests (CLI)
- All commands parse arguments correctly
- Output formatting (table, JSON, YAML)
- Config file read/write
- Error handling (API down, auth failed, not found)

### Unit Tests (SDK)
- All client methods make correct HTTP calls (mock httpx)
- Response parsing into models
- Error handling and retries

### Integration Tests
- CLI: `agentcore workflow list` against live API
- SDK: `client.deploy(workflow_id)` creates real deployment
- CLI: Full flow: create → deploy → invoke → delete

## Security Requirements

- [ ] API keys scoped per user (not shared)
- [ ] API keys can be rotated without downtime
- [ ] Token stored securely in config file (file permissions 600)
- [ ] CLI supports environment variables (no secrets in command history)
- [ ] Rate limiting per API key
- [ ] API key usage logged for audit

## Acceptance Criteria

- [ ] `pip install agentcore-cli` works on Python 3.10+
- [ ] `agentcore workflow list` returns user's workflows
- [ ] `agentcore deploy create` deploys and waits for completion
- [ ] `agentcore test invoke` sends message and returns response
- [ ] SDK: `AgentCoreClient` provides type-hinted methods
- [ ] GitHub Actions example works end-to-end
- [ ] Config profiles support multiple environments
- [ ] Comprehensive `--help` on all commands
- [ ] OpenAPI spec exported at `/api/docs` (FastAPI auto-generates)
