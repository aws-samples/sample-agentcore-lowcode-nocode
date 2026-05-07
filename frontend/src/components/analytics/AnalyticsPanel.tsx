/**
 * Analytics panel (Task 04).
 *
 * Shown inside the DeployPanel's Analytics tab. Displays KPI cards and a
 * minimal inline bar chart for InvocationCount over the selected window.
 *
 * Metrics come from CloudWatch under AgentCore/Agents (emitted by the
 * generated agent code or manually via POST /api/analytics/.../record).
 */

import { useCallback, useEffect, useState } from 'react';
import type { AnalyticsSummary, TimeseriesPoint } from '../../services/analytics';
import { getSummary, getTimeseries } from '../../services/analytics';

interface Props {
  deploymentId: string;
  onClose?: () => void;
}

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
    <div style={{ padding: 16 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Analytics</h2>
        {onClose && <button onClick={onClose}>✕</button>}
      </header>

      <div style={{ marginTop: 8 }}>
        <label style={{ fontSize: 12 }}>Window:</label>{' '}
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={1}>Last 1 hour</option>
          <option value={24}>Last 24 hours</option>
          <option value={24 * 7}>Last 7 days</option>
          <option value={24 * 30}>Last 30 days</option>
        </select>
        <button onClick={refresh} style={{ marginLeft: 8 }}>Refresh</button>
      </div>

      {error && <div style={{ color: '#b00', marginTop: 8 }}>{error}</div>}
      {loading && !summary && <div style={{ marginTop: 12 }}>Loading…</div>}

      {summary && (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
              gap: 8,
              marginTop: 12,
            }}
          >
            <Kpi label="Invocations" value={summary.invocations.toLocaleString()} />
            <Kpi label="Errors" value={`${summary.errors} (${summary.error_rate_pct.toFixed(1)}%)`} />
            <Kpi
              label="Avg latency"
              value={`${summary.avg_latency_ms.toFixed(0)} ms`}
              note={`p95 ${summary.p95_latency_ms.toFixed(0)} · p99 ${summary.p99_latency_ms.toFixed(0)}`}
            />
            <Kpi label="Input tokens" value={summary.input_tokens.toLocaleString()} />
            <Kpi label="Output tokens" value={summary.output_tokens.toLocaleString()} />
            <Kpi
              label="Estimated cost"
              value={`$${summary.estimated_cost_usd.toFixed(4)}`}
              note="approximate"
            />
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, color: '#555' }}>Invocations over time</div>
            {series && series.length === 0 && (
              <div style={{ color: '#888', fontSize: 12, marginTop: 6 }}>No data in this window.</div>
            )}
            {series && series.length > 0 && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-end',
                  gap: 2,
                  height: 100,
                  marginTop: 6,
                  borderBottom: '1px solid #ddd',
                }}
              >
                {series.map((p) => {
                  const pct = maxValue > 0 ? (p.value / maxValue) * 100 : 0;
                  return (
                    <div
                      key={p.timestamp}
                      title={`${new Date(p.timestamp).toLocaleString()}\n${p.value}`}
                      style={{
                        flex: 1,
                        background: '#0972d3',
                        height: `${pct}%`,
                        minHeight: p.value > 0 ? 2 : 0,
                      }}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div style={{ border: '1px solid #e9ebed', borderRadius: 4, padding: 10 }}>
      <div style={{ fontSize: 11, color: '#555' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, marginTop: 2 }}>{value}</div>
      {note && <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>{note}</div>}
    </div>
  );
}

export default AnalyticsPanel;
