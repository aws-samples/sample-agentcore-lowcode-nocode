/**
 * Analytics API client (Task 04).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export interface AnalyticsSummary {
  deployment_id: string;
  window_hours: number;
  invocations: number;
  errors: number;
  error_rate_pct: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
}

export interface TimeseriesPoint {
  timestamp: string;
  value: number;
}

export interface RecordInvocationRequest {
  model_id?: string;
  input_tokens?: number;
  output_tokens?: number;
  latency_ms?: number;
  tool_call_count?: number;
  tool_call_success_rate?: number;
  is_error?: boolean;
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

export async function getSummary(deploymentId: string, hours = 24): Promise<AnalyticsSummary> {
  return req(`/api/analytics/${encodeURIComponent(deploymentId)}/summary?hours=${hours}`);
}

export async function getTimeseries(
  deploymentId: string,
  metric: string,
  hours = 24,
  stat = 'Sum',
): Promise<{ metric: string; stat: string; hours: number; points: TimeseriesPoint[] }> {
  const q = new URLSearchParams({ metric, hours: String(hours), stat });
  return req(`/api/analytics/${encodeURIComponent(deploymentId)}/timeseries?${q.toString()}`);
}

export async function recordInvocation(
  deploymentId: string,
  body: RecordInvocationRequest,
): Promise<{ status: string; estimated_cost_usd: number }> {
  return req(`/api/analytics/${encodeURIComponent(deploymentId)}/record`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
