/**
 * RegistryModal — Phase 2 Gap 2A global agent registry browse/publish/clone.
 *
 * Browse org-wide / public published agents, search by name/tag/scope, and
 * clone a canvas snapshot to the active canvas. Mirrors the shell of
 * EvaluationConfigurationModal (fixed overlay + white panel + header + close X).
 */

import { useCallback, useEffect, useState } from 'react';
import {
  searchRegistryApi,
  cloneFromRegistryApi,
  getErrorMessage,
  type RegistryEntry,
  type GeneratedCanvasSpec,
} from '../../services/api';

// ============================================================================
// Props
// ============================================================================

export interface RegistryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onClone?: (snapshot: GeneratedCanvasSpec) => void;
}

// ============================================================================
// Component
// ============================================================================

export function RegistryModal({ isOpen, onClose, onClone }: RegistryModalProps) {
  const [scope, setScope] = useState<'all' | 'mine' | 'public'>('all');
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<RegistryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloning, setCloning] = useState<string | null>(null); // agent_slug being cloned

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const results = await searchRegistryApi({ q: query || undefined, scope });
      setEntries(results);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [query, scope]);

  useEffect(() => {
    if (isOpen) {
      void load();
    }
  }, [isOpen, load]);

  const handleClone = async (slug: string) => {
    if (!onClone) return;
    setCloning(slug);
    setError(null);
    try {
      const result = await cloneFromRegistryApi(slug);
      onClone(result.canvas_snapshot);
      onClose();
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setCloning(null);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    void load();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative bg-white rounded-xl shadow-lg w-full max-w-4xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 tracking-tight">
              Agent Registry
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Browse and clone published agent blueprints
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Close"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              viewBox="0 0 24 24"
            >
              <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Search bar */}
        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50">
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or description..."
              className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as 'all' | 'mine' | 'public')}
              className="px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
            >
              <option value="all">All visible</option>
              <option value="mine">My agents</option>
              <option value="public">Public</option>
            </select>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Searching...' : 'Search'}
            </button>
          </form>
        </div>

        {/* Error banner */}
        {error && (
          <div className="mx-6 mt-4 px-3 py-2 rounded-lg border border-red-200 bg-red-50 text-xs text-red-700">
            {error}
          </div>
        )}

        {/* Content area */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading && entries.length === 0 ? (
            <div className="text-sm text-gray-500">Loading agents...</div>
          ) : entries.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-sm font-medium text-gray-700 mb-1">
                No agents found
              </div>
              <div className="text-xs text-gray-500">
                {query
                  ? 'Try a different search term or scope'
                  : 'No published agents match your scope'}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {entries.map((entry) => (
                <div
                  key={entry.agent_slug}
                  className="border border-gray-200 rounded-lg p-4 bg-white hover:border-gray-300 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="text-sm font-semibold text-gray-900 tracking-tight">
                          {entry.display_name}
                        </h3>
                        <span
                          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${
                            entry.visibility === 'public'
                              ? 'bg-green-100 text-green-700'
                              : entry.visibility === 'org'
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {entry.visibility}
                        </span>
                        {entry.is_owner && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 text-[10px] font-medium uppercase tracking-wide">
                            owner
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-600 mb-2 line-clamp-2">
                        {entry.description || 'No description provided.'}
                      </p>
                      {entry.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-2">
                          {entry.tags.map((tag) => (
                            <span
                              key={tag}
                              className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 text-[10px]"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="flex items-center gap-3 text-[10px] text-gray-500">
                        <span className="font-variant-numeric: tabular-nums">
                          {entry.usage_count} clone{entry.usage_count !== 1 ? 's' : ''}
                        </span>
                        {entry.source_runtime_name && (
                          <span className="font-mono text-[9px]">
                            {entry.source_runtime_name}
                          </span>
                        )}
                        <span>
                          {new Date(entry.updated_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleClone(entry.agent_slug)}
                      disabled={cloning !== null || !onClone}
                      className="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
                    >
                      {cloning === entry.agent_slug ? 'Cloning...' : 'Add to canvas'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
