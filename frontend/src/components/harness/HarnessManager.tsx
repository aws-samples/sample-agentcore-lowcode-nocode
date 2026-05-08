/**
 * Harness Manager drawer (Task 11).
 *
 * Full lifecycle UI for AgentCore Harnesses:
 *   - create (model + prompt + tools + execution limits)
 *   - list (with status chip + refresh)
 *   - invoke (inline chat against a single harness)
 *   - delete
 *
 * Styled to match the AWS-console Tailwind look used elsewhere. Uses
 * framer-motion for the slide-in entrance to match the ApprovalInbox drawer.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
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

interface Props {
  open: boolean;
  onClose: () => void;
}

const DEFAULT_MODEL = 'anthropic.claude-3-5-haiku-20241022-v1:0';
const BEDROCK_MODELS = [
  'anthropic.claude-opus-4-5-20250101-v1:0',
  'anthropic.claude-sonnet-4-20250514-v1:0',
  'anthropic.claude-3-5-sonnet-20241022-v2:0',
  'anthropic.claude-3-5-haiku-20241022-v1:0',
  'anthropic.claude-3-haiku-20240307-v1:0',
  'amazon.nova-pro-v1:0',
  'amazon.nova-lite-v1:0',
];

const statusChip = (s: HarnessStatus): string => {
  if (s === 'READY') return 'bg-emerald-500 text-white';
  if (s === 'CREATING' || s === 'UPDATING' || s === 'DELETING')
    return 'bg-[#ff9900]/20 text-[#d45b07] border border-[#ff9900]/40';
  return 'bg-red-50 text-red-700 border border-red-200';
};

export function HarnessManager({ open, onClose }: Props) {
  const [list, setList] = useState<HarnessRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [regionMeta, setRegionMeta] = useState<{ region: string; available: boolean; supported_regions: string[] } | null>(null);
  const [mode, setMode] = useState<'list' | 'create' | 'invoke'>('list');
  const [selected, setSelected] = useState<HarnessRecord | null>(null);
  // Invoke state
  const [prompt, setPrompt] = useState('');
  const [invokeOutput, setInvokeOutput] = useState<{ role: 'user' | 'assistant'; text: string }[]>([]);
  const [invoking, setInvoking] = useState(false);

  // Create form state
  const [form, setForm] = useState<HarnessCreateRequest>({
    harness_name: '',
    model: { bedrock: { model_id: DEFAULT_MODEL } },
    system_prompt: 'You are a helpful assistant.',
    tools: [],
    allowed_tools: ['*'],
    max_iterations: 20,
    timeout_seconds: 300,
  });
  const [includeCodeInterpreter, setIncludeCodeInterpreter] = useState(false);
  const [includeBrowser, setIncludeBrowser] = useState(false);

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
    if (!open) return;
    void harnessRegion().then(setRegionMeta).catch(() => setRegionMeta(null));
    void refresh();
  }, [open, refresh]);

  // Poll non-terminal harnesses
  useEffect(() => {
    if (!open) return;
    const pending = list.filter((h) => !['READY', 'CREATE_FAILED', 'UPDATE_FAILED', 'DELETE_FAILED'].includes(h.status));
    if (pending.length === 0) return;
    const id = setInterval(async () => {
      for (const h of pending) {
        try {
          const fresh = await getHarness(h.harness_id, true);
          setList((prev) => prev.map((p) => (p.harness_id === h.harness_id ? fresh : p)));
        } catch {
          // keep previous
        }
      }
    }, 7000);
    return () => clearInterval(id);
  }, [open, list]);

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      const tools: HarnessCreateRequest['tools'] = [];
      if (includeCodeInterpreter) tools!.push({ type: 'agentcore_code_interpreter' });
      if (includeBrowser) tools!.push({ type: 'agentcore_browser' });
      const body: HarnessCreateRequest = {
        ...form,
        tools: tools && tools.length ? tools : undefined,
      };
      const rec = await createHarness(body);
      setList((prev) => [rec, ...prev]);
      setMode('list');
      setForm({ ...form, harness_name: '' });
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
        setInvokeOutput((prev) => [...prev, { role: 'assistant', text: r.response || '(empty)' }]);
      } else {
        setInvokeOutput((prev) => [...prev, { role: 'assistant', text: `error: ${r.error}` }]);
      }
    } catch (e) {
      setInvokeOutput((prev) => [...prev, { role: 'assistant', text: `error: ${e instanceof Error ? e.message : 'failed'}` }]);
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

  const canCreate = useMemo(() => /^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(form.harness_name), [form.harness_name]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 bg-black/30 z-[99]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label="Harness Manager"
            className="fixed top-0 right-0 h-screen w-full sm:max-w-[560px] bg-white shadow-xl z-[100] flex flex-col"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-[#e9ebed] bg-[#232f3e]">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-md bg-[#ff9900] flex items-center justify-center">
                  <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">Harness Manager</h2>
                  <p className="text-[11px] text-white/50">AgentCore managed agent — model + tools + memory in one resource</p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close harness manager"
                className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
              >
                <svg className="w-4 h-4 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </header>

            <div className="flex-1 overflow-y-auto">
              {regionMeta && !regionMeta.available && (
                <div className="m-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  AgentCore Harness is not available in <strong>{regionMeta.region}</strong>. Supported regions: {regionMeta.supported_regions.join(', ')}.
                </div>
              )}

              {error && (
                <div role="alert" className="m-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
              )}

              {mode === 'list' && (
                <section className="p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs text-[#5f6b7a]">{list.length} harness{list.length === 1 ? '' : 'es'}</div>
                    <div className="flex gap-2">
                      <button className="px-2.5 py-1 text-xs font-medium rounded-md border border-[#e9ebed] bg-white text-[#16191f] hover:bg-[#f2f3f3]" onClick={refresh}>
                        Refresh
                      </button>
                      <button className="px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9]" onClick={() => setMode('create')} disabled={!regionMeta?.available}>
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
                      <div className="text-sm text-[#16191f] font-medium mb-1">No harnesses yet</div>
                      <div className="text-xs text-[#5f6b7a]">Click “New harness” to create an AgentCore managed agent.</div>
                    </div>
                  )}

                  <ul className="space-y-2">
                    {list.map((h) => (
                      <li key={h.harness_id} className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm">
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-semibold text-[#16191f] truncate">{h.name}</span>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${statusChip(h.status)}`}>{h.status}</span>
                            </div>
                            <div className="text-[11px] text-[#5f6b7a] truncate">{h.model_provider} · {h.model_id}</div>
                            {h.failure_reason && <div className="text-[11px] text-red-700 mt-1">{h.failure_reason}</div>}
                          </div>
                          <div className="flex gap-1.5">
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
                  <button className="text-xs text-[#0972d3] hover:underline" onClick={() => setMode('list')}>
                    ← Back to list
                  </button>
                  <h3 className="text-sm font-semibold text-[#16191f]">New harness</h3>

                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Name</span>
                    <input
                      className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm text-[#16191f] focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30"
                      placeholder="letter + alphanumerics/_ (max 64)"
                      value={form.harness_name}
                      onChange={(e) => setForm({ ...form, harness_name: e.target.value })}
                    />
                  </label>
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Bedrock model</span>
                    <select
                      className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm text-[#16191f]"
                      value={form.model.bedrock?.model_id || DEFAULT_MODEL}
                      onChange={(e) => setForm({ ...form, model: { bedrock: { model_id: e.target.value } } })}
                    >
                      {BEDROCK_MODELS.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">System prompt</span>
                    <textarea
                      rows={4}
                      className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm text-[#16191f]"
                      value={form.system_prompt || ''}
                      onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                    />
                  </label>
                  <fieldset className="rounded-xl border border-[#e9ebed] p-3">
                    <legend className="text-[11px] uppercase tracking-wide text-[#5f6b7a] px-1">Built-in tools</legend>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={includeCodeInterpreter} onChange={(e) => setIncludeCodeInterpreter(e.target.checked)} />
                      Code interpreter (Python)
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={includeBrowser} onChange={(e) => setIncludeBrowser(e.target.checked)} />
                      Browser
                    </label>
                  </fieldset>
                  <div className="grid grid-cols-3 gap-2">
                    <label className="block">
                      <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Max iters</span>
                      <input
                        type="number"
                        className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                        value={form.max_iterations || ''}
                        onChange={(e) => setForm({ ...form, max_iterations: parseInt(e.target.value || '0', 10) || undefined })}
                      />
                    </label>
                    <label className="block">
                      <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Max tokens</span>
                      <input
                        type="number"
                        className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                        value={form.max_tokens || ''}
                        onChange={(e) => setForm({ ...form, max_tokens: parseInt(e.target.value || '0', 10) || undefined })}
                      />
                    </label>
                    <label className="block">
                      <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">Timeout (s)</span>
                      <input
                        type="number"
                        className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                        value={form.timeout_seconds || ''}
                        onChange={(e) => setForm({ ...form, timeout_seconds: parseInt(e.target.value || '0', 10) || undefined })}
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
                  <button className="text-xs text-[#0972d3] hover:underline" onClick={() => setMode('list')}>
                    ← Back to list
                  </button>
                  <div>
                    <h3 className="text-sm font-semibold text-[#16191f]">{selected.name}</h3>
                    <div className="text-[11px] text-[#5f6b7a]">{selected.model_provider} · {selected.model_id}</div>
                  </div>
                  <div className="rounded-xl border border-[#e9ebed] bg-[#fafafa] p-3 space-y-2 max-h-[340px] overflow-y-auto">
                    {invokeOutput.length === 0 && (
                      <div className="text-xs text-[#8d99a8]">No messages yet. Send a prompt to talk to your harness.</div>
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
                      className="flex-1 rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:border-[#0972d3] focus:ring-2 focus:ring-[#0972d3]/30"
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
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

export default HarnessManager;
