/**
 * Agent version history + diff + rollback UI (Task 03).
 *
 * Styled to match the AWS-console Tailwind look of the DeployPanel.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  type VersionDiffChange,
  type VersionSummary,
  diffVersions,
  listVersions,
  rollback,
} from '../../services/versions';

interface Props {
  deploymentId: string;
  onRollback?: (newVersion: number, workflow: Record<string, unknown>) => void;
  onClose?: () => void;
}

const btnSecondaryCls =
  'px-2.5 py-1 text-xs font-medium rounded-md border border-[#e9ebed] bg-white text-[#16191f] ' +
  'hover:bg-[#f2f3f3] transition-colors';
const btnPrimaryCls =
  'inline-flex items-center gap-1.5 rounded-md bg-[#0972d3] px-3 py-1.5 text-sm font-semibold text-white ' +
  'hover:bg-[#0961b9] disabled:bg-[#e9ebed] disabled:text-[#8d99a8] disabled:cursor-not-allowed transition-colors';
const inputCls =
  'w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm text-[#16191f] ' +
  'focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30 placeholder-[#8d99a8]';

export function VersionHistory({ deploymentId, onRollback, onClose }: Props) {
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<[number | null, number | null]>([null, null]);
  const [diff, setDiff] = useState<VersionDiffChange[] | null>(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setVersions(await listVersions(deploymentId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  }, [deploymentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runDiff = async () => {
    if (selected[0] === null || selected[1] === null) return;
    setDiff(null);
    try {
      const r = await diffVersions(deploymentId, selected[0], selected[1]);
      setDiff(r.changes);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  };

  const runRollback = async () => {
    if (rollbackTarget === null) return;
    if (!rollbackReason.trim()) {
      setError('Rollback reason is required');
      return;
    }
    try {
      const r = await rollback(deploymentId, rollbackTarget, rollbackReason);
      onRollback?.(r.new_version, r.workflow_snapshot);
      setRollbackTarget(null);
      setRollbackReason('');
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  };

  return (
    <div className="p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-[#16191f]">Version history</h2>
          <p className="text-xs text-[#5f6b7a] mt-0.5">
            Every deploy snapshots workflow state. Diff versions and roll back safely.
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close versions"
            className="p-1.5 rounded-md text-[#5f6b7a] hover:bg-[#f2f3f3] transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-xs text-[#5f6b7a]">
          <div className="w-3 h-3 border-2 border-[#0972d3] border-t-transparent rounded-full animate-spin" />
          Loading versions…
        </div>
      )}

      {!loading && versions.length === 0 && (
        <div className="rounded-xl border border-dashed border-[#e9ebed] bg-[#fafafa] p-6 text-center">
          <div className="text-sm text-[#16191f] font-medium mb-1">No versions yet</div>
          <div className="text-xs text-[#5f6b7a]">
            Deploy this agent to create its first snapshot.
          </div>
        </div>
      )}

      <ul className="space-y-2">
        {versions.map((v) => {
          const isActive = v.status === 'active';
          const isFrom = selected[0] === v.version;
          const isTo = selected[1] === v.version;
          return (
            <li
              key={v.version}
              className={`rounded-xl border p-3 shadow-sm ${
                isActive ? 'border-emerald-200 bg-emerald-50/40' : 'border-[#e9ebed] bg-white'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-semibold text-[#16191f]">v{v.version}</span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${
                        isActive
                          ? 'bg-emerald-500 text-white'
                          : 'bg-[#f2f3f3] text-[#5f6b7a] border border-[#e9ebed]'
                      }`}
                    >
                      {v.status}
                    </span>
                    {isFrom && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#0972d3]/10 text-[#0972d3] font-medium">
                        FROM
                      </span>
                    )}
                    {isTo && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#ff9900]/10 text-[#d45b07] font-medium">
                        TO
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-[#5f6b7a] mt-1">
                    {new Date(v.deployed_at).toLocaleString()} · {v.deployed_by}
                  </div>
                  {v.change_description && (
                    <div className="text-xs text-[#16191f] mt-1">{v.change_description}</div>
                  )}
                  {v.agent_code_hash && (
                    <div className="text-[10px] text-[#8d99a8] font-mono mt-1">
                      sha256:{v.agent_code_hash.slice(0, 12)}…
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5 flex-shrink-0 justify-end">
                  <button
                    className={btnSecondaryCls}
                    onClick={() => setSelected([v.version, selected[1]])}
                  >
                    Set as from
                  </button>
                  <button
                    className={btnSecondaryCls}
                    onClick={() => setSelected([selected[0], v.version])}
                  >
                    Set as to
                  </button>
                  {!isActive && (
                    <button
                      className="px-2.5 py-1 text-xs font-medium rounded-md border border-[#ff9900]/40 bg-[#ff9900]/10 text-[#d45b07] hover:bg-[#ff9900]/20 transition-colors"
                      onClick={() => setRollbackTarget(v.version)}
                    >
                      Rollback to this
                    </button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {selected[0] !== null && selected[1] !== null && (
        <section className="rounded-xl border border-[#e9ebed] bg-white p-3.5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="text-sm text-[#16191f]">
              Diff <span className="font-semibold">v{selected[0]}</span>{' '}
              <span className="text-[#5f6b7a]">→</span>{' '}
              <span className="font-semibold">v{selected[1]}</span>
            </div>
            <button onClick={runDiff} className={btnPrimaryCls}>Compute</button>
          </div>
          {diff !== null && (
            <div className="mt-3 space-y-2">
              {diff.length === 0 && (
                <div className="text-xs text-[#5f6b7a]">No differences.</div>
              )}
              {diff.map((c, i) => (
                <div
                  key={i}
                  className="rounded-md border border-[#e9ebed] bg-[#fafafa] p-2.5 text-xs"
                >
                  <div className="font-semibold text-[#16191f] mb-1">{c.field}</div>
                  <div className="font-mono text-[11px] text-red-700 bg-red-50 rounded px-2 py-1 mb-1 break-all">
                    − {JSON.stringify(c.from)}
                  </div>
                  <div className="font-mono text-[11px] text-emerald-700 bg-emerald-50 rounded px-2 py-1 break-all">
                    + {JSON.stringify(c.to)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {rollbackTarget !== null && (
        <section className="rounded-xl border border-[#ff9900]/40 bg-[#ff9900]/5 p-3.5 shadow-sm space-y-2">
          <div className="text-sm text-[#16191f]">
            Rollback to <span className="font-semibold">v{rollbackTarget}</span>. This creates a new
            active version with the target's content. You must <em>redeploy</em> after rollback for
            the change to take effect.
          </div>
          <input
            className={inputCls}
            placeholder="Reason (required)"
            value={rollbackReason}
            onChange={(e) => setRollbackReason(e.target.value)}
          />
          <div className="flex gap-2">
            <button onClick={runRollback} className={btnPrimaryCls}>
              Confirm rollback
            </button>
            <button onClick={() => setRollbackTarget(null)} className={btnSecondaryCls}>
              Cancel
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

export default VersionHistory;
