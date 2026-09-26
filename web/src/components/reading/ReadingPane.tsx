import { useCallback, useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { ReadingPaneContext, useActiveSlotPlugins, type ReadingPanel } from "@radd/plugin-sdk";

/**
 * The reading pane (RADD-772, generalised in RADD-1395): a panel BESIDE the text being read, where
 * an answer has room — the dead space next to the reading column — instead of a cramped popover or
 * the w-72 rail. A contribution opens it with `useReadingPane()`; the frame (heading, close,
 * placement) is the host's, the body is the contribution's.
 *
 * A panel opened from a plugin's contribution is that plugin's: when the plugin is withdrawn the
 * panel closes, and its body unmounts with it (which is what stops any stream it was reading).
 */

interface OpenPanel {
  panel: ReadingPanel;
  owner: string | null;
  /** Bumped per open, so opening the same panel again renders its body afresh. */
  runId: number;
}

/** The pane's state, for a surface that places the panel itself (the issue page). */
export function useReadingPaneState() {
  const [current, setCurrent] = useState<OpenPanel | null>(null);
  const open = useCallback((panel: ReadingPanel, owner: string | null) => {
    setCurrent((previous) => ({ panel, owner, runId: (previous?.runId ?? 0) + 1 }));
  }, []);
  const close = useCallback(() => setCurrent(null), []);
  // A withdrawn plugin's panel closes rather than lingering with its body gone.
  const active = useActiveSlotPlugins();
  const withdrawn = current?.owner != null && !active.includes(current.owner);
  useEffect(() => {
    if (withdrawn) setCurrent(null);
  }, [withdrawn]);
  return { current: withdrawn ? null : current, open, close };
}

/** The panel's frame: its heading, a close button, and the contribution's body. */
export function ReadingPanelView({
  open,
  onClose,
  className = "",
}: {
  open: OpenPanel;
  onClose: () => void;
  className?: string;
}) {
  const { panel } = open;
  return (
    <aside
      aria-label={panel.label ?? panel.title}
      data-reading-panel
      className={`flex flex-col rounded-xl border border-subtle bg-surface shadow-lift ${className}`}
    >
      <div className="flex shrink-0 items-center gap-1.5 border-b border-subtle px-3 py-2">
        {panel.icon}
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{panel.title}</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${panel.label ?? panel.title}`}
          className="ml-auto rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
        >
          <X size={13} />
        </button>
      </div>
      <div key={open.runId} className="min-h-0 flex-1 overflow-y-auto p-3">
        {panel.render()}
      </div>
    </aside>
  );
}

/**
 * A reading surface with the pane beside it — the SDK's `ReadingPane`, which the wiki wraps its
 * page in. Beside the content at @4xl, stacked above it below that; the caller supplies the
 * `@container/page` ancestor the variants query.
 *
 * `children` is the page, rendered in place whatever the pane does: remounting it would throw
 * away an open edit session.
 */
export function ReadingPane({ children }: { children: ReactNode }) {
  const pane = useReadingPaneState();
  return (
    <ReadingPaneContext.Provider value={pane.open}>
      <div className="flex flex-col items-start gap-3 @4xl:flex-row @4xl:justify-center">
        {pane.current && (
          <ReadingPanelView
            open={pane.current}
            onClose={pane.close}
            className="order-first m-6 mb-0 w-[calc(100%-3rem)] @4xl:sticky @4xl:top-0 @4xl:order-2 @4xl:ml-0 @4xl:max-h-[calc(100vh-8rem)] @4xl:w-96 @4xl:shrink-0"
          />
        )}
        <div className="w-full min-w-0 flex-1 @4xl:w-auto">{children}</div>
      </div>
    </ReadingPaneContext.Provider>
  );
}
