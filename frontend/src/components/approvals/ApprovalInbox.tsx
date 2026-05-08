/**
 * Approval Inbox (Task 02).
 *
 * Lists pending approvals for the caller, with quick approve/reject actions
 * and support for binary/choice/form/review approval types.
 *
 * Styled to match the AWS-console Tailwind look of the DeployPanel.
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

const inputCls =
  'w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm text-[#16191f] ' +
  'focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30 placeholder-[#8d99a8]';
const selectCls =
  'rounded-md border border-[#e9ebed] bg-white px-2 py-1 text-xs text-[#16191f] ' +
  'focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30';
const btnApproveCls =
  'px-3 py-1.5 text-xs font-semibold rounded-md border border-emerald-600 bg-emerald-600 text-white ' +
  'hover:bg-emerald-700 transition-colors';
const btnRejectCls =
  'px-3 py-1.5 text-xs font-semibold rounded-md border border-red-500 bg-white text-red-600 ' +
  'hover:bg-red-50 transition-colors';

function StatsBadge({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'warn' }) {
  const valueCls =
    tone === 'warn' && value > 0 ? 'text-[#d45b07]' : 'text-[#16191f]';
  return (
    <div className="rounded-lg border border-[#e9ebed] bg-white px-3 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-[#5f6b7a]">{label}</div>
      <div className={`text-sm font-semibold ${valueCls}`}>{value}</div>
    </div>
  );
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
    <div className="flex flex-col h-full bg-white">
      <header className="flex items-center justify-between px-4 py-3 border-b border-[#e9ebed] bg-[#232f3e]">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-md bg-[#ff9900] flex items-center justify-center">
            <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 12l2 2 4-4" />
              <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
              <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              <path d="M3 5c0-1.66 4-3 9-3s9 1.34 9 3" />
            </svg>
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white">Approval Inbox</h2>
            <p className="text-[11px] text-white/50">Human-in-the-loop decisions</p>
          </div>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close approval inbox"
            className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
          >
            <svg className="w-4 h-4 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {stats && (
          <div className="grid grid-cols-4 gap-2">
            <StatsBadge label="Pending" value={stats.pending} tone="warn" />
            <StatsBadge label="Approved" value={stats.approved} />
            <StatsBadge label="Rejected" value={stats.rejected} />
            <StatsBadge label="Expired" value={stats.expired} />
          </div>
        )}

        <div className="flex items-center gap-2">
          <label className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Filter</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as ApprovalStatus | 'all')}
            className={selectCls}
          >
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="expired">Expired</option>
            <option value="all">All</option>
          </select>
        </div>

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
            Loading…
          </div>
        )}

        {!loading && approvals.length === 0 && (
          <div className="rounded-xl border border-dashed border-[#e9ebed] bg-[#fafafa] p-8 text-center">
            <div className="text-sm text-[#16191f] font-medium mb-1">All clear</div>
            <div className="text-xs text-[#5f6b7a]">No approvals in this state.</div>
          </div>
        )}

        <ul className="space-y-3">
          {approvals.map((a) => {
            const statusColor =
              a.status === 'pending'
                ? 'bg-[#ff9900]/10 text-[#d45b07] border-[#ff9900]/40'
                : a.status === 'approved'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : a.status === 'rejected'
                    ? 'bg-red-50 text-red-700 border-red-200'
                    : 'bg-[#f2f3f3] text-[#5f6b7a] border-[#e9ebed]';
            return (
              <li
                key={a.approval_id}
                className="rounded-xl border border-[#e9ebed] bg-white p-3.5 shadow-sm space-y-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-semibold text-[#16191f]">{a.title}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#0972d3]/10 text-[#0972d3] font-medium uppercase tracking-wide">
                        {a.approval_type}
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium uppercase tracking-wide ${statusColor}`}>
                        {a.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-[#5f6b7a] mt-1">
                      {new Date(a.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="text-[10px] text-[#8d99a8] truncate max-w-[140px]" title={a.deployment_id}>
                    {a.deployment_id}
                  </div>
                </div>

                {a.description && (
                  <div className="text-sm text-[#16191f]">{a.description}</div>
                )}
                {a.proposed_action && (
                  <div className="rounded-md bg-[#fafafa] border border-[#e9ebed] p-2 text-xs text-[#16191f]">
                    <span className="text-[10px] uppercase tracking-wide text-[#5f6b7a] mr-1">Proposed</span>
                    <span className="italic">{a.proposed_action}</span>
                  </div>
                )}

                {a.approval_type === 'review' && a.content_to_review !== null && a.content_to_review !== undefined && (
                  <textarea
                    rows={4}
                    className={inputCls + ' font-mono text-xs resize-y'}
                    value={editedContent[a.approval_id] ?? a.content_to_review ?? ''}
                    onChange={(e) =>
                      setEditedContent((prev) => ({ ...prev, [a.approval_id]: e.target.value }))
                    }
                    disabled={a.status !== 'pending'}
                  />
                )}
                {a.approval_type === 'choice' && a.options && (
                  <div className="space-y-1">
                    {a.options.map((opt) => (
                      <label
                        key={opt}
                        className="flex items-center gap-2 text-sm text-[#16191f] rounded-md border border-[#e9ebed] px-2.5 py-1.5 hover:bg-[#fafafa] cursor-pointer"
                      >
                        <input
                          type="radio"
                          name={`opt-${a.approval_id}`}
                          value={opt}
                          disabled={a.status !== 'pending'}
                          checked={selectedOption[a.approval_id] === opt}
                          onChange={(e) =>
                            setSelectedOption((prev) => ({ ...prev, [a.approval_id]: e.target.value }))
                          }
                          className="accent-[#0972d3]"
                        />
                        <span>{opt}</span>
                      </label>
                    ))}
                  </div>
                )}
                {a.status === 'pending' && (
                  <div className="flex items-center gap-2">
                    <input
                      placeholder="Optional feedback"
                      value={feedback[a.approval_id] ?? ''}
                      onChange={(e) =>
                        setFeedback((prev) => ({ ...prev, [a.approval_id]: e.target.value }))
                      }
                      className={inputCls + ' flex-1'}
                    />
                    <button onClick={() => resolve(a, 'approved')} className={btnApproveCls}>
                      Approve
                    </button>
                    <button onClick={() => resolve(a, 'rejected')} className={btnRejectCls}>
                      Reject
                    </button>
                  </div>
                )}
                {a.resolution && (
                  <div className="rounded-md bg-[#fafafa] border border-[#e9ebed] p-2 text-[11px] text-[#5f6b7a]">
                    <span className="uppercase tracking-wide mr-1 text-[10px]">Resolved</span>
                    <code className="font-mono text-[11px] text-[#16191f] break-all">
                      {JSON.stringify(a.resolution)}
                    </code>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

export default ApprovalInbox;
