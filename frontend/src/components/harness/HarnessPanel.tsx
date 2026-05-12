/**
 * HarnessPanel — the body of the Harness management UI.
 *
 * Rendered inside two places:
 *   - the standalone HarnessManager drawer (legacy entry)
 *   - the AgentCoreManager "Harness" tab (the new home)
 *
 * Exposes the full AgentCore Harness surface we support:
 *   description, model w/ topK + stop sequences, built-in tools, memory,
 *   guardrail, knowledge base, observability, lifecycle, network mode,
 *   plus invoke chat against a READY harness. One-click "Publish to
 *   Registry" lives next to each row.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  type HarnessCreateRequest,
  type HarnessRecord,
  type HarnessStatus,
  createHarness,
  deleteHarness,
  getHarness,
  harnessRegion,
  invokeHarness,
  listHarnesses,
} from '../../services/harness';
import { PublishToRegistryModal } from '../registry/PublishToRegistryModal';
import { useRole } from '../../context/RoleContext';

const DEFAULT_MODEL = 'us.anthropic.claude-sonnet-4-5-20250929-v1:0';

// Latest Bedrock models (us-east-1 inference profiles verified live 2026-05).
const BEDROCK_MODELS = [
  'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
  'us.anthropic.claude-opus-4-5-20251101-v1:0',
  'us.anthropic.claude-haiku-4-5-20251001-v1:0',
  'us.amazon.nova-premier-v1:0',
  'us.amazon.nova-pro-v1:0',
  'us.amazon.nova-lite-v1:0',
  'us.amazon.nova-micro-v1:0',
];

const statusChip = (s: HarnessStatus): string => {
  if (s === 'READY') return 'bg-emerald-500 text-white';
  if (s === 'CREATING' || s === 'UPDATING' || s === 'DELETING')
    return 'bg-[#ff9900]/20 text-[#d45b07] border border-[#ff9900]/40';
  return 'bg-red-50 text-red-700 border border-red-200';
};

interface Props {
  /** Height of the scrollable body. Parent sets flex so we just fill. */
  className?: string;
}

