/**
 * Approvals API client (Task 02).
 */
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired';
export type ApprovalType = 'binary' | 'choice' | 'form' | 'review';

export interface Approval {
  approval_id: string;
  user_id: string;
  deployment_id: string;
  runtime_id?: string | null;
  session_id?: string | null;
  approval_type: ApprovalType;
  title: string;
  description: string;
  context: Record<string, unknown>;
  proposed_action: string;
  options?: string[] | null;
  form_schema?: Record<string, unknown> | null;
  content_to_review?: string | null;
  status: ApprovalStatus;
  timeout_minutes: number;
  created_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution?: Record<string, unknown> | null;
  ttl?: number | null;
}

export interface ApprovalCreateRequest {
  deployment_id: string;
  runtime_id?: string;
  session_id?: string;
  approval_type?: ApprovalType;
  title: string;
  description?: string;
  context?: Record<string, unknown>;
  proposed_action?: string;
  options?: string[];
  form_schema?: Record<string, unknown>;
  content_to_review?: string;
  timeout_minutes?: number;
}

export interface ApprovalResolveRequest {
  decision: 'approved' | 'rejected';
  feedback?: string;
  edited_content?: string;
  form_data?: Record<string, unknown>;
  selected_option?: string;
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

export async function listApprovals(params?: { status?: ApprovalStatus; deployment_id?: string }): Promise<Approval[]> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set('status_filter', params.status);
  if (params?.deployment_id) qs.set('deployment_id', params.deployment_id);
  const q = qs.toString() ? `?${qs.toString()}` : '';
  const resp = await req<{ approvals: Approval[] }>(`/api/approvals${q}`);
  return resp.approvals;
}

export async function createApproval(body: ApprovalCreateRequest): Promise<Approval> {
  const resp = await req<{ approval: Approval }>(`/api/approvals`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return resp.approval;
}

export async function getApproval(id: string): Promise<Approval> {
  const resp = await req<{ approval: Approval }>(`/api/approvals/${encodeURIComponent(id)}`);
  return resp.approval;
}

export async function resolveApproval(id: string, body: ApprovalResolveRequest): Promise<Approval> {
  const resp = await req<{ approval: Approval }>(
    `/api/approvals/${encodeURIComponent(id)}/resolve`,
    { method: 'POST', body: JSON.stringify(body) },
  );
  return resp.approval;
}

export async function approvalStats(): Promise<{ pending: number; approved: number; rejected: number; expired: number }> {
  return req(`/api/approvals/stats`);
}
