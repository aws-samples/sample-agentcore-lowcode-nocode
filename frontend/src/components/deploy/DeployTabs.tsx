/**
 * DeployTabs — two-row, icon-forward tab control for the deploy drawer.
 *
 * - Row 1 (primary): Deploy, Chat — always visible.
 * - Row 2 (post-deploy): Triggers, Versions, Analytics — enabled once deployed.
 *
 * Accessibility: role=tablist / role=tab + aria-selected + left/right arrow
 * keyboard navigation, lock icon + tooltip for disabled tabs.
 */

import { useCallback, useRef } from 'react';
import type { KeyboardEvent } from 'react';

export type DeployTabId = 'deploy' | 'chat' | 'triggers' | 'versions' | 'analytics';

interface TabDef {
  id: DeployTabId;
  label: string;
  row: 1 | 2;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  {
    id: 'deploy',
    label: 'Deploy',
    row: 1,
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 2L11 13" />
        <path d="M22 2l-7 20-4-9-9-4 20-7z" />
      </svg>
    ),
  },
  {
    id: 'chat',
    label: 'Chat',
    row: 1,
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
  {
    id: 'triggers',
    label: 'Triggers',
    row: 2,
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    id: 'versions',
    label: 'Versions',
    row: 2,
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v5h5" />
        <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
        <path d="M12 7v5l4 2" />
      </svg>
    ),
  },
  {
    id: 'analytics',
    label: 'Analytics',
    row: 2,
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="20" x2="12" y2="10" />
        <line x1="18" y1="20" x2="18" y2="4" />
        <line x1="6" y1="20" x2="6" y2="16" />
      </svg>
    ),
  },
];

const LOCK_ICON = (
  <svg className="w-3 h-3 opacity-60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

export interface DeployTabsProps {
  activeTab: DeployTabId;
  isDeployed: boolean;
  /** Show a small green dot on the Chat tab when it's ready. */
  chatReady?: boolean;
  onChange: (id: DeployTabId) => void;
}

export function DeployTabs({ activeTab, isDeployed, chatReady, onChange }: DeployTabsProps) {
  const disabledTooltip = 'Deploy the agent first to unlock this tab';
  const listRef = useRef<HTMLDivElement>(null);

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      // Navigate only through enabled tabs in the visual order.
      const enabled: DeployTabId[] = ['deploy'];
      if (isDeployed) enabled.push('chat', 'triggers', 'versions', 'analytics');
      const idx = enabled.indexOf(activeTab);
      let nextIdx = idx;
      if (e.key === 'ArrowRight') nextIdx = Math.min(enabled.length - 1, idx + 1);
      else if (e.key === 'ArrowLeft') nextIdx = Math.max(0, idx - 1);
      else if (e.key === 'Home') nextIdx = 0;
      else if (e.key === 'End') nextIdx = enabled.length - 1;
      if (nextIdx !== idx) {
        onChange(enabled[nextIdx]);
        // Focus the newly active tab
        setTimeout(() => {
          const el = listRef.current?.querySelector<HTMLButtonElement>(`[data-tab-id="${enabled[nextIdx]}"]`);
          el?.focus();
        }, 0);
      }
    },
    [activeTab, isDeployed, onChange],
  );

  const renderTab = (t: TabDef) => {
    const disabled = t.id !== 'deploy' && !isDeployed;
    const isActive = activeTab === t.id;
    const tooltip = disabled ? disabledTooltip : t.label;
    return (
      <button
        key={t.id}
        data-tab-id={t.id}
        role="tab"
        aria-selected={isActive}
        aria-disabled={disabled}
        aria-label={t.label}
        title={tooltip}
        tabIndex={isActive ? 0 : -1}
        disabled={disabled}
        onClick={() => !disabled && onChange(t.id)}
        onKeyDown={onKeyDown}
        className={[
          'relative flex-1 min-w-0 py-2 px-2 rounded-md text-xs font-medium transition-all',
          'flex items-center justify-center gap-1.5',
          isActive
            ? 'bg-white text-[#0972d3] shadow-sm border border-[#e9ebed]'
            : disabled
              ? 'text-[#b8bfc8] cursor-not-allowed'
              : 'text-[#5f6b7a] hover:text-[#16191f] hover:bg-white/60 border border-transparent',
        ].join(' ')}
      >
        <span className="flex-shrink-0">{t.icon}</span>
        <span className="truncate">{t.label}</span>
        {disabled && <span className="flex-shrink-0 ml-0.5">{LOCK_ICON}</span>}
        {t.id === 'chat' && chatReady && !disabled && (
          <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full flex-shrink-0" aria-label="ready" />
        )}
      </button>
    );
  };

  const primary = TABS.filter((t) => t.row === 1);
  const secondary = TABS.filter((t) => t.row === 2);

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label="Deploy panel sections"
      className="border-b border-[#e9ebed] bg-[#f7f8f9] px-2 pt-2 pb-1.5 space-y-1.5"
    >
      <div className="flex gap-1.5">{primary.map(renderTab)}</div>
      <div className="flex gap-1.5">{secondary.map(renderTab)}</div>
    </div>
  );
}

export default DeployTabs;
