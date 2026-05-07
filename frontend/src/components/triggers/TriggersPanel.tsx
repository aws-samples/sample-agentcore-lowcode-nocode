/**
 * Triggers management panel for a deployed agent (Task 01).
 *
 * Shows:
 *   - list of existing triggers for this deployment
 *   - "add trigger" form (schedule | webhook | event)
 *   - quick enable/disable + delete + test
 *   - execution history (last 100)
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
    <div className="triggers-panel" style={{ padding: 16 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Triggers</h2>
        <button onClick={onClose} aria-label="close">✕</button>
      </header>
      <p style={{ color: '#555', fontSize: 13 }}>
        Schedule runs, expose a webhook URL, or fire this agent from AWS events.
      </p>

      <NewTriggerForm
        deploymentId={deploymentId}
        runtimeId={runtimeId ?? undefined}
        onCreated={refresh}
      />

      {error && (
        <div role="alert" style={{ color: '#b00', marginTop: 12 }}>{error}</div>
      )}

      {loading && <div>Loading…</div>}

      {!loading && triggers.length === 0 && (
        <div style={{ marginTop: 16, color: '#666' }}>No triggers yet.</div>
      )}

      <ul style={{ listStyle: 'none', padding: 0, marginTop: 16 }}>
        {triggers.map((t) => (
          <li key={t.trigger_id} style={{ border: '1px solid #ddd', borderRadius: 4, marginBottom: 8, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>{t.name}</strong>{' '}
                <span style={{ color: '#888', fontSize: 12 }}>
                  [{t.trigger_type}] {t.enabled ? 'enabled' : 'disabled'} · fired {t.trigger_count}×
                </span>
                {t.trigger_type === 'schedule' && t.schedule_expression && (
                  <div style={{ fontSize: 12, color: '#555' }}>{t.schedule_expression}</div>
                )}
                {t.trigger_type === 'webhook' && t.webhook_path && (
                  <div style={{ fontSize: 12, color: '#555' }}>
                    <code>{webhookUrl(apiBaseUrl, t.webhook_path)}</code>
                  </div>
                )}
                {t.last_error && (
                  <div style={{ fontSize: 12, color: '#b00' }}>Last error: {t.last_error}</div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
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
                  onClick={() => handleExpand(t.trigger_id)}
                  aria-expanded={expandedId === t.trigger_id}
                >
                  {expandedId === t.trigger_id ? 'Hide history' : 'History'}
                </button>
                {t.trigger_type === 'webhook' && (
                  <button
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
              <div style={{ fontSize: 12, marginTop: 8 }}>
                <code style={{ wordBreak: 'break-all' }}>{revealedSecret[t.trigger_id]}</code>
                <div style={{ color: '#888' }}>
                  Send as: <code>X-AgentCore-Signature: sha256=&lt;HMAC-SHA256(body, secret)&gt;</code>
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
    return <div style={{ marginTop: 8, color: '#666', fontSize: 13 }}>No invocations yet.</div>;
  }
  return (
    <table style={{ marginTop: 8, width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
      <thead>
        <tr style={{ textAlign: 'left', color: '#555' }}>
          <th>When</th>
          <th>Source</th>
          <th>Status</th>
          <th>Duration</th>
          <th>Detail</th>
        </tr>
      </thead>
      <tbody>
        {invocations.map((i) => (
          <tr key={i.invocation_id}>
            <td>{new Date(i.invoked_at).toLocaleString()}</td>
            <td>{i.source}</td>
            <td style={{ color: i.status === 'success' ? '#080' : '#b00' }}>{i.status}</td>
            <td>{i.duration_ms ?? '-'}ms</td>
            <td>{i.error || i.input_payload_preview || ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
    <section style={{ border: '1px solid #eee', padding: 12, marginTop: 12, borderRadius: 4 }}>
      <h3 style={{ margin: '0 0 8px 0', fontSize: 14 }}>New trigger</h3>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <select value={type} onChange={(e) => setType(e.target.value as TriggerType)}>
          <option value="schedule">Schedule</option>
          <option value="webhook">Webhook</option>
          <option value="event">Event</option>
        </select>
        <input
          placeholder="Trigger name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ flex: 1, minWidth: 120 }}
        />
      </div>

      {type === 'schedule' && (
        <div style={{ marginTop: 8 }}>
          <label style={{ display: 'block', fontSize: 12 }}>
            Preset
            <select
              style={{ marginLeft: 8 }}
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
          </label>
          <input
            style={{ marginTop: 4, width: '100%' }}
            placeholder="cron(0 9 * * ? *) or rate(1 hour)"
            value={scheduleExpression}
            onChange={(e) => setScheduleExpression(e.target.value)}
          />
        </div>
      )}

      {type === 'webhook' && (
        <div style={{ marginTop: 8 }}>
          <input
            style={{ width: '100%' }}
            placeholder="webhook-path (alphanumeric, _ -)"
            value={webhookPath}
            onChange={(e) => setWebhookPath(e.target.value)}
          />
        </div>
      )}

      {type === 'event' && (
        <div style={{ marginTop: 8 }}>
          <textarea
            rows={4}
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }}
            placeholder='{"source": ["aws.s3"]}'
            value={eventPattern}
            onChange={(e) => setEventPattern(e.target.value)}
          />
        </div>
      )}

      <div style={{ marginTop: 8 }}>
        <label style={{ fontSize: 12 }}>Input template (available var: {`{event}`})</label>
        <input
          style={{ width: '100%' }}
          value={inputTemplate}
          onChange={(e) => setInputTemplate(e.target.value)}
        />
      </div>

      {err && <div style={{ color: '#b00', marginTop: 8 }}>{err}</div>}

      <button
        disabled={!canSubmit || busy}
        onClick={submit}
        style={{ marginTop: 8 }}
      >
        {busy ? 'Creating…' : 'Create trigger'}
      </button>
    </section>
  );
}

export default TriggersPanel;
