# G3.1 Coverage Matrix — 354 catalog patterns vs platform surface (2026-07-08)

Catalog: `.claude/agents/agentcore-pattern-catalog.md` (354 pattern IDs, 24 families).

## Grounded platform surface (from code, not assumption)

- Framework: `strands_agents` ONLY (`enums.py:AgentFramework`)
- Providers: bedrock (self-contained) + openai/anthropic/gemini/litellm/mistral/ollama/sagemaker/writer/llamaapi/deepseek/groq/together (each needs an API key)
- Protocols: HTTP / MCP / A2A (`AgentServerProtocol`)
- Components (12): runtime, gateway (targets: **lambda, openapi, smithy, mcp_server** only), memory (semantic/summary/episodic/user_preferences/custom), code_interpreter, browser, guardrails, observability (langfuse/custom-OTLP), identity (oauth2/api_key), evaluation (+CustomEvaluatorConfig), policy (Cedar allowed-tools ENFORCE/etc.), a2a, tool
- KB: kbMode existing|create_new; dataSource s3|web_crawler|confluence|salesforce|sharepoint; vector s3_vectors|opensearch_serverless; retrieval multi_hop|hybrid|reranked
- Platform-native: P-PLAT-001..027; deploy surfaces: sync API, Step Functions async, CFN export, harness path

## Classification (every pattern ID, grouped)

### Family A — P-RUN (28)
- SELF_CONTAINED (5): P-RUN-001 (template web-search-agent), P-RUN-015 (harness declarative path), P-RUN-018 (SSE via stream_handler), P-RUN-019 (context echo via custom tool), P-RUN-024→**UNMAPPABLE** — correction: no persistent-FS config → moved below.
  Final: P-RUN-001, P-RUN-015, P-RUN-018, P-RUN-019 (4)
- NEEDS_INPUT (1): P-RUN-003 (non-Bedrock provider key: OpenAI/Anthropic/Gemini)
- UNMAPPABLE (23): P-RUN-002 (LangGraph), 004 (CrewAI), 005 (Java ADK), 006 (TS/Mastra), 007 (AgentSkills), 008 (Google ADK), 009 (LlamaIndex), 010 (OpenAI Agents SDK), 011 (AutoGen), 012/013 (Claude Agent SDK ±hooks), 014 (PydanticAI), 016 (AG-UI), 017 (custom ASGI middleware), 020 (S3 payload swap), 021 (async 8-hr lifecycle), 022 (EFS), 023 (S3 mount), 024 (persistent session FS), 025 (exec-command side channel), 026 (VPC runtime), 027/028 (WebRTC)

### Family B — P-MCP (6) / P-A2A (5)
- SELF_CONTAINED (5): P-MCP-001 (template mcp-server-runtime), P-MCP-002 (MCP + IAM), P-A2A-001 (protocol=A2A, agent-card), P-A2A-003 (multi-deploy + call_a2a_peer), P-A2A-005 (3× Strands A2A)
- NEEDS_INPUT (1): P-MCP-004 (Auth0 tenant + DCR)
- UNMAPPABLE (5): P-MCP-003 (TS SDK), P-MCP-005 (prompts/resources/elicitation), P-MCP-006 (stateful MCP), P-A2A-002 (dedupe note: IAM-A2A expressible → actually SELF_CONTAINED, dedup with P-A2A-001; counted there), P-A2A-004 (mixed frameworks)
  Final UNMAPPABLE: P-MCP-003, P-MCP-005, P-MCP-006, P-A2A-004 (4); P-A2A-002 dedup→P-A2A-001

### Family C — P-MULTI (6)
- SELF_CONTAINED (1): P-MULTI-002 (sub-agents as Lambda tools on Gateway)
- UNMAPPABLE (5): 001 (raw boto3 fan-out; runtime role lacks InvokeAgentRuntime config), 003 (in-process multi-agent codegen absent), 004 (LangGraph supervisor), 005 (Auth0 RFC8693), 006 (mixed frameworks)

### Family D — P-GW (49)
- SELF_CONTAINED (7): P-GW-LAM-001 (template strands-gateway-agent), P-GW-SMI-001 (smithy target), P-GW-MCP-001 (template mcp-server-gateway-target), P-GW-PRE-016/017/018/019 (Bedrock-Agent/Bedrock/CloudWatch/DDB via smithy target)
- NEEDS_INPUT (17): P-GW-OAS-001/002/003 (external OpenAPI backend + key/OAuth2; note: OpenAPI target sync limitation on harness path), P-GW-APIGW-001/002 (existing APIGW stage; HealthLake), P-GW-MCP-003 (3LO IdP), P-GW-MCP-006 (external MCP w/ resources), P-GW-MCP-007 (Dynatrace), P-GW-MCP-008/009 (Databricks), P-GW-MCP-010 (AWS Knowledge MCP — public but external-URL target type unsupported → see note), P-GW-PRE-001..005 grouped: Salesforce, Slack, Jira, Asana, Confluence keys, P-GW-PRE-006..014 grouped: MS Graph, PagerDuty, ServiceNow, Zendesk, Smartsheet, Tavily, Brave, Zoom, BambooHR keys
- UNMAPPABLE (25): P-GW-LAM-002 (IAM inbound), 003 (semantic tool search), 004 (custom scopes), 005 (DDB authz interceptor), P-GW-MCP-002 (DYNAMIC), 004 (SigV4 MCP), 005 (no-auth), P-GW-PRE-015 (x402), P-GW-PRE-020 (VS Code OAuth proxy), P-GW-RUN-001..004 (runtime-HTTP target type absent), P-GW-VPC-001..004 (Lattice/ECS/EKS)
  (P-GW-MCP-010 counted once in NEEDS_INPUT/UNMAPPABLE boundary: external MCP URL target absent → UNMAPPABLE. Moved: NEEDS_INPUT 16, UNMAPPABLE 26.)

