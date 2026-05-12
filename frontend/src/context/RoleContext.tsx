/**
 * RoleContext — the single source of truth for the caller's RBAC state.
 *
 * On mount the provider calls GET /api/rbac/me once, caches the role +
 * permissions, and exposes helpers so any component can ask:
 *   - what is my role?
 *   - do I have permission X?
 *   - show a Publisher-only button or hide it?
 *
 * The backend is the authoritative check (every route is gated), but the
 * UI uses this context to hide controls a user can't use so they don't
 * click Publish and see a 403.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { authFetch } from '../auth/authFetch';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export type Role =
  | 'platform_admin'
  | 'agent_creator'
  | 'agent_operator'
  | 'agent_tester'
  | 'viewer'
  | 'registry_publisher'
  | 'registry_consumer';

export interface MeResponse {
  user_id: string;
  email: string | null;
  role: Role;
  permissions: string[];
}

interface RoleContextValue {
  loading: boolean;
  error: string | null;
  me: MeResponse | null;
  role: Role | null;
  has: (permission: string) => boolean;
  refresh: () => Promise<void>;
}

const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/rbac/me`);
      if (!res.ok) throw new Error(`rbac/me failed (${res.status})`);
      const data: MeResponse = await res.json();
      setMe(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<RoleContextValue>(() => {
    const perms = new Set(me?.permissions ?? []);
    return {
      loading,
      error,
      me,
      role: me?.role ?? null,
      has: (p: string) => perms.has(p),
      refresh,
    };
  }, [loading, error, me, refresh]);

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) {
    // Pre-provider render — safe empty state so components don't crash.
    return {
      loading: true,
      error: null,
      me: null,
      role: null,
      has: () => false,
      refresh: async () => {},
    };
  }
  return ctx;
}

// Convenience bundles matching the three AWS Agent Registry personas.
export const ROLE_IS_ADMIN = (r: Role | null): boolean => r === 'platform_admin';
export const ROLE_IS_PUBLISHER = (r: Role | null): boolean =>
  r === 'platform_admin' || r === 'agent_creator' || r === 'registry_publisher';
export const ROLE_IS_CONSUMER_ONLY = (r: Role | null): boolean => r === 'registry_consumer';
