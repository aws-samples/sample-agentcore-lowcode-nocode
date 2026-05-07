# Task 04: Observability Dashboard & Cost Tracking

## Problem Statement

**88% of AI projects fail to reach production due to operational gaps** (Databricks 2025). Our platform has basic CloudWatch logs and alarms but:
- No agent performance dashboard (no latency, token usage, or cost visibility)
- No conversation analytics (task completion, satisfaction)
- No per-agent cost tracking (impossible to know which agent costs the most)
- No visual representation of agent health

Competitors:
- **Dify**: Built-in observability with token usage, response time, user feedback
- **n8n**: Execution history, success/failure rates, timing per node
- **Microsoft Copilot Studio**: Analytics dashboard with conversation metrics, CSAT, containment rate
- **Google Vertex AI**: Agent Engine with built-in metrics, Cloud Monitoring integration

Enterprise requirement: "We need to see per-agent cost breakdowns before we can justify continued investment" — recurring theme in customer conversations.

## Proposed Solution Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│ Agent        │────▶│ CloudWatch EMF   │────▶│ CloudWatch     │
│ Runtime      │     │ (Embedded Metrics)│     │ Custom Metrics │
└──────────────┘     └──────────────────┘     └────────────────┘
                                                       │
                                              ┌────────▼────────┐
                                              │ CloudWatch      │
                                              │ Dashboard       │
                                              │ (per-agent)     │
                                              └────────┬────────┘
                                                       │
                                              ┌────────▼────────┐
                                              │ Frontend        │
                                              │ Analytics Page  │
                                              │ (Highcharts)    │
                                              └─────────────────┘
```

## AWS Services

- **CloudWatch Embedded Metric Format (EMF)**: Structured metrics from Lambda
- **CloudWatch Custom Metrics**: Per-agent dimensions (deployment_id, model, tool)
- **CloudWatch Dashboards**: Pre-built dashboard per deployment
- **AWS Cost Explorer API**: Model invocation costs (Bedrock pricing)
- **DynamoDB**: Conversation analytics storage (aggregated daily)
- **Lambda**: Analytics aggregation (daily cron)

## Metrics to Track

### Agent Performance (per deployment)
- `InvocationCount` — total calls
- `InvocationLatencyMs` — p50, p95, p99 response time
- `InputTokens` / `OutputTokens` — per invocation
- `TotalCost` — estimated cost per invocation (model pricing × tokens)
- `ToolCallCount` — number of tool calls per invocation
- `ToolCallSuccessRate` — % of tool calls that succeed
- `ToolCallLatencyMs` — per-tool latency
- `ErrorRate` — % of invocations that error
- `ConversationTurns` — average turns per session
- `TimeToFirstToken` — streaming latency

### Business Metrics
- `UniqueUsers` — distinct session IDs per day
- `TaskCompletionRate` — % of conversations with successful outcome
- `EscalationRate` — % requiring human intervention (if HITL enabled)
- `AverageCostPerConversation` — total spend ÷ conversations

## Files to Create/Modify

### New Files

1. **`backend/src/app/services/metrics_emitter.py`**
```python
import json
import sys
from datetime import datetime

class AgentMetricsEmitter:
    """Emit structured metrics using CloudWatch EMF format."""
    
    def emit_invocation_metrics(self, deployment_id, model_id, metrics):
        """Emit to stdout in EMF format — CloudWatch auto-ingests."""
        emf = {
            "_aws": {
                "Timestamp": int(datetime.now().timestamp() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": "AgentCore/Agents",
                    "Dimensions": [["DeploymentId"], ["DeploymentId", "ModelId"]],
                    "Metrics": [
                        {"Name": "InvocationLatencyMs", "Unit": "Milliseconds"},
                        {"Name": "InputTokens", "Unit": "Count"},
                        {"Name": "OutputTokens", "Unit": "Count"},
                        {"Name": "EstimatedCostUSD", "Unit": "None"},
                        {"Name": "ToolCallCount", "Unit": "Count"},
                        {"Name": "ToolCallSuccessRate", "Unit": "Percent"},
                    ]
                }]
            },
            "DeploymentId": deployment_id,
            "ModelId": model_id,
            **metrics
        }
        # Print to stdout — Lambda CloudWatch integration auto-parses EMF
        print(json.dumps(emf))
