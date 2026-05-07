# agentcore-cli

Command-line interface for the AgentCore Visual Workflow Platform.

## Install

```bash
pip install agentcore-cli
```

## Auth

The CLI uses Cognito. Provide either a pre-obtained access token, or the
Cognito pool details (user pool id, client id, username, password) and the
CLI will mint a token for you via `cognito-idp:InitiateAuth` (USER_PASSWORD_AUTH).

```bash
# Option 1: bring your own token
export AGENTCORE_API_URL=https://your-cloudfront.cloudfront.net
export AGENTCORE_TOKEN=ey...

# Option 2: let the CLI authenticate
export AGENTCORE_COGNITO_USER_POOL_ID=us-east-1_xxxxx
export AGENTCORE_COGNITO_CLIENT_ID=xxxxx
export AGENTCORE_COGNITO_USERNAME=you@example.com
export AGENTCORE_COGNITO_PASSWORD='****'
export AGENTCORE_AWS_REGION=us-east-1
```

## Examples

```bash
agentcore health
agentcore flows list
agentcore triggers list
agentcore triggers create-schedule \
  --deployment d1 --runtime r1 --name nightly --cron "cron(0 9 * * ? *)"
agentcore versions list --deployment d1
agentcore versions rollback --deployment d1 --target-version 1 --reason "regression"
agentcore analytics summary --deployment d1 --hours 24
agentcore environments promote \
  --deployment d1 --source-env dev --target-env staging --desc "ready"
agentcore guardrails test --guardrail-id abc --text "my SSN is 123-45-6789" --source OUTPUT
```

Add `--json` on any command to emit raw JSON instead of a human-readable table.
