/**
 * PublishToRegistryModal
 *
 * One-click publish of a deployment / tool / harness to the AWS Agent
 * Registry. Fetches available registries, shows a picker, pre-fills name
 * + description from the source entity, and hits /api/registry/auto-publish
 * so the descriptor JSON is built server-side (the user never types it).
 */

import { useEffect, useState } from 'react';
import {
  type AutoPublishSourceType,
  type RegistrySummary,
  autoPublishToRegistry,
  listRegistries,
} from '../../services/registry';

interface Props {
  source_type: AutoPublishSourceType;
  source_id: string;
  defaultName?: string;
  defaultDescription?: string;
  /** For source_type="tool" we can't load the tool from a store, so the
   * caller passes its metadata directly. */
  toolPayload?: {
    display_name?: string;
    description?: string;
    input_schema?: Record<string, unknown>;
  };
  onClose: () => void;
  onPublished?: (recordId: string) => void;
}

export function PublishToRegistryModal({
  source_type,
  source_id,
  defaultName,
  defaultDescription,
  toolPayload,
  onClose,
  onPublished,
}: Props) {
  const [registries, setRegistries] = useState<RegistrySummary[]>([]);
  const [selectedRegistry, setSelectedRegistry] = useState<string>('');
  const [name, setName] = useState(defaultName || '');
  const [description, setDescription] = useState(defaultDescription || '');
  const [submitForApproval, setSubmitForApproval] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoadingList(true);
      try {
        const rs = await listRegistries();
        const ready = rs.filter((r) => r.status === 'READY' || !r.status);
        setRegistries(ready);
        if (ready.length > 0) setSelectedRegistry(ready[0].registry_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to list registries');
      } finally {
        setLoadingList(false);
      }
    })();
  }, []);

  const doPublish = async () => {
    if (!selectedRegistry) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const rec = await autoPublishToRegistry({
        source_type,
        source_id,
        registry_id: selectedRegistry,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        submit_for_approval: submitForApproval,
        tool_payload: source_type === 'tool' ? toolPayload : undefined,
      });
      setSuccess(`Published as ${rec.name} (${rec.record_id}) — ${rec.status}`);
      onPublished?.(rec.record_id);
      // Auto-close after 1.6s so the user sees the success message
      setTimeout(() => onClose(), 1600);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'publish failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Publish to Registry"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between px-4 py-3 border-b border-[#e9ebed] bg-[#f7f8f9] rounded-t-xl">
          <div>
            <h3 className="text-sm font-semibold text-[#16191f]">
              Publish to AWS Agent Registry
            </h3>
            <p className="text-[11px] text-[#5f6b7a]">
              Auto-generates the descriptor from this{' '}
              <strong>{source_type}</strong>.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded-md hover:bg-[#e9ebed]"
          >
            <svg
              className="w-4 h-4 text-[#5f6b7a]"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </header>

        <div className="p-4 space-y-3">
          {error && (
            <div
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
            >
              {error}
            </div>
          )}
          {success && (
            <div
              role="status"
              className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800"
            >
              {success}
            </div>
          )}

          {loadingList ? (
            <div className="text-xs text-[#5f6b7a]">Loading registries…</div>
          ) : registries.length === 0 ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              No registries found. An admin must create one first via the
              Services drawer → Registry tab → Setup registry.
            </div>
          ) : (
            <label className="block">
              <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
                Registry
              </span>
              <select
                className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
                value={selectedRegistry}
                onChange={(e) => setSelectedRegistry(e.target.value)}
              >
                {registries.map((r) => (
                  <option key={r.registry_id} value={r.registry_id}>
                    {r.name} ({r.registry_id})
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
              Record name
            </span>
            <input
              className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
              placeholder="Auto-generated from source"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wide text-[#5f6b7a]">
              Description
            </span>
            <textarea
              rows={2}
              className="mt-1 w-full rounded-md border border-[#e9ebed] bg-white px-2.5 py-1.5 text-sm"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label className="flex items-center gap-2 text-xs text-[#16191f]">
            <input
              type="checkbox"
              checked={submitForApproval}
              onChange={(e) => setSubmitForApproval(e.target.checked)}
            />
            Submit for approval (publish as PENDING instead of DRAFT)
          </label>
        </div>

        <footer className="flex justify-end gap-2 px-4 py-3 border-t border-[#e9ebed] bg-[#f7f8f9] rounded-b-xl">
          <button
            className="px-3 py-1.5 text-sm rounded-md border border-[#e9ebed] bg-white text-[#16191f] hover:bg-[#f2f3f3]"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="px-3 py-1.5 text-sm font-semibold rounded-md bg-[#0972d3] text-white hover:bg-[#0961b9] disabled:bg-[#e9ebed] disabled:text-[#8d99a8]"
            onClick={doPublish}
            disabled={loading || !selectedRegistry || registries.length === 0}
          >
            {loading ? 'Publishing…' : 'Publish'}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default PublishToRegistryModal;
