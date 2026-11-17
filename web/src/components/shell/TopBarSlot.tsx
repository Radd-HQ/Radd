import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

/**
 * The top bar's QUERY SLOT: the prominent center bar is owned by the page.
 * A view page portals its live SLQ filter editor into the slot (the bar then
 * IS the view's filter); pages that claim nothing get the default
 * search-the-app pill instead. Plain React context + portal — no globals.
 */

interface TopBarSlotState {
  el: HTMLElement | null;
  setEl: (el: HTMLElement | null) => void;
  occupied: boolean;
  setOccupied: (occupied: boolean) => void;
}

const TopBarSlotContext = createContext<TopBarSlotState | null>(null);

export function TopBarSlotProvider({ children }: { children: ReactNode }) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [occupied, setOccupied] = useState(false);
  return (
    <TopBarSlotContext.Provider value={{ el, setEl, occupied, setOccupied }}>
      {children}
    </TopBarSlotContext.Provider>
  );
}

/** For the TopBar itself: where to mount the slot + whether a page filled it. */
export function useTopBarSlotHost(): {
  setEl: (el: HTMLElement | null) => void;
  occupied: boolean;
} {
  const slot = useContext(TopBarSlotContext);
  return { setEl: slot?.setEl ?? (() => {}), occupied: slot?.occupied ?? false };
}

/** Renders `children` INTO the top bar's query slot for this page's lifetime.
 *
 *  `scope` says what the bar filters while the page owns it (RADD-1562). The
 *  same input, in the same place, is global search on pages that claim nothing
 *  and this page's filter on pages that do; nothing used to say which. */
export function TopBarQuery({ children, scope = "This page" }: { children: ReactNode; scope?: string }) {
  const slot = useContext(TopBarSlotContext);
  const setOccupied = slot?.setOccupied;
  useEffect(() => {
    if (!setOccupied) return;
    setOccupied(true);
    return () => setOccupied(false);
  }, [setOccupied]);
  if (!slot?.el) return null;
  return createPortal(
    <div className="flex min-w-0 items-center gap-2">
      <span
        data-topbar-scope
        title={`This bar filters ${scope.toLowerCase()}. Search everything with the Search entry in the sidebar.`}
        className="hidden shrink-0 rounded border border-subtle bg-elevated px-1.5 py-0.5 text-meta text-fg-secondary sm:inline"
      >
        Filter: {scope}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>,
    slot.el,
  );
}