```

2. **`backend/src/app/services/cost_calculator.py`**
```python
# Bedrock pricing lookup (per-model, per-region)
# Calculate cost = (input_tokens × input_price) + (output_tokens × output_price)
# Support for all 13 providers with their respective pricing
# Daily aggregation into DynamoDB for historical tracking
```

3. **`backend/src/app/routers/analytics.py`**
```python
# Endpoints:
# GET /api/analytics/{deployment_id}/summary     - 24h/7d/30d summary
# GET /api/analytics/{deployment_id}/timeseries  - Metric over time
# GET /api/analytics/{deployment_id}/costs       - Cost breakdown
# GET /api/analytics/{deployment_id}/tools       - Per-tool performance
# GET /api/analytics/overview                    - All deployments summary
```

4. **`frontend/src/pages/AnalyticsPage.tsx`**
```typescript
// Full-page analytics dashboard with:
// - Deployment selector dropdown
// - Time range picker (24h, 7d, 30d, custom)
// - KPI cards: Total Invocations, Avg Latency, Total Cost, Error Rate
// - Charts: Invocations over time, Latency distribution, Cost trend
// - Tool performance table: name, call count, success rate, avg latency
// - Top errors table
```

5. **`frontend/src/components/analytics/CostBreakdown.tsx`**
```typescript
// Cost visualization:
// - Pie chart: cost by model provider
// - Bar chart: daily cost trend
// - Table: per-agent cost ranking
// - Budget alert configuration
```

6. **`frontend/src/components/analytics/PerformanceCharts.tsx`**
```typescript
// Using Recharts or similar:
// - Line chart: latency p50/p95/p99 over time
// - Area chart: token usage (input vs output)
// - Bar chart: invocations per hour
// - Heatmap: error rate by hour × day of week
```

7. **`backend/src/app/services/analytics_aggregator.py`**
```python
# Daily Lambda (triggered by EventBridge Scheduler):
# - Query CloudWatch metrics for each active deployment
# - Aggregate into daily summaries
# - Store in DynamoDB for fast API queries
# - Calculate cost estimates using pricing data
# - Detect anomalies (latency spike, cost surge, error rate increase)
```

### Modified Files

8. **Generated agent code (code_generator.py)**
   - Wrap agent invocations with timing + token counting
   - Emit EMF metrics after each invocation
   - Log tool call durations

9. **`infra/stacks/main_stack.py`**
   - Add DynamoDB table: `AgentAnalytics` (PK: deployment_id, SK: date)
   - Add analytics aggregator Lambda (daily schedule)
   - Add CloudWatch dashboard template per deployment
   - IAM permissions for CloudWatch GetMetricData

10. **`frontend/src/App.tsx`** (or router)
    - Add `/analytics` route
    - Add "Analytics" nav item

## Deployment Instructions

1. Modify code generator to emit EMF metrics
2. Add analytics DynamoDB table and aggregator Lambda to CDK
3. Add analytics API routes
4. Deploy backend: `./scripts/deploy.sh`
5. Add frontend analytics page, rebuild
6. Deploy an agent → invoke it 10+ times → verify metrics appear

## Testing Requirements

### Unit Tests
- EMF format output validation
- Cost calculation accuracy (known tokens × known price = expected cost)
- Analytics aggregation logic

### Integration Tests  
- Invoke agent → metrics appear in CloudWatch within 60s
- Aggregator Lambda runs → DynamoDB has daily summary
- Analytics API returns correct data for time range

### E2E Tests
- Deploy agent → invoke 50 times → dashboard shows correct metrics
- Multiple agents → overview shows per-agent breakdown
- Cost tracking matches expected Bedrock pricing

## Security Requirements

- [ ] Analytics API requires authentication
- [ ] Users can only see metrics for their own deployments
- [ ] No PII in metrics (no conversation content, only counts/latencies)
- [ ] Cost data approximations clearly labeled (not billing-accurate)
- [ ] CloudWatch dashboard access scoped by IAM

## Acceptance Criteria

- [ ] After 10+ invocations, all metric types populated
- [ ] Dashboard shows real-time metrics (< 5 min delay)
- [ ] Cost breakdown shows estimated spend per agent per day
- [ ] Latency percentiles (p50, p95, p99) displayed correctly
- [ ] Tool performance table ranks tools by success rate
- [ ] Time range filter works (24h, 7d, 30d)
- [ ] Error rate alerts when above 5% threshold
- [ ] Analytics page loads in < 3 seconds
