/**
 * A collapsible side panel — the one pattern for anything docked to the edge of
 * a work surface (the roadmap's Unscheduled tray, the issue properties rail, …).
 *
 * Collapsed it becomes a slim vertical strip carrying the panel's icon, its
 * label rotated to read bottom-up, and its badge, so you can still tell what is
 * behind it. That is the same bargain the main sidebar's icon rail makes: give
 * back the width, keep the affordance.
 *
 * State is per-panel and persisted, because "I want more room on the roadmap"
 * is a standing preference, not a per-visit one.
 *
 * Narrow layouts: a panel that STACKS below its content instead of sitting
 * beside it has no width to give back, so pass `sideAt` with the container-query
 * breakpoint where it docks — below that the panel renders plain and the toggle
 * disappears.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen, type LucideIcon } from "lucide-react";
import { sidePanelStorageKey } from "../lib/constants";

/** Tailwind only generates classes it can SEE — `\`${sideAt}:block\`` builds a
 * name at runtime that never enters the stylesheet (this was a live bug: the
 * docked issue rail's collapse toggle rendered `display: none` forever). Every
 * docked breakpoint therefore gets its static class set; add a row when a new
 * `sideAt` value appears. */
const DOCKED_CLASSES = {
  "@3xl": {
    /** Collapsed aside: full width while stacked, the slim strip when docked. */
    stripWidth: "w-full @3xl:w-9",
    /** The strip's expand button: pointless while stacked. */
    stripButton: "hidden @3xl:flex",
    /** Collapsed + stacked: nothing to collapse, so the content stays. */
    stackedContent: "@3xl:hidden",
    /** Collapse toggles: only shown where collapsing buys width back. Queries
     * the NAMED page container — an embedded `<SidePanelCollapse>` can sit
     * inside a smaller `@container` (the fields card runs its own), where an
     * unnamed query would resolve against the card, never the page. The
     * docking surface must therefore carry `@container/page`. */
    toggle: "hidden @3xl/page:block",
  },
} as const;
export type SidePanelSideAt = keyof typeof DOCKED_CLASSES;

const SidePanelContext = createContext<{ toggle: () => void; sideAt?: SidePanelSideAt } | null>(
  null,
);

/** The collapse toggle for a `frameless` SidePanel — place it inside the
 * panel's own chrome (a card header). Same docked gating as the built-in
 * header button; renders nothing outside a SidePanel. */
export function SidePanelCollapse({ className = "" }: { className?: string }) {
  const panel = useContext(SidePanelContext);
  if (!panel) return null;
  return (
    <button
      type="button"
      onClick={panel.toggle}
      aria-expanded
      title="Hide panel"
      className={
        "cursor-pointer rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg " +
        "focus-visible:outline-2 focus-visible:outline-focus " +
        (panel.sideAt ? `${DOCKED_CLASSES[panel.sideAt].toggle} ` : "") +
        className
      }
    >
      <PanelLeftClose size={14} aria-hidden />
    </button>
  );
}

interface SidePanelProps {
  /** Stable id for the persisted collapse state (per surface, not per route). */
  panelKey: string;
  label: string;
  icon: LucideIcon;
  /** Small count shown in the header and on the collapsed strip. */
  badge?: ReactNode;
  /** Container-query prefix at which the panel docks to the side, e.g. "@3xl"
   *  (must have a DOCKED_CLASSES row — Tailwind needs the static classes).
   *  Omit for panels that are always side-docked (the roadmap tray). */
  sideAt?: SidePanelSideAt;
  /** Suppress the built-in expanded header: the panel's first card carries the
   *  identity instead, and a `<SidePanelCollapse>` inside the children takes
   *  over the toggle. The collapsed strip still shows icon + label. */
  frameless?: boolean;
  /** Classes applied in BOTH states — position only (order, margins). Must NOT
   *  carry width: the collapsed strip sets its own, and a leftover `w-72` here
   *  simply beats it, collapsing the state without collapsing the panel. */
  className?: string;
  /** Classes for the EXPANDED panel only: width, scrolling, card treatment. */
  expandedClassName?: string;
  children: ReactNode;
}

export function SidePanel({
  panelKey,
  label,
  icon: Icon,
  badge,
  sideAt,
  frameless = false,
  className = "",
  expandedClassName = "",
  children,
}: SidePanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    setCollapsed(window.localStorage.getItem(sidePanelStorageKey(panelKey)) === "1");
  }, [panelKey]);
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    window.localStorage.setItem(sidePanelStorageKey(panelKey), next ? "1" : "0");
  };

  // Below `sideAt` the panel is stacked, so collapsing would hide content
  // without buying anything — the strip and the hiding are gated to the docked
  // breakpoint, and the panel renders normally underneath it.
  const docked = sideAt ? DOCKED_CLASSES[sideAt] : null;

  if (collapsed) {
    return (
      <aside
        className={
          "flex shrink-0 flex-col rounded-xl border border-subtle bg-surface shadow-lift " +
          (docked ? `${docked.stripWidth} ` : "w-9 ") +
          className  // position only — `expandedClassName` (the width) is dropped
        }
        aria-label={label}
      >
        <button
          type="button"
          onClick={toggle}
          aria-expanded={false}
          title={`Show ${label}`}
          className={
            "group w-full cursor-pointer flex-col items-center gap-2 rounded-xl py-2.5 " +
            "text-fg-muted hover:bg-elevated/60 hover:text-fg " +
            "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
            (docked ? docked.stripButton : "flex")
          }
        >
          <PanelLeftOpen size={15} aria-hidden />
          <Icon size={14} aria-hidden />
          {badge !== undefined && (
            <span className="rounded bg-elevated px-1 py-px text-[10px] tabular-nums text-fg-secondary">
              {badge}
            </span>
          )}
          <span
            className="mt-1 text-[11px] font-medium tracking-wide whitespace-nowrap"
            style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
          >
            {label}
          </span>
        </button>
        {/* Stacked (below `sideAt`): nothing to collapse, so show the content. */}
        {docked && <div className={docked.stackedContent}>{children}</div>}
      </aside>
    );
  }

  return (
    <SidePanelContext.Provider value={{ toggle, sideAt }}>
      <aside className={`${className} ${expandedClassName}`} aria-label={label}>
        {!frameless && (
          <div className="flex items-center gap-2 px-4 pt-3 pb-1">
            <Icon size={14} className="text-fg-muted" aria-hidden />
            <h2 className="text-[13px] font-semibold text-fg">{label}</h2>
            {badge !== undefined && (
              <span className="rounded bg-elevated px-1.5 py-px text-[11px] tabular-nums text-fg-secondary">
                {badge}
              </span>
            )}
            <button
              type="button"
              onClick={toggle}
              aria-expanded
              title={`Hide ${label}`}
              className={
                "ml-auto cursor-pointer rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg " +
                "focus-visible:outline-2 focus-visible:outline-focus " +
                (docked ? docked.toggle : "")
              }
            >
              <PanelLeftClose size={14} aria-hidden />
            </button>
          </div>
        )}
        {children}
      </aside>
    </SidePanelContext.Provider>
  );
}
