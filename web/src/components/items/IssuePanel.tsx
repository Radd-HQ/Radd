import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { Maximize2, X } from "lucide-react";
import { useDialogFocus } from "../../lib/dialog-focus";
import { registerDismiss } from "../../lib/dismiss-stack";
import { startHorizontalDrag } from "../../lib/drag";
import { PeekSurfaceContext, useItemByKey, usePeek } from "../../lib/hooks";
import {
  PEEK_DEFAULT_WIDTH,
  PEEK_MAX_WIDTH,
  PEEK_MIN_WIDTH,
  PEEK_WIDTH_STORAGE_KEY,
} from "../../lib/constants";
import { removeRecentItem } from "../../lib/recent";
import { ItemDetailBody } from "../../routes/item-detail";
import { RequestPanelBody } from "../requests/RequestPanelBody";
import { Button } from "../Button";
import { Spinner } from "../Spinner";

/**
 * Issue side panel (spec 25): a right-side drawer that opens over any view when
 * `?peek=<itemKey>` is set. Clicking an issue opens it here (staying on the
 * view — Back closes it); the ⤢ button expands to the full `/issues/$key` page.
 */
export function IssuePanel() {
  const { peekKey, close, expand } = usePeek();
  const panelRef = useRef<HTMLElement>(null);
  useDialogFocus(panelRef, Boolean(peekKey));
  const closeRef = useRef(close);
  closeRef.current = close;

  useEffect(() => {
    if (!peekKey) return;
    // Dismiss-stack, not a bare document listener: a peek can sit above a
    // modal (a similar-issue click from the New Item form), and one Esc must
    // close only the panel, never the draft underneath.
    return registerDismiss((event) => {
      // Don't hijack Esc while editing a field inside the panel.
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return false;
      closeRef.current();
      return true;
    });
  }, [Boolean(peekKey)]);

  // Width is user-set and sticky: the peek is where you triage, and how wide
  // you want it is a standing preference, not a per-open one.
  const [width, setWidth] = useState(PEEK_DEFAULT_WIDTH);
  useEffect(() => {
    const stored = Number(window.localStorage.getItem(PEEK_WIDTH_STORAGE_KEY));
    if (Number.isFinite(stored) && stored > 0) {
      setWidth(Math.min(PEEK_MAX_WIDTH, Math.max(PEEK_MIN_WIDTH, stored)));
    }
  }, []);

  const startResize = (event: ReactPointerEvent) =>
    startHorizontalDrag(event, {
      start: width,
      min: PEEK_MIN_WIDTH,
      max: PEEK_MAX_WIDTH,
      // Right-anchored: dragging LEFT (negative dx) makes it wider.
      direction: -1,
      onMove: setWidth,
      onEnd: (final) => window.localStorage.setItem(PEEK_WIDTH_STORAGE_KEY, String(final)),
    });

  if (!peekKey) return null;
  // Use the same portal layer as Modal: opening order must determine which
  // dialog is above the other, including a peek opened from an unfinished form.
  return createPortal(
    <>
      <div className="fixed inset-0 z-40 bg-black/50 animate-fade-in" onClick={close} aria-hidden />
      <aside
        ref={panelRef}
        tabIndex={-1}
        aria-modal="true"
        role="dialog"
        aria-label={`Issue ${peekKey}`}
        style={{ width, maxWidth: "calc(100vw - 1rem)" }}
        className="fixed inset-y-0 right-0 z-50 m-2 flex max-w-full animate-panel-in flex-col overflow-hidden rounded-2xl border border-subtle bg-base shadow-modal"
      >
        {/* Drag the left edge to resize. The drawer grows LEFTWARDS (it is
            right-anchored), so a rightward pointer move shrinks it. */}
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize panel"
          onPointerDown={startResize}
          className="absolute inset-y-0 left-0 z-10 w-1.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60"
          title="Drag to resize"
        />
        <div className="flex shrink-0 items-center gap-2 border-b border-subtle px-3 py-2">
          <button
            type="button"
            onClick={close}
            aria-label="Close panel"
            className="rounded p-1 text-fg-secondary hover:bg-elevated hover:text-heading cursor-pointer"
          >
            <X size={16} />
          </button>
          <button
            type="button"
            onClick={() => expand(peekKey)}
            title={`Open ${peekKey}`}
            className="cursor-pointer font-mono text-xs text-fg-muted hover:text-accent-text hover:underline"
          >
            {peekKey}
          </button>
          <Button
            variant="secondary"
            size="sm"
            className="ml-auto"
            onClick={() => expand(peekKey)}
            title="Open full page"
          >
            <Maximize2 size={13} aria-hidden />
            Open full page
          </Button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Issue-reference cards inside the panel behave peek-aware
              (promote-then-peek) — see useOpenIssueRef. */}
          <PeekSurfaceContext.Provider value={true}>
            <PanelBody itemKey={peekKey} />
          </PeekSurfaceContext.Provider>
        </div>
      </aside>
    </>, document.body
  );
}

function PanelBody({ itemKey }: { itemKey: string }) {
  const { project, item, isPending, isError } = useItemByKey(itemKey);
  // A dead key (deleted item) shouldn't keep haunting the recently-viewed trail.
  useEffect(() => {
    if (isError) removeRecentItem(itemKey);
  }, [isError, itemKey]);
  if (isPending) return <Spinner label="Loading item…" />;
  if (isError || !project || !item) {
    // Not readable as an ISSUE — but it may still be a request this person
    // filed, or one shared with their team (RADD-803). A requester holds no
    // `item.read`, so the issue fetch failing is the NORMAL path for them, not
    // an error: fall through to the requester body rather than telling somebody
    // their own request does not exist.
    //
    // This is why there is one peek and not two panels. The drawer, the
    // `?peek=` param and the dismiss behaviour are the same object; only what
    // goes inside it depends on who is looking.
    return <RequestPanelBody requestKey={itemKey} />;
  }
  return <ItemDetailBody key={item.id} project={project} item={item} />;
}
