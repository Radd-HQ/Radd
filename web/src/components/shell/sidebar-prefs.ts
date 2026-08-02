/** Sidebar collapse prefs (spec 60): pin/unpin sections, fold project trees — localStorage-persisted. */

import { useSyncExternalStore } from "react";
import { SIDEBAR_PREFS_STORAGE_KEY } from "../../lib/constants";

interface SidebarPrefs {
  /** Whole-sidebar collapse: false = full sidebar, true = slim icon rail. */
  railCollapsed: boolean;
  /** Section ids the user collapsed (sections default to expanded). */
  collapsedSections: string[];
  /** Project ids explicitly expanded (projects default to COLLAPSED). */
  expandedProjects: string[];
  /** Project ids explicitly collapsed — beats the current-route auto-expand. */
  collapsedProjects: string[];
}

function readSidebarPrefs(): SidebarPrefs {
  try {
    const raw = window.localStorage.getItem(SIDEBAR_PREFS_STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<SidebarPrefs>) : {};
    return {
      railCollapsed: parsed.railCollapsed ?? false,
      collapsedSections: parsed.collapsedSections ?? [],
      expandedProjects: parsed.expandedProjects ?? [],
      collapsedProjects: parsed.collapsedProjects ?? [],
    };
  } catch {
    return {
      railCollapsed: false,
      collapsedSections: [],
      expandedProjects: [],
      collapsedProjects: [],
    };
  }
}

// ONE module-level store, not per-component state: the rail toggle lives in
// the top bar while section folds live in the sidebar — two independent
// useState copies would clobber each other's writes on the shared key.
let prefs = readSidebarPrefs();
const listeners = new Set<() => void>();

function write(next: SidebarPrefs) {
  prefs = next;
  try {
    window.localStorage.setItem(SIDEBAR_PREFS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Best-effort — collapse still works for the session.
  }
  listeners.forEach((notify) => notify());
}

const subscribe = (notify: () => void) => {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
};

export function useSidebarPrefs() {
  const current = useSyncExternalStore(subscribe, () => prefs);
  const toggleSection = (id: string) =>
    write({
      ...prefs,
      collapsedSections: prefs.collapsedSections.includes(id)
        ? prefs.collapsedSections.filter((s) => s !== id)
        : [...prefs.collapsedSections, id],
    });
  const toggleProject = (id: string, effectiveExpanded: boolean) =>
    write({
      ...prefs,
      expandedProjects: effectiveExpanded
        ? prefs.expandedProjects.filter((p) => p !== id)
        : [...prefs.expandedProjects, id],
      collapsedProjects: effectiveExpanded
        ? [...prefs.collapsedProjects.filter((p) => p !== id), id]
        : prefs.collapsedProjects.filter((p) => p !== id),
    });
  const toggleRail = () => write({ ...prefs, railCollapsed: !prefs.railCollapsed });
  return { prefs: current, toggleSection, toggleProject, toggleRail };
}
