/**
 * AgentCore Optimization API client (Task 12).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export interface EvaluatorSummary {
  evaluator_id: string;
  evaluator_name: string;
  evaluator_arn: string;
  evaluator_type: string;
  level?: string | null;
  description?: string | null;
  status?: string | null;
  locked_for_modification: boolean;
}

export interface BundleComponent {
  resource_arn: string;
  configuration: Record<string, unknown>;
}

export interface ConfigurationBundleRecord {
  bundle_id: string;
  user_id: string;
  bundle_name: string;
  description: string;
  bundle_arn: string;
  latest_version_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConfigurationBundleRequest {
  bundle_name: string;
  description?: string;
  components?: BundleComponent[];
  branch_name?: string;
  commit_message?: string;
}

export interface ConfigurationBundleUpdateRequest {
  components?: BundleComponent[];
  branch_name?: string;
  commit_message?: string;
  parent_version_ids?: string[];
  description?: string;
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

export async function listEvaluators(): Promise<EvaluatorSummary[]> {
  const r = await req<{ evaluators: EvaluatorSummary[] }>(`/api/optimization/evaluators`);
  return r.evaluators;
}

export async function listBundles(): Promise<ConfigurationBundleRecord[]> {
  const r = await req<{ bundles: ConfigurationBundleRecord[] }>(`/api/optimization/bundles`);
  return r.bundles;
}

export async function createBundle(body: ConfigurationBundleRequest): Promise<ConfigurationBundleRecord> {
  const r = await req<{ bundle: ConfigurationBundleRecord }>(`/api/optimization/bundles`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return r.bundle;
}

export async function updateBundle(
  id: string,
  body: ConfigurationBundleUpdateRequest,
): Promise<ConfigurationBundleRecord> {
  const r = await req<{ bundle: ConfigurationBundleRecord }>(
    `/api/optimization/bundles/${encodeURIComponent(id)}`,
    { method: 'PUT', body: JSON.stringify(body) },
  );
  return r.bundle;
}

export async function listBundleVersions(id: string): Promise<{ versions: Array<Record<string, unknown>> }> {
  return req(`/api/optimization/bundles/${encodeURIComponent(id)}/versions`);
}

export async function deleteBundle(id: string): Promise<void> {
  await req(`/api/optimization/bundles/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
