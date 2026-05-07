/**
 * Agent versions API client (Task 03).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export interface VersionSummary {
  deployment_id: string;
  version: number;
  user_id: string;
  status: 'active' | 'archived' | 'rolled-back';
  deployed_by: string;
  deployed_at: string;
  change_description: string;
  agent_code_hash?: string | null;
  runtime_id?: string | null;
}

export interface AgentVersion extends VersionSummary {
  workflow_snapshot: Record<string, unknown>;
  agent_code?: string | null;
  model_config_snapshot: Record<string, unknown>;
  tools_config: Record<string, unknown>[];
  system_prompt?: string | null;
  memory_config?: Record<string, unknown> | null;
  policy_config?: Record<string, unknown> | null;
  guardrails_config?: Record<string, unknown> | null;
  knowledge_base_config?: Record<string, unknown> | null;
  runtime_arn?: string | null;
}

export interface VersionDiffChange {
  field: string;
  from: unknown;
  to: unknown;
}

export interface SnapshotCreateRequest {
  deployment_id: string;
  workflow_snapshot?: Record<string, unknown>;
  agent_code?: string;
  model_config_snapshot?: Record<string, unknown>;
  tools_config?: Record<string, unknown>[];
  system_prompt?: string;
  memory_config?: Record<string, unknown>;
  policy_config?: Record<string, unknown>;
  guardrails_config?: Record<string, unknown>;
  knowledge_base_config?: Record<string, unknown>;
  runtime_arn?: string;
  runtime_id?: string;
  change_description?: string;
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

export async function listVersions(deploymentId: string): Promise<VersionSummary[]> {
  const resp = await req<{ versions: VersionSummary[] }>(
    `/api/deployments/${encodeURIComponent(deploymentId)}/versions`,
  );
  return resp.versions;
}

export async function getVersion(deploymentId: string, version: number): Promise<AgentVersion> {
  const resp = await req<{ version: AgentVersion }>(
    `/api/deployments/${encodeURIComponent(deploymentId)}/versions/${version}`,
  );
  return resp.version;
}

export async function getActiveVersion(deploymentId: string): Promise<AgentVersion> {
  const resp = await req<{ version: AgentVersion }>(
    `/api/deployments/${encodeURIComponent(deploymentId)}/versions/active`,
  );
  return resp.version;
}

export async function diffVersions(
  deploymentId: string,
  from: number,
  to: number,
): Promise<{ changes: VersionDiffChange[] }> {
  return req(
    `/api/deployments/${encodeURIComponent(deploymentId)}/versions/diff?from_version=${from}&to_version=${to}`,
  );
}

export async function createSnapshot(req_body: SnapshotCreateRequest): Promise<AgentVersion> {
  const resp = await req<{ version: AgentVersion }>(
    `/api/deployments/${encodeURIComponent(req_body.deployment_id)}/versions`,
    { method: 'POST', body: JSON.stringify(req_body) },
  );
  return resp.version;
}

export async function rollback(
  deploymentId: string,
  targetVersion: number,
  reason: string,
): Promise<{ new_version: number; restored_from_version: number; workflow_snapshot: Record<string, unknown> }> {
  return req(
    `/api/deployments/${encodeURIComponent(deploymentId)}/versions/rollback`,
    {
      method: 'POST',
      body: JSON.stringify({ target_version: targetVersion, reason }),
    },
  );
}
