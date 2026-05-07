/**
 * Triggers API client (Task 01).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export type TriggerType = 'schedule' | 'webhook' | 'event';
export type TriggerStatus = 'active' | 'disabled' | 'error';

export interface TriggerConfig {
  trigger_id: string;
  user_id: string;
  deployment_id: string;
  runtime_id?: string | null;
  trigger_type: TriggerType;
  name: string;
  description?: string | null;
  enabled: boolean;
  status: TriggerStatus;
  schedule_expression?: string | null;
  schedule_timezone?: string | null;
  webhook_path?: string | null;
  webhook_secret_arn?: string | null;
  event_pattern?: Record<string, unknown> | null;
  event_bus_name?: string | null;
  input_template?: string | null;
  schedule_name?: string | null;
  schedule_arn?: string | null;
  event_rule_name?: string | null;
  event_rule_arn?: string | null;
  trigger_count: number;
  last_triggered_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TriggerCreateRequest {
  deployment_id: string;
  runtime_id?: string;
  trigger_type: TriggerType;
  name: string;
  description?: string;
  schedule_expression?: string;
  schedule_timezone?: string;
  webhook_path?: string;
  event_pattern?: Record<string, unknown>;
  event_bus_name?: string;
  input_template?: string;
  enabled?: boolean;
}

export interface TriggerUpdateRequest {
  name?: string;
  description?: string;
  enabled?: boolean;
  schedule_expression?: string;
  input_template?: string | null;
}

export interface TriggerInvocationRecord {
  invocation_id: string;
  trigger_id: string;
  user_id: string;
  deployment_id: string;
  status: 'success' | 'failed' | 'throttled';
  source: string;
  input_payload_preview?: string | null;
  error?: string | null;
  duration_ms?: number | null;
  invoked_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
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

export async function listTriggers(deployment_id?: string): Promise<TriggerConfig[]> {
  const q = deployment_id ? `?deployment_id=${encodeURIComponent(deployment_id)}` : '';
  const resp = await request<{ triggers: TriggerConfig[] }>(`/api/triggers${q}`);
  return resp.triggers;
}

export async function createTrigger(req: TriggerCreateRequest): Promise<TriggerConfig> {
  const resp = await request<{ trigger: TriggerConfig }>(`/api/triggers`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
  return resp.trigger;
}

export async function updateTrigger(id: string, req: TriggerUpdateRequest): Promise<TriggerConfig> {
  const resp = await request<{ trigger: TriggerConfig }>(`/api/triggers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(req),
  });
  return resp.trigger;
}

export async function deleteTrigger(id: string): Promise<void> {
  await request<{ message: string }>(`/api/triggers/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export async function testTrigger(id: string, input?: string): Promise<{ invocation_id: string; status: string; error?: string; duration_ms?: number }> {
  return request(`/api/triggers/${encodeURIComponent(id)}/test`, {
    method: 'POST',
    body: JSON.stringify({ input: input ?? '' }),
  });
}

export async function getTriggerHistory(id: string): Promise<TriggerInvocationRecord[]> {
  const resp = await request<{ invocations: TriggerInvocationRecord[] }>(
    `/api/triggers/${encodeURIComponent(id)}/history`,
  );
  return resp.invocations;
}

export async function getWebhookSecret(id: string): Promise<{ trigger_id: string; webhook_path: string; secret: string }> {
  return request(`/api/triggers/${encodeURIComponent(id)}/secret`);
}

export function webhookUrl(base: string, webhookPath: string): string {
  const baseUrl = base.replace(/\/$/, '');
  return `${baseUrl}/api/webhooks/${encodeURIComponent(webhookPath)}`;
}

export const SCHEDULE_PRESETS: { label: string; expression: string }[] = [
  { label: 'Every 15 minutes', expression: 'rate(15 minutes)' },
  { label: 'Every hour', expression: 'rate(1 hour)' },
  { label: 'Daily at 09:00 UTC', expression: 'cron(0 9 * * ? *)' },
  { label: 'Weekly, Monday 09:00 UTC', expression: 'cron(0 9 ? * 2 *)' },
  { label: 'First of every month, 09:00 UTC', expression: 'cron(0 9 1 * ? *)' },
];
