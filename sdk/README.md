# agentcore-sdk

Python SDK for the AgentCore Visual Workflow Platform. Wraps the REST API
with typed methods and Pydantic models.

## Install

```bash
pip install agentcore-sdk
```

## Usage

```python
from agentcore_sdk import AgentCoreClient

client = AgentCoreClient(
    api_url="https://your-cloudfront-url.cloudfront.net",
    token="your-cognito-access-token",
)

# Workflows
for wf in client.list_workflows():
    print(wf["name"])

# Triggers
client.create_schedule_trigger(
    deployment_id="d1",
    runtime_id="r1",
    name="nightly",
    schedule_expression="cron(0 9 * * ? *)",
)

# Versions
versions = client.list_versions("d1")
client.rollback("d1", target_version=1, reason="regression")

# Analytics
summary = client.analytics_summary("d1", hours=24)
```

All methods return plain dicts; the `AgentCoreClient.raw` attribute exposes
the underlying `httpx.Client` for calls outside the typed API surface.
