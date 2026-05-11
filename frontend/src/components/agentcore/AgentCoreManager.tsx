/**
 * AgentCore Services drawer (Tasks 11, 12 & 13 frontend).
 *
 * Three tabs: Harness (managed agent), Optimization (bundles + evaluators),
 * Registry (AWS Agent Registry). Single right-hand entry-point for all
 * AgentCore-managed services.
 */

import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  type ConfigurationBundleRecord,
  type EvaluatorSummary,
  createBundle,
  deleteBundle,
  listBundles,
  listBundleVersions,
  listEvaluators,
  updateBundle,
} from '../../services/optimization';
import {
  type RecordSummary,
  type RegistrySummary,
  approveRecord,
  createRecord,
  deleteRecord,
  listRecords,
  listRegistries,
  searchRecords,
  submitForApproval,
} from '../../services/registry';
import { HarnessPanel } from '../harness/HarnessPanel';

interface Props {
  open: boolean;
  onClose: () => void;
  defaultTab?: Tab;
}

type Tab = 'harness' | 'optimization' | 'registry';

export function AgentCoreManager({ open, onClose, defaultTab }: Props) {
  const [tab, setTab] = useState<Tab>(defaultTab || 'harness');
  useEffect(() => {
    if (defaultTab && open) setTab(defaultTab);
  }, [defaultTab, open]);
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
            aria-label="AgentCore Services"
            className="fixed top-0 right-0 h-screen w-full sm:max-w-[720px] bg-white shadow-xl z-[100] flex flex-col"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-[#e9ebed] bg-[#232f3e]">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-md bg-[#ff9900] flex items-center justify-center">
                  <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 3h7v7H3z" /><path d="M14 3h7v7h-7z" /><path d="M14 14h7v7h-7z" /><path d="M3 14h7v7H3z" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">AgentCore Services</h2>
                  <p className="text-[11px] text-white/50">Harness · Optimization · Registry</p>
                </div>
              </div>
              <button onClick={onClose} aria-label="close" className="p-1.5 rounded-md hover:bg-white/10">
                <svg className="w-4 h-4 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </header>
            <nav className="flex border-b border-[#e9ebed] bg-[#f7f8f9] px-2 pt-2 gap-1.5" role="tablist" aria-label="Services tabs">
              {(['harness', 'optimization', 'registry'] as Tab[]).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={[
                    'py-2 px-3 rounded-t-md text-xs font-medium capitalize',
                    tab === t
                      ? 'bg-white text-[#0972d3] shadow-sm border border-[#e9ebed] border-b-white'
                      : 'text-[#5f6b7a] hover:text-[#16191f]',
                  ].join(' ')}
                >
                  {t}
                </button>
              ))}
            </nav>
            <div className="flex-1 overflow-y-auto">
              {tab === 'harness' && <HarnessPanel />}
              {tab === 'optimization' && <OptimizationPanel />}
              {tab === 'registry' && <RegistryPanel />}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}


