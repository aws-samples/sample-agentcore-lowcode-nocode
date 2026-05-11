/**
 * AgentCore Harness API client (Task 11).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export type HarnessStatus =
  | 'CREATING'
  | 'CREATE_FAILED'
  | 'UPDATING'
  | 'UPDATE_FAILED'
  | 'READY'
  | 'DELETING'
  | 'DELETE_FAILED';

export type HarnessModelProvider = 'BEDROCK' | 'OPENAI' | 'GEMINI';

export interface HarnessRecord {
  harness_id: string;
  user_id: string;
  name: string;
  description?: string | null;
  arn: string;
  status: HarnessStatus;
  model_provider: HarnessModelProvider;
  model_id: string;
  agent_runtime_arn?: string | null;
  agent_runtime_id?: string | null;
  failure_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BedrockModelConfig {
  model_id: string;
  max_tokens?: number;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  stop_sequences?: string[];
}

export interface HarnessGuardrailConfig {
  guardrail_identifier: string;
  version?: string;
  trace?: boolean;
}

export interface HarnessKnowledgeBaseConfig {
  knowledge_base_ids: string[];
}

export interface HarnessObservabilityConfig {
  traces_enabled: boolean;
  metrics_enabled: boolean;
}

export interface HarnessLifecycleConfig {
  idle_runtime_session_timeout: number;
  max_lifetime: number;
}

export interface HarnessMemoryConfig {
  memory_arn: string;
  actor_id?: string;
  messages_count?: number;
}

export interface HarnessToolInput {
  type:
    | 'remote_mcp'
    | 'agentcore_browser'
    | 'agentcore_gateway'
    | 'inline_function'
    | 'agentcore_code_interpreter';
  name?: string;
  remote_mcp_url?: string;
  remote_mcp_headers?: Record<string, string>;
  gateway_arn?: string;
  browser_arn?: string;
  code_interpreter_arn?: string;
  inline_description?: string;
  inline_input_schema?: Record<string, unknown>;
}

export interface HarnessCreateRequest {
  harness_name: string;
  description?: string;
  model: {
    bedrock?: BedrockModelConfig;
    openai?: { model_id: string; api_key_arn: string; max_tokens?: number; temperature?: number };
    gemini?: { model_id: string; api_key_arn: string; max_tokens?: number; temperature?: number };
  };
  system_prompt?: string;
  tools?: HarnessToolInput[];
  allowed_tools?: string[];
  memory?: HarnessMemoryConfig;
  guardrail?: HarnessGuardrailConfig;
  knowledge_base?: HarnessKnowledgeBaseConfig;
  observability?: HarnessObservabilityConfig;
  lifecycle?: HarnessLifecycleConfig;
  skills?: string[];
  max_iterations?: number;
  max_tokens?: number;
  timeout_seconds?: number;
  network_mode?: 'PUBLIC' | 'VPC';
  security_group_ids?: string[];
  subnet_ids?: string[];
  tags?: Record<string, string>;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = (body as { detail?: string }).detail || msg;
    } catch {
      // ignore
    }
    throw new Error(`Request failed (${res.status}): ${msg}`);
  }
  return res.json() as Promise<T>;
}

export async function harnessRegion(): Promise<{
  region: string;
  available: boolean;
  supported_regions: string[];
}> {
  return req('/api/harness/meta/region');
}

export async function listHarnesses(): Promise<HarnessRecord[]> {
  const resp = await req<{ harnesses: HarnessRecord[] }>(`/api/harness`);
  return resp.harnesses;
}

export async function createHarness(body: HarnessCreateRequest): Promise<HarnessRecord> {
  const resp = await req<{ harness: HarnessRecord }>(`/api/harness`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return resp.harness;
}

export async function getHarness(
  id: string,
  refresh = false,
): Promise<HarnessRecord> {
  const resp = await req<{ harness: HarnessRecord }>(
    `/api/harness/${encodeURIComponent(id)}${refresh ? '?refresh=true' : ''}`,
  );
  return resp.harness;
}

export async function invokeHarness(
  id: string,
  prompt: string,
  session_id?: string,
): Promise<{ success: boolean; response?: string; error?: string; session_id?: string; duration_ms?: number }> {
  return req(`/api/harness/${encodeURIComponent(id)}/invoke`, {
    method: 'POST',
    body: JSON.stringify({ prompt, session_id }),
  });
}

export async function deleteHarness(id: string): Promise<void> {
  await req(`/api/harness/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
