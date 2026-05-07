/**
 * Agent version history + diff + rollback UI (Task 03).
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
    <div style={{ padding: 16 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>Version History</h2>
        {onClose && <button onClick={onClose}>✕</button>}
      </header>
      {error && <div style={{ color: '#b00', marginTop: 8 }}>{error}</div>}
      {loading && <div>Loading…</div>}
      {!loading && versions.length === 0 && (
        <div style={{ color: '#666', marginTop: 12 }}>
          No versions yet. Deploy this agent to create its first snapshot.
        </div>
      )}
      <ul style={{ listStyle: 'none', padding: 0, marginTop: 12 }}>
        {versions.map((v) => (
          <li
            key={v.version}
            style={{
              border: '1px solid #ddd',
              borderRadius: 4,
              padding: 12,
              marginBottom: 8,
              background: v.status === 'active' ? '#e8f5e9' : '#fff',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>v{v.version}</strong>{' '}
                <span
                  style={{
                    fontSize: 11,
                    padding: '2px 6px',
                    borderRadius: 3,
                    background: v.status === 'active' ? '#2e7d32' : '#888',
                    color: '#fff',
                  }}
                >
                  {v.status}
                </span>{' '}
                <span style={{ color: '#555', fontSize: 12 }}>
                  {new Date(v.deployed_at).toLocaleString()} · {v.deployed_by}
                </span>
                {v.change_description && (
                  <div style={{ fontSize: 12, marginTop: 4 }}>{v.change_description}</div>
                )}
                {v.agent_code_hash && (
                  <div style={{ fontSize: 11, color: '#888', fontFamily: 'monospace' }}>
                    sha256:{v.agent_code_hash.slice(0, 12)}…
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={() => setSelected([v.version, selected[1]])}>Set as from</button>
                <button onClick={() => setSelected([selected[0], v.version])}>Set as to</button>
                {v.status !== 'active' && (
                  <button onClick={() => setRollbackTarget(v.version)}>Rollback to this</button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {selected[0] !== null && selected[1] !== null && (
        <section style={{ marginTop: 12, padding: 12, border: '1px solid #eee', borderRadius: 4 }}>
          <div>
            Diff <strong>v{selected[0]}</strong> → <strong>v{selected[1]}</strong>{' '}
            <button onClick={runDiff}>Compute</button>
          </div>
          {diff !== null && (
            <div style={{ marginTop: 8 }}>
              {diff.length === 0 && <div style={{ color: '#666' }}>No differences.</div>}
              {diff.map((c, i) => (
                <div key={i} style={{ fontSize: 12, marginBottom: 6 }}>
                  <strong>{c.field}</strong>
                  <div style={{ color: '#c62828' }}>
                    - {JSON.stringify(c.from)}
                  </div>
                  <div style={{ color: '#2e7d32' }}>
                    + {JSON.stringify(c.to)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {rollbackTarget !== null && (
        <section style={{ marginTop: 12, padding: 12, border: '1px solid #b58900', borderRadius: 4 }}>
          <div>
            Rollback to <strong>v{rollbackTarget}</strong>. This creates a new active version with
            the target's content. You must <em>redeploy</em> after rollback for the change to take effect.
          </div>
          <input
            style={{ width: '100%', marginTop: 8 }}
            placeholder="Reason (required)"
            value={rollbackReason}
            onChange={(e) => setRollbackReason(e.target.value)}
          />
          <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>
            <button onClick={runRollback}>Confirm rollback</button>
            <button onClick={() => setRollbackTarget(null)}>Cancel</button>
          </div>
        </section>
      )}
    </div>
  );
}

export default VersionHistory;
