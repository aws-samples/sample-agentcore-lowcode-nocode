/**
 * Harness Manager drawer (Task 11 — legacy entry point).
 *
 * This drawer is kept for backwards compatibility; the recommended path is
 * the right-hand "AgentCore Services" drawer which renders the same
 * <HarnessPanel /> body under its Harness tab.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { HarnessPanel } from './HarnessPanel';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function HarnessManager({ open, onClose }: Props) {
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
            className="fixed top-0 right-0 h-screen w-full sm:max-w-[640px] bg-white shadow-xl z-[100] flex flex-col"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-[#e9ebed] bg-[#232f3e]">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-md bg-[#ff9900] flex items-center justify-center">
                  <svg
                    className="w-4 h-4 text-white"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">
                    Harness Manager
                  </h2>
                  <p className="text-[11px] text-white/50">
                    AgentCore managed agent — model + tools + memory in one
                    resource
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close harness manager"
                className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
              >
                <svg
                  className="w-4 h-4 text-white/70"
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

            <div className="flex-1 overflow-y-auto">
              <HarnessPanel />
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

export default HarnessManager;
