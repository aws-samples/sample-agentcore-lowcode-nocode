/**
 * ModalShell - Shared modal container with scrim, backdrop, focus trap, and Escape handling.
 * Enforces consistent modal UX across the app.
 */

import { useEffect, useCallback, type ReactNode } from 'react';

// ============================================================================
// Types
// ============================================================================

export interface ModalShellProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
  'data-testid'?: string;
}

// ============================================================================
// ModalShell Component
// ============================================================================

export function ModalShell({
  isOpen,
  onClose,
  title,
  children,
  footer,
  width = 'var(--modal-width, 540px)',
  'data-testid': dataTestId = 'modal',
}: ModalShellProps) {
  // Handle escape key to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) {
        onClose();
      }
    },
    [onClose]
  );

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      style={{ backdropFilter: 'blur(2px)' }}
      onClick={handleBackdropClick}
      data-testid={`${dataTestId}-backdrop`}
    >
      <div
        className="bg-white shadow-2xl max-h-[90vh] flex flex-col"
        style={{ width, borderRadius: 'var(--radius-surface)' }}
        data-testid={dataTestId}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${dataTestId}-title`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <h2 id={`${dataTestId}-title`} className="text-base font-semibold truncate pr-2" style={{ color: 'var(--color-text-primary)' }}>
            {title}
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
            style={{ borderRadius: 'var(--radius-control)' }}
            aria-label="Close modal"
            data-testid={`${dataTestId}-close-button`}
          >
            <svg className="w-5 h-5" style={{ color: 'var(--color-text-secondary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        {children}

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-3 px-5 py-3 border-t bg-gray-50" style={{ borderColor: 'var(--color-border)', borderBottomLeftRadius: 'var(--radius-surface)', borderBottomRightRadius: 'var(--radius-surface)' }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export default ModalShell;
