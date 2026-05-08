/**
 * Analytics panel (Task 04).
 *
 * Shown inside the DeployPanel's Analytics tab. Displays KPI cards and a
 * minimal inline bar chart for InvocationCount over the selected window.
 *
 * Metrics come from CloudWatch under AgentCore/Agents (emitted by the
 * generated agent code or manually via POST /api/analytics/.../record).
 *
 * Styled to match the AWS-console Tailwind look of the DeployPanel.
 */

import { useCallback, useEffect, useState } from 'react';
import type { AnalyticsSummary, TimeseriesPoint } from '../../services/analytics';
import { getSummary, getTimeseries } from '../../services/analytics';

interface Props {
  deploymentId: string;
  onClose?: () => void;
}

const selectCls =
  'rounded-md border border-[#e9ebed] bg-white px-2 py-1 text-xs text-[#16191f] ' +
  'focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30';

export function AnalyticsPanel({ deploymentId, onClose }: Props) {
  const [hours, setHours] = useState<number>(24);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [series, setSeries] = useState<TimeseriesPoint[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, ts] = await Promise.all([
        getSummary(deploymentId, hours),
        getTimeseries(deploymentId, 'InvocationCount', hours, 'Sum'),
      ]);
      setSummary(s);
      setSeries(ts.points);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  }, [deploymentId, hours]);

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 30_000); // 30s refresh
    return () => clearInterval(id);
  }, [refresh]);

  const maxValue = series && series.length > 0 ? Math.max(...series.map((p) => p.value)) : 0;

  return (
    <div className="p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-[#16191f]">Analytics</h2>
          <p className="text-xs text-[#5f6b7a] mt-0.5">
            Real-time metrics from CloudWatch. Refreshes every 30 seconds.
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close analytics"
            className="p-1.5 rounded-md text-[#5f6b7a] hover:bg-[#f2f3f3] transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </header>

      <div className="flex items-center gap-2">
        <label className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Window</label>
        <select
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className={selectCls}
        >
          <option value={1}>Last 1 hour</option>
          <option value={24}>Last 24 hours</option>
          <option value={24 * 7}>Last 7 days</option>
          <option value={24 * 30}>Last 30 days</option>
        </select>
        <button
          onClick={refresh}
          className="ml-auto px-2.5 py-1 text-xs font-medium rounded-md border border-[#e9ebed] bg-white text-[#16191f] hover:bg-[#f2f3f3] transition-colors"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {error}
        </div>
      )}

      {loading && !summary && (
        <div className="flex items-center gap-2 text-xs text-[#5f6b7a]">
          <div className="w-3 h-3 border-2 border-[#0972d3] border-t-transparent rounded-full animate-spin" />
          Loading metrics…
        </div>
      )}

      {summary && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Kpi label="Invocations" value={summary.invocations.toLocaleString()} />
            <Kpi
              label="Errors"
              value={`${summary.errors}`}
              note={`${summary.error_rate_pct.toFixed(1)}% error rate`}
              tone={summary.error_rate_pct > 0 ? 'warn' : 'ok'}
            />
            <Kpi
              label="Avg latency"
              value={`${summary.avg_latency_ms.toFixed(0)} ms`}
              note={`p95 ${summary.p95_latency_ms.toFixed(0)}ms · p99 ${summary.p99_latency_ms.toFixed(0)}ms`}
            />
            <Kpi
              label="Est. cost"
              value={`$${summary.estimated_cost_usd.toFixed(4)}`}
              note="approximate"
            />
            <Kpi label="Input tokens" value={summary.input_tokens.toLocaleString()} />
            <Kpi label="Output tokens" value={summary.output_tokens.toLocaleString()} />
          </div>

          <section className="rounded-xl border border-[#e9ebed] bg-white p-3.5 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-medium text-[#16191f]">Invocations over time</div>
              <div className="text-[10px] text-[#8d99a8]">peak: {maxValue.toLocaleString()}</div>
            </div>
            {series && series.length === 0 && (
              <div className="text-xs text-[#8d99a8]">No data in this window.</div>
            )}
            {series && series.length > 0 && (
              <div className="flex items-end gap-0.5 h-24 border-b border-[#e9ebed]">
                {series.map((p) => {
                  const pct = maxValue > 0 ? (p.value / maxValue) * 100 : 0;
                  return (
                    <div
                      key={p.timestamp}
                      title={`${new Date(p.timestamp).toLocaleString()}\n${p.value}`}
                      className="flex-1 bg-[#0972d3] hover:bg-[#0961b9] transition-colors rounded-t"
                      style={{
                        height: `${pct}%`,
                        minHeight: p.value > 0 ? 2 : 0,
                      }}
                    />
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: 'ok' | 'warn';
}) {
  const borderCls =
    tone === 'warn'
      ? 'border-amber-200 bg-amber-50/60'
      : 'border-[#e9ebed] bg-white';
  return (
    <div className={`rounded-xl border ${borderCls} p-3 shadow-sm`}>
      <div className="text-[10px] uppercase tracking-wide text-[#5f6b7a]">{label}</div>
      <div className="text-lg font-semibold text-[#16191f] mt-0.5">{value}</div>
      {note && <div className="text-[10px] text-[#8d99a8] mt-0.5">{note}</div>}
    </div>
  );
}

export default AnalyticsPanel;
