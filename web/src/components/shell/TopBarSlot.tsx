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

/** Renders `children` INTO the top bar's query slot for this page's lifetime. */
export function TopBarQuery({ children }: { children: ReactNode }) {
  const slot = useContext(TopBarSlotContext);
  const setOccupied = slot?.setOccupied;
  useEffect(() => {
    if (!setOccupied) return;
    setOccupied(true);
    return () => setOccupied(false);
  }, [setOccupied]);
  if (!slot?.el) return null;
  return createPortal(children, slot.el);
}