function OptimizationPanel() {
  const [evaluators, setEvaluators] = useState<EvaluatorSummary[]>([]);
  const [bundles, setBundles] = useState<ConfigurationBundleRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, Array<Record<string, unknown>>>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [bundleName, setBundleName] = useState('');
  const [resourceArn, setResourceArn] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('You are a helpful assistant.');
  const [commit, setCommit] = useState('initial');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ev, bs] = await Promise.all([listEvaluators(), listBundles()]);
      setEvaluators(ev);
      setBundles(bs);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const create = async () => {
    if (!bundleName.trim() || !resourceArn.trim()) return;
    try {
      await createBundle({
        bundle_name: bundleName,
        description: 'Created from UI',
        components: [{ resource_arn: resourceArn, configuration: { systemPrompt } }],
        commit_message: commit || undefined,
      });
      setBundleName('');
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  };

  const toggleExpand = async (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!versions[id]) {
      try {
        const r = await listBundleVersions(id);
        setVersions((p) => ({ ...p, [id]: r.versions }));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed');
      }
    }
  };

  const tweakPrompt = async (b: ConfigurationBundleRecord) => {
    const nextPrompt = prompt('New system prompt:', 'You are an even more helpful assistant.');
    if (!nextPrompt) return;
    const arn = prompt('Resource ARN this config applies to:', resourceArn || 'arn:aws:bedrock-agentcore:us-east-1:0:runtime/placeholder');
    if (!arn) return;
    try {
      await updateBundle(b.bundle_id, {
        components: [{ resource_arn: arn, configuration: { systemPrompt: nextPrompt } }],
        commit_message: 'UI: tweak prompt',
      });
      setVersions((p) => { const c = { ...p }; delete c[b.bundle_id]; return c; });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  };

  return (
    <section className="p-4 space-y-4">
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}

      <div className="rounded-xl border border-[#e9ebed] bg-white p-3.5 shadow-sm">
        <h3 className="text-sm font-semibold text-[#16191f]">New configuration bundle</h3>
        <p className="text-xs text-[#5f6b7a] mt-0.5">Versioned snapshots of agent config (keyed by resource ARN).</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <input className="rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" placeholder="bundle_name" value={bundleName} onChange={(e) => setBundleName(e.target.value)} />
          <input className="rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" placeholder="resource ARN" value={resourceArn} onChange={(e) => setResourceArn(e.target.value)} />
        </div>
        <textarea className="mt-2 w-full rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" rows={2} placeholder="system prompt" value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
        <div className="mt-2 flex gap-2">
          <input className="flex-1 rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" placeholder="commit message" value={commit} onChange={(e) => setCommit(e.target.value)} />
          <button className="px-3 py-1.5 text-sm font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9] disabled:opacity-50" onClick={create} disabled={!bundleName.trim() || !resourceArn.trim()}>Create</button>
        </div>
      </div>

      {loading && <div className="text-xs text-[#5f6b7a]">Loading…</div>}

      <ul className="space-y-2">
        {bundles.map((b) => (
          <li key={b.bundle_id} className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-[#16191f]">{b.bundle_name}</div>
                <div className="text-[11px] text-[#5f6b7a]">{b.bundle_id}</div>
                <div className="text-[10px] text-[#8d99a8] font-mono truncate">{b.bundle_arn}</div>
                {b.description && <div className="text-xs text-[#16191f] mt-1">{b.description}</div>}
              </div>
              <div className="flex gap-1.5">
                <button className="px-2 py-1 text-xs rounded-md border border-[#e9ebed] bg-white hover:bg-[#f2f3f3]" onClick={() => toggleExpand(b.bundle_id)}>
                  {expanded === b.bundle_id ? 'Hide' : 'Versions'}
                </button>
                <button className="px-2 py-1 text-xs rounded-md border border-[#0972d3]/40 bg-white text-[#0972d3] hover:bg-[#0972d3]/5" onClick={() => tweakPrompt(b)}>Tweak</button>
                <button
                  className="px-2 py-1 text-xs rounded-md border border-red-200 bg-white text-red-700 hover:bg-red-50"
                  onClick={async () => {
                    if (!confirm(`Delete bundle "${b.bundle_name}"?`)) return;
                    try { await deleteBundle(b.bundle_id); await refresh(); }
                    catch (e) { setError(e instanceof Error ? e.message : 'failed'); }
                  }}
                >Delete</button>
              </div>
            </div>
            {expanded === b.bundle_id && versions[b.bundle_id] && (
              <ul className="mt-2 space-y-1 text-[11px]">
                {versions[b.bundle_id].map((v, i) => (
                  <li key={i} className="font-mono text-[#5f6b7a]">
                    {(v.versionId as string)?.slice(0, 12)}… · {(v.lineageMetadata as { commitMessage?: string })?.commitMessage || '—'} · {String(v.versionCreatedAt)}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
        {!loading && bundles.length === 0 && (
          <li className="rounded-xl border border-dashed border-[#e9ebed] bg-[#fafafa] p-4 text-center text-xs text-[#5f6b7a]">No bundles yet.</li>
        )}
      </ul>

      <details className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-[#16191f]">Evaluators ({evaluators.length})</summary>
        <ul className="mt-2 space-y-1 text-xs">
          {evaluators.map((e) => (
            <li key={e.evaluator_id} className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <span className="font-mono text-[#16191f]">{e.evaluator_id}</span>
                {e.level && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-[#0972d3]/10 text-[#0972d3]">{e.level}</span>}
              </div>
              <div className="text-[10px] text-[#8d99a8] truncate max-w-[60%]" title={e.description || ''}>{e.description || ''}</div>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}


function RegistryPanel() {
  const [registries, setRegistries] = useState<RegistrySummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newContent, setNewContent] = useState('{}');

  const refreshList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rs = await listRegistries();
      setRegistries(rs);
      if (rs.length > 0 && !selected) setSelected(rs[0].registry_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  const refreshRecords = useCallback(async () => {
    if (!selected) return;
    try {
      const rs = query.trim()
        ? await searchRecords(selected, query.trim())
        : await listRecords(selected, filter ? { status: filter } : undefined);
      setRecords(rs);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  }, [selected, query, filter]);

  useEffect(() => { void refreshList(); }, [refreshList]);
  useEffect(() => { void refreshRecords(); }, [refreshRecords]);

  const publish = async () => {
    if (!selected || !newName.trim()) return;
    try {
      await createRecord({
        registry_id: selected,
        name: newName.trim(),
        description: newDescription,
        descriptor_type: 'CUSTOM',
        descriptors: { custom: { inline_content: newContent } },
      });
      setNewName(''); setNewDescription(''); setNewContent('{}');
      await refreshRecords();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    }
  };

  return (
    <section className="p-4 space-y-4">
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}

      <div className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm">
        <div className="text-[11px] uppercase tracking-wide text-[#5f6b7a] mb-1">Registry</div>
        {loading && <div className="text-xs text-[#5f6b7a]">Loading…</div>}
        {registries.length === 0 && !loading && <div className="text-xs text-[#5f6b7a]">No registries found in this account.</div>}
        {registries.length > 0 && (
          <select className="w-full rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" value={selected || ''} onChange={(e) => setSelected(e.target.value || null)}>
            {registries.map((r) => (
              <option key={r.registry_id} value={r.registry_id}>{r.name} ({r.registry_id})</option>
            ))}
          </select>
        )}
      </div>

      {selected && (
        <>
          <div className="rounded-xl border border-[#e9ebed] bg-white p-3.5 shadow-sm space-y-2">
            <h3 className="text-sm font-semibold text-[#16191f]">Publish CUSTOM record</h3>
            <input className="w-full rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" placeholder="name" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <input className="w-full rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" placeholder="description" value={newDescription} onChange={(e) => setNewDescription(e.target.value)} />
            <textarea className="w-full rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm font-mono" rows={3} value={newContent} onChange={(e) => setNewContent(e.target.value)} />
            <button className="px-3 py-1.5 text-sm font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9] disabled:opacity-50" onClick={publish} disabled={!newName.trim()}>Publish</button>
          </div>

          <div className="flex gap-2">
            <input className="flex-1 rounded-md border border-[#e9ebed] px-2.5 py-1.5 text-sm" placeholder="search approved records" value={query} onChange={(e) => setQuery(e.target.value)} />
            <select className="rounded-md border border-[#e9ebed] px-2 py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)} disabled={!!query.trim()}>
              <option value="">Any status</option>
              <option value="DRAFT">Draft</option>
              <option value="PENDING_APPROVAL">Pending</option>
              <option value="APPROVED">Approved</option>
              <option value="REJECTED">Rejected</option>
              <option value="RETIRED">Retired</option>
            </select>
            <button className="px-2.5 py-1 text-xs rounded-md border border-[#e9ebed] bg-white hover:bg-[#f2f3f3]" onClick={refreshRecords}>Refresh</button>
          </div>

          <ul className="space-y-2">
            {records.map((r) => (
              <li key={r.record_id} className="rounded-xl border border-[#e9ebed] bg-white p-3 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-semibold text-[#16191f] truncate">{r.name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#0972d3]/10 text-[#0972d3] font-medium">{r.descriptor_type}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        r.status === 'APPROVED' ? 'bg-emerald-500 text-white'
                        : r.status === 'PENDING_APPROVAL' ? 'bg-[#ff9900]/20 text-[#d45b07] border border-[#ff9900]/40'
                        : r.status === 'REJECTED' ? 'bg-red-50 text-red-700 border border-red-200'
                        : 'bg-[#f2f3f3] text-[#5f6b7a] border border-[#e9ebed]'
                      }`}>{r.status}</span>
                    </div>
                    {r.description && <div className="text-xs text-[#5f6b7a] mt-1">{r.description}</div>}
                  </div>
                  <div className="flex gap-1.5 flex-shrink-0">
                    {r.status === 'DRAFT' && (
                      <button className="px-2 py-1 text-xs rounded-md border border-[#e9ebed] bg-white hover:bg-[#f2f3f3]" onClick={async () => { try { await submitForApproval(r.registry_id, r.record_id); await refreshRecords(); } catch (e) { setError(e instanceof Error ? e.message : 'failed'); } }}>Submit</button>
                    )}
                    {r.status === 'PENDING_APPROVAL' && (
                      <button className="px-2 py-1 text-xs rounded-md border border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700" onClick={async () => { try { await approveRecord(r.registry_id, r.record_id, 'ui approval'); await refreshRecords(); } catch (e) { setError(e instanceof Error ? e.message : 'failed'); } }}>Approve</button>
                    )}
                    <button className="px-2 py-1 text-xs rounded-md border border-red-200 bg-white text-red-700 hover:bg-red-50" onClick={async () => { if (!confirm(`Delete record "${r.name}"?`)) return; try { await deleteRecord(r.registry_id, r.record_id); await refreshRecords(); } catch (e) { setError(e instanceof Error ? e.message : 'failed'); } }}>Delete</button>
                  </div>
                </div>
              </li>
            ))}
            {records.length === 0 && !loading && (
              <li className="rounded-xl border border-dashed border-[#e9ebed] bg-[#fafafa] p-4 text-center text-xs text-[#5f6b7a]">No records match.</li>
            )}
          </ul>
        </>
      )}
    </section>
  );
}

export default AgentCoreManager;
