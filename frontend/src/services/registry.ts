/**
 * AWS Agent Registry API client (Task 13).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export interface RegistrySummary {
  registry_id: string;
  registry_arn: string;
  name: string;
  description: string;
  status: string;
  authorizer_type?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export type DescriptorType = 'MCP' | 'A2A' | 'CUSTOM' | 'AGENT_SKILLS';

export interface RecordSummary {
  registry_id: string;
  registry_arn: string;
  record_id: string;
  record_arn: string;
  name: string;
  description: string;
  descriptor_type: string;
  record_version?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RecordCreateRequest {
  registry_id: string;
  name: string;
  description?: string;
  descriptor_type: DescriptorType;
  descriptors?: {
    mcp?: {
      server?: { schema_version?: string; inline_content: string };
      tools?: { protocol_version?: string; inline_content: string };
    };
    a2a?: { agent_card: { schema_version?: string; inline_content: string } };
    custom?: { inline_content: string };
    agent_skills?: {
      skill_md?: { inline_content: string };
      skill_definition?: { schema_version?: string; inline_content: string };
    };
  };
  record_version?: string;
  sync_from_url?: string;
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

export async function listRegistries(): Promise<RegistrySummary[]> {
  const r = await req<{ registries: RegistrySummary[] }>(`/api/registry/list`);
  return r.registries;
}

export async function listRecords(
  registry_id: string,
  filters?: { status?: string; descriptor_type?: string; name?: string },
): Promise<RecordSummary[]> {
  const q = new URLSearchParams({ registry_id });
  if (filters?.status) q.set('status_filter', filters.status);
  if (filters?.descriptor_type) q.set('descriptor_type', filters.descriptor_type);
  if (filters?.name) q.set('name', filters.name);
  const r = await req<{ records: RecordSummary[] }>(`/api/registry/records?${q.toString()}`);
  return r.records;
}

export async function searchRecords(
  registry_id: string,
  q: string,
  descriptor_type?: string,
): Promise<RecordSummary[]> {
  const params = new URLSearchParams({ registry_id, q });
  if (descriptor_type) params.set('descriptor_type', descriptor_type);
  const r = await req<{ records: RecordSummary[] }>(`/api/registry/search?${params.toString()}`);
  return r.records;
}

export async function createRecord(body: RecordCreateRequest): Promise<RecordSummary> {
  const r = await req<{ record: RecordSummary }>(`/api/registry/records`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return r.record;
}

export async function submitForApproval(registry_id: string, record_id: string): Promise<unknown> {
  return req(
    `/api/registry/records/${encodeURIComponent(record_id)}/submit?registry_id=${encodeURIComponent(registry_id)}`,
    { method: 'POST' },
  );
}

export async function approveRecord(
  registry_id: string,
  record_id: string,
  status_reason = '',
): Promise<unknown> {
  return req(
    `/api/registry/records/${encodeURIComponent(record_id)}/approve?registry_id=${encodeURIComponent(registry_id)}`,
    { method: 'POST', body: JSON.stringify({ status_reason }) },
  );
}

export async function rejectRecord(
  registry_id: string,
  record_id: string,
  status_reason: string,
): Promise<unknown> {
  return req(
    `/api/registry/records/${encodeURIComponent(record_id)}/reject?registry_id=${encodeURIComponent(registry_id)}`,
    { method: 'POST', body: JSON.stringify({ status_reason }) },
  );
}

export async function deleteRecord(registry_id: string, record_id: string): Promise<void> {
  await req(
    `/api/registry/records/${encodeURIComponent(record_id)}?registry_id=${encodeURIComponent(registry_id)}`,
    { method: 'DELETE' },
  );
}

export type AutoPublishSourceType = 'deployment' | 'tool' | 'harness';

export interface AutoPublishRequest {
  source_type: AutoPublishSourceType;
  source_id: string;
  registry_id: string;
  name?: string;
  description?: string;
  submit_for_approval?: boolean;
  tool_payload?: {
    display_name?: string;
    description?: string;
    input_schema?: Record<string, unknown>;
  };
}

export async function autoPublishToRegistry(
  body: AutoPublishRequest,
): Promise<RecordSummary> {
  const r = await req<{ record: RecordSummary }>(`/api/registry/auto-publish`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return r.record;
}