export function HarnessPanel({ className }: Props) {
  const [list, setList] = useState<HarnessRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [regionMeta, setRegionMeta] = useState<{
    region: string;
    available: boolean;
    supported_regions: string[];
  } | null>(null);
  const [mode, setMode] = useState<'list' | 'create' | 'invoke'>('list');
  const [selected, setSelected] = useState<HarnessRecord | null>(null);
  const [publishFor, setPublishFor] = useState<HarnessRecord | null>(null);
  const { has: hasPermission } = useRole();
  const canPublishToRegistry = hasPermission('registry:publish');

  // Invoke state
  const [prompt, setPrompt] = useState('');
  const [invokeOutput, setInvokeOutput] = useState<
    { role: 'user' | 'assistant'; text: string }[]
  >([]);
  const [invoking, setInvoking] = useState(false);

  // Create form state
  const [form, setForm] = useState<HarnessCreateRequest>({
    harness_name: '',
    description: '',
    model: { bedrock: { model_id: DEFAULT_MODEL } },
    system_prompt: 'You are a helpful assistant.',
    tools: [],
    allowed_tools: ['*'],
    max_iterations: 20,
    timeout_seconds: 300,
    observability: { traces_enabled: true, metrics_enabled: true },
    lifecycle: { idle_runtime_session_timeout: 900, max_lifetime: 28_800 },
  });
  const [customModel, setCustomModel] = useState('');
  const [includeCodeInterpreter, setIncludeCodeInterpreter] = useState(false);
  const [includeBrowser, setIncludeBrowser] = useState(false);
  const [gatewayArn, setGatewayArn] = useState('');
  const [memoryArn, setMemoryArn] = useState('');
  const [guardrailId, setGuardrailId] = useState('');
  const [guardrailVersion, setGuardrailVersion] = useState('DRAFT');
  const [kbIdsCsv, setKbIdsCsv] = useState('');
  const [stopSeqsCsv, setStopSeqsCsv] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setList(await listHarnesses());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void harnessRegion().then(setRegionMeta).catch(() => setRegionMeta(null));
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const pending = list.filter(
      (h) =>
        !['READY', 'CREATE_FAILED', 'UPDATE_FAILED', 'DELETE_FAILED'].includes(
          h.status,
        ),
    );
    if (pending.length === 0) return;
    const id = setInterval(async () => {
      for (const h of pending) {
        try {
          const fresh = await getHarness(h.harness_id, true);
          setList((prev) =>
            prev.map((p) => (p.harness_id === h.harness_id ? fresh : p)),
          );
        } catch {
          // keep previous
        }
      }
    }, 7000);
    return () => clearInterval(id);
  }, [list]);

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      const tools: HarnessCreateRequest['tools'] = [];
      if (includeCodeInterpreter) tools!.push({ type: 'agentcore_code_interpreter' });
      if (includeBrowser) tools!.push({ type: 'agentcore_browser' });
      if (gatewayArn.trim())
        tools!.push({ type: 'agentcore_gateway', gateway_arn: gatewayArn.trim() });

      const body: HarnessCreateRequest = {
        ...form,
        model: customModel
          ? { bedrock: { model_id: customModel.trim() } }
          : form.model,
        description: form.description?.trim() || undefined,
        tools: tools && tools.length ? tools : undefined,
      };
      if (memoryArn.trim()) {
        body.memory = { memory_arn: memoryArn.trim() };
      }
      if (guardrailId.trim()) {
        body.guardrail = {
          guardrail_identifier: guardrailId.trim(),
          version: guardrailVersion.trim() || 'DRAFT',
        };
      }
      const kbList = kbIdsCsv
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      if (kbList.length) {
        body.knowledge_base = { knowledge_base_ids: kbList };
      }
      const stopList = stopSeqsCsv
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      if (stopList.length && body.model.bedrock) {
        body.model = {
          bedrock: { ...body.model.bedrock, stop_sequences: stopList },
        };
      }

      const rec = await createHarness(body);
      setList((prev) => [rec, ...prev]);
      setMode('list');
      setForm((f) => ({ ...f, harness_name: '', description: '' }));
      setGatewayArn('');
      setMemoryArn('');
      setGuardrailId('');
      setKbIdsCsv('');
      setStopSeqsCsv('');
      setCustomModel('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  };

  const handleInvoke = async () => {
    if (!selected || !prompt.trim()) return;
    setInvoking(true);
    setError(null);
    const userText = prompt;
    setInvokeOutput((prev) => [...prev, { role: 'user', text: userText }]);
    setPrompt('');
    try {
      const r = await invokeHarness(selected.harness_id, userText);
      if (r.success) {
        setInvokeOutput((prev) => [
          ...prev,
          { role: 'assistant', text: r.response || '(empty)' },
        ]);
      } else {
        setInvokeOutput((prev) => [
          ...prev,
          { role: 'assistant', text: `error: ${r.error}` },
        ]);
      }
    } catch (e) {
      setInvokeOutput((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `error: ${e instanceof Error ? e.message : 'failed'}`,
        },
      ]);
    } finally {
      setInvoking(false);
    }
  };

  const handleDelete = async (h: HarnessRecord) => {
    if (!confirm(`Delete harness "${h.name}"?`)) return;
    try {
      await deleteHarness(h.harness_id);
      setList((prev) => prev.filter((x) => x.harness_id !== h.harness_id));
      if (selected?.harness_id === h.harness_id) {
        setSelected(null);
        setMode('list');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  };

  const canCreate = useMemo(
    () =>
      /^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(form.harness_name) &&
      (!!customModel.trim() || !!form.model.bedrock?.model_id),
    [form.harness_name, form.model.bedrock, customModel],
  );

  const useCustom = customModel.trim().length > 0;

  return (
    <div className={className}>
      {regionMeta && !regionMeta.available && (
        <div className="m-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          AgentCore Harness is not available in{' '}
          <strong>{regionMeta.region}</strong>. Supported regions:{' '}
          {regionMeta.supported_regions.join(', ')}.
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="m-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {error}
        </div>
      )}

      {mode === 'list' && (
        <section className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-xs text-[#5f6b7a]">
              {list.length} harness{list.length === 1 ? '' : 'es'}
            </div>
            <div className="flex gap-2">
              <button
                className="px-2.5 py-1 text-xs font-medium rounded-md border border-[#e9ebed] bg-white text-[#16191f] hover:bg-[#f2f3f3]"
                onClick={refresh}
              >
                Refresh
              </button>
              <button
                className="px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9] disabled:opacity-50"
                onClick={() => setMode('create')}
                disabled={!regionMeta?.available}
              >
                New harness
              </button>
            </div>
          </div>

          {loading && list.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-[#5f6b7a]">
              <div className="w-3 h-3 border-2 border-[#0972d3] border-t-transparent rounded-full animate-spin" />
              Loading…
            </div>
          )}

          {!loading && list.length === 0 && (
            <div className="rounded-xl border border-dashed border-[#e9ebed] bg-[#fafafa] p-6 text-center">
              <div className="text-sm text-[#16191f] font-medium mb-1">
                No harnesses yet
              </div>
              <div className="text-xs text-[#5f6b7a]">
                Click "New harness" to create an AgentCore managed agent.
              </div>
            </div>
          )}

          <ul className="space-y-2">
            {list.map((h) => (
              <li
                key={h.harness_id}
                className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-[#16191f] truncate">
                        {h.name}
                      </span>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${statusChip(h.status)}`}
                      >
                        {h.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-[#5f6b7a] truncate">
                      {h.model_provider} · {h.model_id}
                    </div>
                    {h.description && (
                      <div className="text-[11px] text-[#5f6b7a] italic truncate">
                        {h.description}
                      </div>
                    )}
                    {h.failure_reason && (
                      <div className="text-[11px] text-red-700 mt-1">
                        {h.failure_reason}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1.5 justify-end">
                    <button
                      className="px-2 py-1 text-xs rounded-md border border-[#e9ebed] bg-white text-[#16191f] hover:bg-[#f2f3f3] disabled:opacity-50"
                      disabled={h.status !== 'READY'}
                      onClick={() => {
                        setSelected(h);
                        setInvokeOutput([]);
                        setMode('invoke');
                      }}
                    >
                      Invoke
                    </button>
                    {canPublishToRegistry && (
                      <button
                        className="px-2 py-1 text-xs rounded-md border border-[#0972d3]/40 bg-white text-[#0972d3] hover:bg-[#0972d3]/5 disabled:opacity-50"
                        disabled={h.status !== 'READY'}
                        onClick={() => setPublishFor(h)}
                        title="Publish this harness to AWS Agent Registry"
                      >
                        Publish
                      </button>
                    )}
                    <button
                      className="px-2 py-1 text-xs rounded-md border border-red-200 bg-white text-red-700 hover:bg-red-50"
                      onClick={() => handleDelete(h)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {mode === 'create' && (
        <section className="p-4 space-y-3">
          <button
            className="text-xs text-[#0972d3] hover:underline"
            onClick={() => setMode('list')}
          >
            ← Back to list
          </button>
          <h3 className="text-sm font-semibold text-[#16191f]">New harness</h3>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
              Name
            </span>
            <input
              className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
              placeholder="letter + alphanumerics/_ (max 64)"
              value={form.harness_name}
              onChange={(e) =>
                setForm({ ...form, harness_name: e.target.value })
              }
            />
          </label>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
              Description (optional)
            </span>
            <input
              className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
              placeholder="What does this harness do?"
              value={form.description || ''}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </label>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
              Bedrock model
            </span>
            <input
              list="harness-models"
              className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm font-mono"
              placeholder={DEFAULT_MODEL}
              value={useCustom ? customModel : form.model.bedrock?.model_id || ''}
              onChange={(e) => {
                const v = e.target.value;
                if (BEDROCK_MODELS.includes(v)) {
                  setCustomModel('');
                  setForm({ ...form, model: { bedrock: { model_id: v } } });
                } else {
                  setCustomModel(v);
                }
              }}
            />
            <datalist id="harness-models">
              {BEDROCK_MODELS.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <div className="text-[10px] text-[#8d99a8] mt-0.5">
              Pick from the list or paste any Bedrock model ID. Use the{' '}
              <code>us.</code> inference-profile prefix for on-demand.
            </div>
          </label>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
              System prompt
            </span>
            <textarea
              rows={4}
              className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
              value={form.system_prompt || ''}
              onChange={(e) =>
                setForm({ ...form, system_prompt: e.target.value })
              }
            />
          </label>

          <fieldset className="rounded-xl border border-[#e9ebed] p-3">
            <legend className="text-[11px] uppercase tracking-wide text-[#5f6b7a] px-1">
              Built-in tools
            </legend>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeCodeInterpreter}
                onChange={(e) => setIncludeCodeInterpreter(e.target.checked)}
              />
              Code interpreter (Python)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeBrowser}
                onChange={(e) => setIncludeBrowser(e.target.checked)}
              />
              Browser
            </label>
            <label className="block mt-2">
              <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                Gateway ARN (optional)
              </span>
              <input
                className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-xs font-mono"
                placeholder="arn:aws:bedrock-agentcore:…:gateway/…"
                value={gatewayArn}
                onChange={(e) => setGatewayArn(e.target.value)}
              />
            </label>
          </fieldset>

          <button
            className="text-xs text-[#0972d3] hover:underline"
            onClick={() => setShowAdvanced((s) => !s)}
          >
            {showAdvanced ? '▼' : '▶'} Advanced configuration
          </button>

          {showAdvanced && (
            <div className="space-y-3 rounded-xl border border-[#e9ebed] bg-[#fafafa] p-3">
              <div className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-900">
                <strong>Preview:</strong> guardrail, knowledge base, and
                observability fields below are accepted by the API but not yet
                forwarded to <code>CreateHarness</code> — AWS's current SDK model
                does not include them. Lifecycle, memory, and the Bedrock inference
                knobs <em>are</em> applied.
              </div>
              <label className="block">
                <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                  Memory ARN (AgentCore Memory)
                </span>
                <input
                  className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-xs font-mono"
                  placeholder="arn:aws:bedrock-agentcore:…:memory/…"
                  value={memoryArn}
                  onChange={(e) => setMemoryArn(e.target.value)}
                />
              </label>

              <div className="grid grid-cols-3 gap-2">
                <label className="col-span-2 block">
                  <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                    Guardrail ID
                  </span>
                  <input
                    className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-xs font-mono"
                    placeholder="gr-xxxxxxxx or ARN"
                    value={guardrailId}
                    onChange={(e) => setGuardrailId(e.target.value)}
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                    Version
                  </span>
                  <input
                    className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-xs font-mono"
                    value={guardrailVersion}
                    onChange={(e) => setGuardrailVersion(e.target.value)}
                  />
                </label>
              </div>

              <label className="block">
                <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                  Knowledge base IDs (comma-separated)
                </span>
                <input
                  className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-xs font-mono"
                  placeholder="KB123, KB456"
                  value={kbIdsCsv}
                  onChange={(e) => setKbIdsCsv(e.target.value)}
                />
              </label>

              <label className="block">
                <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                  Stop sequences (comma-separated)
                </span>
                <input
                  className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-xs font-mono"
                  placeholder="END, \n\nHuman:"
                  value={stopSeqsCsv}
                  onChange={(e) => setStopSeqsCsv(e.target.value)}
                />
              </label>

              <fieldset className="rounded-lg border border-[#e9ebed] p-2">
                <legend className="text-[11px] uppercase tracking-wide text-[#5f6b7a] px-1">
                  Observability
                </legend>
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={form.observability?.traces_enabled ?? true}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        observability: {
                          traces_enabled: e.target.checked,
                          metrics_enabled:
                            form.observability?.metrics_enabled ?? true,
                        },
                      })
                    }
                  />
                  Traces enabled
                </label>
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={form.observability?.metrics_enabled ?? true}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        observability: {
                          traces_enabled:
                            form.observability?.traces_enabled ?? true,
                          metrics_enabled: e.target.checked,
                        },
                      })
                    }
                  />
                  Metrics enabled
                </label>
              </fieldset>

              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                    Idle timeout (s)
                  </span>
                  <input
                    type="number"
                    className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                    value={form.lifecycle?.idle_runtime_session_timeout ?? 900}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        lifecycle: {
                          idle_runtime_session_timeout:
                            parseInt(e.target.value, 10) || 900,
                          max_lifetime: form.lifecycle?.max_lifetime ?? 28_800,
                        },
                      })
                    }
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                    Max lifetime (s)
                  </span>
                  <input
                    type="number"
                    className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                    value={form.lifecycle?.max_lifetime ?? 28_800}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        lifecycle: {
                          idle_runtime_session_timeout:
                            form.lifecycle?.idle_runtime_session_timeout ?? 900,
                          max_lifetime: parseInt(e.target.value, 10) || 28_800,
                        },
                      })
                    }
                  />
                </label>
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                Max iters
              </span>
              <input
                type="number"
                className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                value={form.max_iterations || ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    max_iterations:
                      parseInt(e.target.value || '0', 10) || undefined,
                  })
                }
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                Max tokens
              </span>
              <input
                type="number"
                className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                value={form.max_tokens || ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    max_tokens:
                      parseInt(e.target.value || '0', 10) || undefined,
                  })
                }
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                Timeout (s)
              </span>
              <input
                type="number"
                className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                value={form.timeout_seconds || ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    timeout_seconds:
                      parseInt(e.target.value || '0', 10) || undefined,
                  })
                }
              />
            </label>
          </div>

          <div className="flex gap-2">
            <button
              className="px-3 py-1.5 text-sm font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9] disabled:bg-[#e9ebed] disabled:text-[#8d99a8]"
              onClick={handleCreate}
              disabled={!canCreate || loading}
            >
              {loading ? 'Creating…' : 'Create'}
            </button>
            <button
              className="px-3 py-1.5 text-sm rounded-md border border-[#e9ebed] bg-white text-[#16191f] hover:bg-[#f2f3f3]"
              onClick={() => setMode('list')}
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {mode === 'invoke' && selected && (
        <section className="p-4 space-y-3">
          <button
            className="text-xs text-[#0972d3] hover:underline"
            onClick={() => setMode('list')}
          >
            ← Back to list
          </button>
          <div>
            <h3 className="text-sm font-semibold text-[#16191f]">
              {selected.name}
            </h3>
            <div className="text-[11px] text-[#5f6b7a]">
              {selected.model_provider} · {selected.model_id}
            </div>
          </div>
          <div className="rounded-xl border border-[#e9ebed] bg-[#fafafa] p-3 space-y-2 max-h-[340px] overflow-y-auto">
            {invokeOutput.length === 0 && (
              <div className="text-xs text-[#8d99a8]">
                No messages yet. Send a prompt to talk to your harness.
              </div>
            )}
            {invokeOutput.map((m, i) => (
              <div
                key={i}
                className={`rounded-md px-3 py-2 text-sm ${m.role === 'user' ? 'bg-[#0972d3] text-white ml-auto max-w-[85%]' : 'bg-white border border-[#e9ebed] text-[#16191f] max-w-[85%]'}`}
              >
                {m.text}
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
              placeholder="Type a prompt…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void handleInvoke();
                }
              }}
              disabled={invoking}
            />
            <button
              className="px-3 py-1.5 text-sm font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9] disabled:bg-[#e9ebed] disabled:text-[#8d99a8]"
              onClick={handleInvoke}
              disabled={!prompt.trim() || invoking}
            >
              {invoking ? 'Running…' : 'Send'}
            </button>
          </div>
        </section>
      )}

      {publishFor && (
        <PublishToRegistryModal
          source_type="harness"
          source_id={publishFor.harness_id}
          defaultName={`harness_${publishFor.name}`}
          defaultDescription={
            publishFor.description ||
            `AgentCore Harness ${publishFor.name} (${publishFor.model_id})`
          }
          onClose={() => setPublishFor(null)}
        />
      )}
    </div>
  );
}

export default HarnessPanel;
