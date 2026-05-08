/**
 * Triggers management panel for a deployed agent (Task 01).
 *
 * Shows:
 *   - list of existing triggers for this deployment
 *   - "add trigger" form (schedule | webhook | event)
 *   - quick enable/disable + delete + test
 *   - execution history (last 100)
 *
 * Styled to match the AWS-console Tailwind look of the DeployPanel.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  SCHEDULE_PRESETS,
  type TriggerConfig,
  type TriggerCreateRequest,
  type TriggerInvocationRecord,
  type TriggerType,
  createTrigger,
  deleteTrigger,
  getTriggerHistory,
  getWebhookSecret,
  listTriggers,
  testTrigger,
  updateTrigger,
  webhookUrl,
} from '../../services/triggers';

interface Props {
  deploymentId: string;
  runtimeId?: string | null;
  apiBaseUrl: string;
  onClose: () => void;
}

const DEFAULT_INPUT_TEMPLATE = 'Scheduled run: {event}';

const inputCls =
  'w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm text-[#16191f] ' +
  'focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30 placeholder-[#8d99a8]';
const selectCls =
  'rounded-md border border-[#e9ebed] bg-white px-2 py-1.5 text-sm text-[#16191f] ' +
  'focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30';
const btnSecondaryCls =
  'px-2.5 py-1 text-xs font-medium rounded-md border border-[#e9ebed] bg-white text-[#16191f] ' +
  'hover:bg-[#f2f3f3] transition-colors';
const btnDangerCls =
  'px-2.5 py-1 text-xs font-medium rounded-md border border-red-200 bg-white text-red-600 ' +
  'hover:bg-red-50 transition-colors';
const btnPrimaryCls =
  'inline-flex items-center gap-1.5 rounded-md bg-[#ff9900] px-3 py-1.5 text-sm font-semibold text-[#232f3e] ' +
  'hover:bg-[#ec7211] disabled:bg-[#e9ebed] disabled:text-[#8d99a8] disabled:cursor-not-allowed transition-colors';

export function TriggersPanel({ deploymentId, runtimeId, apiBaseUrl, onClose }: Props) {
  const [triggers, setTriggers] = useState<TriggerConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [history, setHistory] = useState<Record<string, TriggerInvocationRecord[]>>({});
  const [revealedSecret, setRevealedSecret] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const t = await listTriggers(deploymentId);
      setTriggers(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load triggers');
    } finally {
      setLoading(false);
    }
  }, [deploymentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleExpand = useCallback(
    async (id: string) => {
      if (expandedId === id) {
        setExpandedId(null);
        return;
      }
      setExpandedId(id);
      if (!history[id]) {
        try {
          const h = await getTriggerHistory(id);
          setHistory((prev) => ({ ...prev, [id]: h }));
        } catch {
          setHistory((prev) => ({ ...prev, [id]: [] }));
        }
      }
    },
    [expandedId, history],
  );

  return (
    <div className="p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-[#16191f]">Triggers</h2>
          <p className="text-xs text-[#5f6b7a] mt-0.5">
            Schedule runs, expose a webhook URL, or fire this agent from AWS events.
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close triggers"
          className="p-1.5 rounded-md text-[#5f6b7a] hover:bg-[#f2f3f3] transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </header>

      <NewTriggerForm
        deploymentId={deploymentId}
        runtimeId={runtimeId ?? undefined}
        onCreated={refresh}
      />

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
          Loading triggers…
        </div>
      )}

      {!loading && triggers.length === 0 && (
        <div className="rounded-xl border border-dashed border-[#e9ebed] bg-[#fafafa] p-6 text-center">
          <div className="text-sm text-[#16191f] font-medium mb-1">No triggers yet</div>
          <div className="text-xs text-[#5f6b7a]">
            Create one above to schedule runs or expose a webhook.
          </div>
        </div>
      )}

      <ul className="space-y-2">
        {triggers.map((t) => (
          <li
            key={t.trigger_id}
            className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-sm font-semibold text-[#16191f] truncate">{t.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#0972d3]/10 text-[#0972d3] font-medium uppercase tracking-wide">
                    {t.trigger_type}
                  </span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                      t.enabled
                        ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                        : 'bg-[#f2f3f3] text-[#5f6b7a] border border-[#e9ebed]'
                    }`}
                  >
                    {t.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                  <span className="text-[11px] text-[#5f6b7a]">fired {t.trigger_count}×</span>
                </div>
                {t.trigger_type === 'schedule' && t.schedule_expression && (
                  <div className="mt-1 text-xs text-[#5f6b7a] font-mono">{t.schedule_expression}</div>
                )}
                {t.trigger_type === 'webhook' && t.webhook_path && (
                  <code className="mt-1 block text-[11px] text-[#0972d3] break-all">
                    {webhookUrl(apiBaseUrl, t.webhook_path)}
                  </code>
                )}
                {t.last_error && (
                  <div className="mt-1 text-[11px] text-red-600">Last error: {t.last_error}</div>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5 flex-shrink-0 justify-end">
                <button
                  className={btnSecondaryCls}
                  onClick={async () => {
                    try {
                      await updateTrigger(t.trigger_id, { enabled: !t.enabled });
                      await refresh();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : 'failed');
                    }
                  }}
                >
                  {t.enabled ? 'Disable' : 'Enable'}
                </button>
                <button
                  className={btnSecondaryCls}
                  onClick={async () => {
                    try {
                      const r = await testTrigger(t.trigger_id);
                      alert(
                        `invocation ${r.invocation_id}: ${r.status}${r.error ? ` — ${r.error}` : ''}`,
                      );
                      await refresh();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : 'failed');
                    }
                  }}
                >
                  Test
                </button>
                <button
                  className={btnSecondaryCls}
                  onClick={() => handleExpand(t.trigger_id)}
                  aria-expanded={expandedId === t.trigger_id}
                >
                  {expandedId === t.trigger_id ? 'Hide history' : 'History'}
                </button>
                {t.trigger_type === 'webhook' && (
                  <button
                    className={btnSecondaryCls}
                    onClick={async () => {
                      try {
                        const s = await getWebhookSecret(t.trigger_id);
                        setRevealedSecret((prev) => ({ ...prev, [t.trigger_id]: s.secret }));
                      } catch (e) {
                        setError(e instanceof Error ? e.message : 'failed');
                      }
                    }}
                  >
                    Secret
                  </button>
                )}
                <button
                  className={btnDangerCls}
                  onClick={async () => {
                    if (!confirm(`Delete trigger "${t.name}"?`)) return;
                    try {
                      await deleteTrigger(t.trigger_id);
                      await refresh();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : 'failed');
                    }
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
            {revealedSecret[t.trigger_id] && (
              <div className="mt-3 rounded-md bg-[#f2f3f3] border border-[#e9ebed] p-2">
                <div className="text-[10px] uppercase tracking-wide text-[#5f6b7a] mb-0.5">
                  Webhook secret
                </div>
                <code className="text-[11px] font-mono text-[#16191f] break-all block">
                  {revealedSecret[t.trigger_id]}
                </code>
                <div className="text-[10px] text-[#5f6b7a] mt-1">
                  Send as: <code className="text-[#d45b07]">X-AgentCore-Signature: sha256=&lt;HMAC-SHA256(body, secret)&gt;</code>
                </div>
              </div>
            )}
            {expandedId === t.trigger_id && (
              <HistoryList invocations={history[t.trigger_id] || []} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function HistoryList({ invocations }: { invocations: TriggerInvocationRecord[] }) {
  if (invocations.length === 0) {
    return (
      <div className="mt-3 rounded-md bg-[#fafafa] border border-[#e9ebed] p-3 text-xs text-[#5f6b7a]">
        No invocations yet.
      </div>
    );
  }
  return (
    <div className="mt-3 rounded-md border border-[#e9ebed] overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-[#f2f3f3] text-[#5f6b7a] text-left">
            <th className="px-2 py-1.5 font-medium">When</th>
            <th className="px-2 py-1.5 font-medium">Source</th>
            <th className="px-2 py-1.5 font-medium">Status</th>
            <th className="px-2 py-1.5 font-medium">Duration</th>
            <th className="px-2 py-1.5 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {invocations.map((i) => (
            <tr key={i.invocation_id} className="border-t border-[#e9ebed] text-[#16191f]">
              <td className="px-2 py-1.5">{new Date(i.invoked_at).toLocaleString()}</td>
              <td className="px-2 py-1.5">{i.source}</td>
              <td
                className={`px-2 py-1.5 font-medium ${
                  i.status === 'success' ? 'text-emerald-700' : 'text-red-600'
                }`}
              >
                {i.status}
              </td>
              <td className="px-2 py-1.5">{i.duration_ms ?? '-'}ms</td>
              <td className="px-2 py-1.5 text-[#5f6b7a] truncate max-w-[120px]" title={i.error || i.input_payload_preview || ''}>
                {i.error || i.input_payload_preview || ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NewTriggerForm({
  deploymentId,
  runtimeId,
  onCreated,
}: {
  deploymentId: string;
  runtimeId?: string;
  onCreated: () => void;
}) {
  const [type, setType] = useState<TriggerType>('schedule');
  const [name, setName] = useState('');
  const [scheduleExpression, setScheduleExpression] = useState(SCHEDULE_PRESETS[2].expression);
  const [webhookPath, setWebhookPath] = useState('');
  const [eventPattern, setEventPattern] = useState('{"source": ["aws.s3"]}');
  const [inputTemplate, setInputTemplate] = useState(DEFAULT_INPUT_TEMPLATE);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const canSubmit = useMemo(() => {
    if (!name.trim()) return false;
    if (type === 'schedule') return !!scheduleExpression.trim();
    if (type === 'webhook') return !!webhookPath.trim() && /^[a-zA-Z0-9_-]{1,64}$/.test(webhookPath);
    if (type === 'event') return !!eventPattern.trim();
    return false;
  }, [name, type, scheduleExpression, webhookPath, eventPattern]);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const req: TriggerCreateRequest = {
        deployment_id: deploymentId,
        runtime_id: runtimeId,
        trigger_type: type,
        name: name.trim(),
        input_template: inputTemplate || undefined,
      };
      if (type === 'schedule') req.schedule_expression = scheduleExpression;
      if (type === 'webhook') req.webhook_path = webhookPath;
      if (type === 'event') {
        try {
          req.event_pattern = JSON.parse(eventPattern);
        } catch {
          setErr('event_pattern must be valid JSON');
          setBusy(false);
          return;
        }
      }
      await createTrigger(req);
      setName('');
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-[#e9ebed] bg-white p-4 shadow-sm space-y-2.5">
      <h3 className="text-sm font-semibold text-[#16191f]">New trigger</h3>
      <div className="flex gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value as TriggerType)}
          className={selectCls}
        >
          <option value="schedule">Schedule</option>
          <option value="webhook">Webhook</option>
          <option value="event">Event</option>
        </select>
        <input
          placeholder="Trigger name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputCls + ' flex-1'}
        />
      </div>

      {type === 'schedule' && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <label className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Preset</label>
            <select
              className={selectCls + ' flex-1'}
              value=""
              onChange={(e) => {
                if (e.target.value) setScheduleExpression(e.target.value);
              }}
            >
              <option value="">— select —</option>
              {SCHEDULE_PRESETS.map((p) => (
                <option key={p.expression} value={p.expression}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <input
            className={inputCls + ' font-mono text-xs'}
            placeholder="cron(0 9 * * ? *) or rate(1 hour)"
            value={scheduleExpression}
            onChange={(e) => setScheduleExpression(e.target.value)}
          />
        </div>
      )}

      {type === 'webhook' && (
        <input
          className={inputCls}
          placeholder="webhook-path (alphanumeric, _ -)"
          value={webhookPath}
          onChange={(e) => setWebhookPath(e.target.value)}
        />
      )}

      {type === 'event' && (
        <textarea
          rows={4}
          className={inputCls + ' font-mono text-xs resize-y'}
          placeholder='{"source": ["aws.s3"]}'
          value={eventPattern}
          onChange={(e) => setEventPattern(e.target.value)}
        />
      )}

      <div>
        <label className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
          Input template (available var: {`{event}`})
        </label>
        <input
          className={inputCls + ' mt-1'}
          value={inputTemplate}
          onChange={(e) => setInputTemplate(e.target.value)}
        />
      </div>

      {err && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-700"
        >
          {err}
        </div>
      )}

      <button disabled={!canSubmit || busy} onClick={submit} className={btnPrimaryCls}>
        {busy ? (
          <>
            <div className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
            Creating…
          </>
        ) : (
          'Create trigger'
        )}
      </button>
    </section>
  );
}

export default TriggersPanel;