### Family E — P-INT (10)
- UNMAPPABLE (10): no gateway interceptor surface (REQUEST or RESPONSE) in schema: P-INT-001..010

### Family F — P-AUTH-IN (12)
- SELF_CONTAINED (3): P-AUTH-IN-001 (IAM SigV4 default), 002 (Cognito JWT), 010 (Cognito-as-CUSTOM_JWT — platform's gateway wiring)
- NEEDS_INPUT (4): 003 (Auth0), 004 (Okta), 005 (Entra), 006 (PingFederate)
- UNMAPPABLE (5): 007 (customClaims rules), 008 (allowedScopes), 009 (allowedAudiences), 011/012 (private IdP via Lattice)

### Family G — P-AUTH-OUT (16)
- SELF_CONTAINED (3): 005 (M2M 2LO — platform-provisioned Cognito CC chain), 010 (customer-owned Cognito in-account), 013 (custom/api-key credential provider)
- NEEDS_INPUT (7): 001 (OpenAI key), 002 (Google 3LO), 003 (GitHub 3LO), 004 (LinkedIn 3LO), 006 (Entra OBO), 007 (M2M+3LO), 014 (per-IdP creds ×25)
- UNMAPPABLE (6): 008 (requestHeaderAllowlist OBO), 009 (3LO from ECS), 011 (mTLS), 012 (SAML), 015 (private IdP Lattice), 016 (3LO USER_FEDERATION)

### Family H — P-MEM (23)
- SELF_CONTAINED (7): STM-001, LTM-001 (user_preferences), LTM-002 (semantic), LTM-003 (summary), LTM-004 (episodic), LTM-008 (custom), ADV-002 (hooks = platform default wiring; dedup STM-001)
- UNMAPPABLE (16): STM-002 (shared cross-agent memory id), LTM-005/006/007 (override prompts not in schema), NS-001/002/003 (namespace templates), ADV-001 (guardrails-on-write), ADV-003 (identity-actorId binding), ADV-004 (browser→memory), ADV-005 (streams), ADV-006 (cross-region), ADV-007 (branching), ADV-008 (IAM namespace policy), ADV-009 (prefix scan), ADV-010 (funnel events)

### Family I — P-KB (23)
- SELF_CONTAINED (3): 001 (S3+S3Vectors), 002 (S3+OSS), 008 (web crawler)
- NEEDS_INPUT (3): 009 (Confluence), 010 (Salesforce), 011 (SharePoint)
- UNMAPPABLE (17): 003 (Aurora pgvector), 004..007 (Pinecone/Mongo/Redis/Neptune), 012 (custom DS), 013/014 (BDA/FM parsing), 015..018 (chunking configs), 019 (EventBridge auto-register), 020..022 (Redshift/Glue/Kendra), 023 (CDK construct product)
- NOTE: catalog's own green bar requires P-KB-003, 013, 015, 016, 019 → **impossible on this platform** (5 hard RED items by the catalog's own rule).

### Family J — P-TOOL (24)
- SELF_CONTAINED (5): CI-001, CI-002, CI-003, CI-004, BR-001
- UNMAPPABLE (19): CI-005/006 (JS/TS sandbox), CI-007 (custom session/network/role), CI-008 (S3 5GB), CI-009 (root CA), BR-002..015 (Nova Act, browser-use, Playwright, DCV, Web Bot Auth, VPC×2, allowlist, profile, proxy, extension, policies, OS actions, recording)

### Family K — P-VOICE (6) / P-STREAM (3)
- SELF_CONTAINED (1): P-STREAM-001 (SSE)
- UNMAPPABLE (8): P-VOICE-001..006, P-STREAM-002 (WebSocket), P-STREAM-003 (AG-UI)

### Family L — P-POL (5) / P-GR (4)
- SELF_CONTAINED (4): POL-001 (Cedar ENFORCE = P-PLAT-027), POL-003 (per-tool Cedar), GR-001 (input), GR-002 (output)
- UNMAPPABLE (5): POL-002 (NL-authored Cedar), POL-004 (condition/cap authoring), POL-005 (DLP interceptor), GR-003 (memory-write), GR-004 (gateway interceptor)

