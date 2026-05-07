/**
 * Approval Inbox (Task 02).
 *
 * Lists pending approvals for the caller, with quick approve/reject actions
 * and support for binary/choice/form/review approval types.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  type Approval,
  type ApprovalStatus,
  approvalStats,
  listApprovals,
  resolveApproval,
} from '../../services/approvals';

interface Props {
  onClose?: () => void;
}

export function ApprovalInbox({ onClose }: Props) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [stats, setStats] = useState<{ pending: number; approved: number; rejected: number; expired: number } | null>(null);
  const [statusFilter, setStatusFilter] = useState<ApprovalStatus | 'all'>('pending');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [editedContent, setEditedContent] = useState<Record<string, string>>({});
  const [selectedOption, setSelectedOption] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [items, s] = await Promise.all([
        listApprovals(statusFilter === 'all' ? {} : { status: statusFilter }),
        approvalStats(),
      ]);
      setApprovals(items);
      setStats(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load approvals');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 10000); // 10s polling
    return () => clearInterval(id);
  }, [refresh]);

  const resolve = async (approval: Approval, decision: 'approved' | 'rejected') => {
    try {
      await resolveApproval(approval.approval_id, {
        decision,
        feedback: feedback[approval.approval_id],
        edited_content: approval.approval_type === 'review' ? editedContent[approval.approval_id] : undefined,
        selected_option: approval.approval_type === 'choice' ? selectedOption[approval.approval_id] : undefined,
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to resolve');
    }
  };

  return (
    <div style={{ padding: 16 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Approval Inbox</h2>
        {onClose && <button onClick={onClose} aria-label="close">✕</button>}
      </header>

      {stats && (
        <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 13, color: '#555' }}>
          <span>Pending: <strong style={{ color: stats.pending > 0 ? '#b58900' : '#666' }}>{stats.pending}</strong></span>
          <span>Approved: {stats.approved}</span>
          <span>Rejected: {stats.rejected}</span>
          <span>Expired: {stats.expired}</span>
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        <label style={{ fontSize: 12 }}>Filter:</label>{' '}
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as ApprovalStatus | 'all')}>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="expired">Expired</option>
          <option value="all">All</option>
        </select>
      </div>

      {error && <div style={{ color: '#b00', marginTop: 8 }}>{error}</div>}
      {loading && <div style={{ marginTop: 12 }}>Loading…</div>}

      {!loading && approvals.length === 0 && (
        <div style={{ marginTop: 24, color: '#666' }}>No approvals in this state.</div>
      )}

      <ul style={{ listStyle: 'none', padding: 0, marginTop: 12 }}>
        {approvals.map((a) => (
          <li key={a.approval_id} style={{ border: '1px solid #ddd', borderRadius: 4, marginBottom: 12, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <strong>{a.title}</strong>{' '}
                <span style={{ color: '#888', fontSize: 12 }}>
                  [{a.approval_type}] [{a.status}] · {new Date(a.created_at).toLocaleString()}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#888' }}>{a.deployment_id}</div>
            </div>
            {a.description && (
              <div style={{ marginTop: 4, fontSize: 13 }}>{a.description}</div>
            )}
            {a.proposed_action && (
              <div style={{ marginTop: 4, fontSize: 13, fontStyle: 'italic' }}>
                Proposed: {a.proposed_action}
              </div>
            )}
            {a.approval_type === 'review' && a.content_to_review !== null && a.content_to_review !== undefined && (
              <textarea
                rows={4}
                style={{ width: '100%', marginTop: 8, fontFamily: 'monospace', fontSize: 12 }}
                value={editedContent[a.approval_id] ?? a.content_to_review ?? ''}
                onChange={(e) =>
                  setEditedContent((prev) => ({ ...prev, [a.approval_id]: e.target.value }))
                }
                disabled={a.status !== 'pending'}
              />
            )}
            {a.approval_type === 'choice' && a.options && (
              <div style={{ marginTop: 8 }}>
                {a.options.map((opt) => (
                  <label key={opt} style={{ display: 'block', fontSize: 13 }}>
                    <input
                      type="radio"
                      name={`opt-${a.approval_id}`}
                      value={opt}
                      disabled={a.status !== 'pending'}
                      checked={selectedOption[a.approval_id] === opt}
                      onChange={(e) =>
                        setSelectedOption((prev) => ({ ...prev, [a.approval_id]: e.target.value }))
                      }
                    />{' '}
                    {opt}
                  </label>
                ))}
              </div>
            )}
            {a.status === 'pending' && (
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <input
                  placeholder="Optional feedback"
                  value={feedback[a.approval_id] ?? ''}
                  onChange={(e) =>
                    setFeedback((prev) => ({ ...prev, [a.approval_id]: e.target.value }))
                  }
                  style={{ flex: 1 }}
                />
                <button onClick={() => resolve(a, 'approved')}>Approve</button>
                <button onClick={() => resolve(a, 'rejected')}>Reject</button>
              </div>
            )}
            {a.resolution && (
              <div style={{ marginTop: 8, fontSize: 12, color: '#555' }}>
                Resolved: {JSON.stringify(a.resolution)}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default ApprovalInbox;