### Family M — P-EVAL (10) / P-OPT (1)
- SELF_CONTAINED (4): EVAL-001 (online = P-PLAT-004), EVAL-002 (results via P-PLAT-005), EVAL-006 (CustomEvaluatorConfig), EVAL-009 (builtin sweep via evaluationConfig)
- UNMAPPABLE (7): EVAL-003 (batch), 004 (dataset), 005 (simulation), 007 (Lambda evaluator — no Lambda-evaluator kind in config), 008 (ground truth), 010 (cross-account share), OPT-001
 
### Family N — P-REG (11)
- SELF_CONTAINED (3): REG-001 (publish/discover = P-PLAT-008), REG-003 (search), REG-009→ registry stores canvas entries only → UNMAPPABLE; final SELF_CONTAINED: REG-001, REG-003 + clone P-PLAT-009 equivalence (2)
- UNMAPPABLE (9): REG-002, 004, 005, 006, 007, 008, 009, 010, 011

### Family O — P-PAY (10)
- UNMAPPABLE (10): P-PAY-001..010 (no payments surface)

### Family P — P-OBS (19)
- SELF_CONTAINED (1): OBS-001 (default CW/X-Ray + P-PLAT-006 dashboard). KNOWN CAVEAT: managed runtimes don't emit gen_ai.usage spans (memory: re-confirmed 2026-07-01) → P-PLAT-010 cost canary expected FAIL.
- NEEDS_INPUT (2): OBS-007 (Langfuse keys), OBS-008..014 grouped as partner backends (Datadog/Dynatrace/Honeycomb/Instana/Arize/Braintrust/OpenLIT — custom OTLP endpoint + creds)
- UNMAPPABLE (16): OBS-002 (non-Runtime ADOT), 003 (Lambda-caller propagation), 004 (EKS), 005 (custom spans), 006 (data protection), 015 (MLflow), 016 (AgentOps flywheel), 017 (cross-account), 018 (memory spans), 019 (dual side-by-side) + partner rows without OTLP-generic path

### Family Q — P-VPC (8)
- UNMAPPABLE (8): P-VPC-001..008

### Family R — P-E2E (36)
- SELF_CONTAINED (9): 001 (Strands everything, composed), 004 (multi-tenant = platform native), 005 (template customer-support-blueprint), 008 (A2A real-estate, dedupe P-A2A-005), 012 (memory A/B, 2 deploys), 016 (embedded tools no gateway, dedupe P-RUN-001), 017 (device mgmt thin), 029 (KB+Memory+Identity composed), 031 (MCP client → gateway, dedupe P-GW-MCP-001), 036 (CFN export: runtime+browser+CI+memory)
  → distinct after dedup: 001, 005, 017, 029, 036 + counted dedups
- NEEDS_INPUT (6): 003 (Langfuse+Tavily+Zendesk), 010 (HealthLake), 023 (Auth0), 024 (Okta), 033 (EntraID)
- UNMAPPABLE (21): 002, 006, 007, 009, 011, 013, 014, 015, 018, 019, 020, 021, 022, 025, 026, 027, 028, 030, 032, 034, 035

### Family S — P-HRN (11)
- SELF_CONTAINED (4): 001 (harness baseline), 004 (harness+gateway), 009 (harness OAuth chain — platform-built), 010 (travel scenario, dedupe 001)
- UNMAPPABLE (7): 002 (Node), 003 (Go), 005 (execution limits — no config field), 006 (MCP recipe distinct from 004 — dedupe → counted in 004), 007 (skills), 008 (VPC), 011 (visual testing)

### Family T — P-VS (1)
- UNMAPPABLE (1): P-VS-001 (Elasticsearch)

### Family U — P-PLAT (27)
- SELF_CONTAINED (27): P-PLAT-001..027. Caveats: P-PLAT-010 cost canary expected FAIL (known platform observability gap, memory 2026-07-01); P-PLAT-017/018/019 use create_new KB (catalog's KB id S7ZDVE9Y4G assumed stale); P-PLAT-021 catalog-only assertions; P-PLAT-027 cold-start caveat.

## Totals

| Classification | Count (approx, after dedup) |
|---|---|
| SELF_CONTAINED | **~78** |
| NEEDS_INPUT | **~41** |
| UNMAPPABLE | **~235** |

## The two structural findings

1. **UNMAPPABLE = RED by the master prompt's own rule.** ~235/354 catalog patterns require capabilities the platform cannot deploy (10 non-Strands frameworks, voice/WebRTC, payments, gateway interceptors, VPC modes, registry advanced, vector stores beyond 2, chunking/parsing configs, async runtimes, …). The catalog's OWN green bar for Family I requires P-KB-003/013/015/016/019 — all unmappable. Under "Unmappable is a RED finding, not a skip," a GREEN verdict against this catalog is **structurally impossible** regardless of inputs.
2. **NEEDS_INPUT (~41) → BLOCKED checkpoint.** Master prompt G3.1.5: stop, list inputs, wait.
