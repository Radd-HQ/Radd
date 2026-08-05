import { useState } from "react";
import { cardDisplayStorageKey } from "./constants";

/**
 * Per-surface card display config (the "widget slots" of issue rows/cards):
 * which metadata chips render on items in a list/board/planning surface, how
 * many labels before the +N overflow chip, and a zoom scale for the whole
 * surface. Persisted per surface key in localStorage — `view:<viewId>`,
 * `list:<projectId>`, `board:<projectId>`, `planning:<projectId>` — so every
 * saved view/board remembers its own configuration.
 *
 * Structural parts of a row/card (kind icon, key, title, star, flag) are NOT
 * slots — they always render.
 */

export const CardSlot = {
  type: "type",
  parent: "parent",
  labels: "labels",
  cycle: "cycle",
  release: "release",
  targetDate: "target_date",
  team: "team",
  priority: "priority",
  assignee: "assignee",
  // Nearest-to-breach SLA timer chip (spec 63) — default OFF everywhere; a
  // surface only fires the batch request while the slot is enabled.
  sla: "sla",
  // Story-points "Np" chip (spec 70) — default OFF like sla; renders only on
  // items that carry points, so non-opted-in projects show nothing.
  points: "points",
  // Epic progress bar (spec 76) — default ON for board/list presets; renders
  // only on epic-kind items, fed by the POST /items/rollup batch.
  progress: "progress",
  // Logged time ("5h 20m") from the POST /items/timelog/batch — like sla, the
  // surface only fires the batch while the slot is on; items with nothing
  // logged render nothing, so timelogging-off projects stay clean.
  loggedTime: "logged_time",
  state: "state",
} as const;
export type CardSlotValue = (typeof CardSlot)[keyof typeof CardSlot];

/** Canonical slot order — surfaces render enabled slots in this sequence
 *  (state intentionally last: it sits at the far right edge of rows). */
export const CARD_SLOT_ORDER: readonly CardSlotValue[] = [
  CardSlot.type,
  CardSlot.parent,
  CardSlot.labels,
  CardSlot.cycle,
  CardSlot.release,
  CardSlot.targetDate,
  CardSlot.team,
  CardSlot.priority,
  CardSlot.assignee,
  CardSlot.sla,
  CardSlot.points,
  CardSlot.progress,
  CardSlot.loggedTime,
  CardSlot.state,
];

export const CARD_SLOT_LABELS: Record<CardSlotValue, string> = {
  [CardSlot.type]: "Issue type",
  [CardSlot.parent]: "Parent",
  [CardSlot.labels]: "Labels",
  [CardSlot.cycle]: "Cycle",
  [CardSlot.release]: "Release",
  [CardSlot.targetDate]: "Target date",
  [CardSlot.team]: "Team",
  [CardSlot.priority]: "Priority",
  [CardSlot.assignee]: "Assignee",
  [CardSlot.sla]: "SLA",
  [CardSlot.points]: "Points",
  [CardSlot.progress]: "Progress",
  [CardSlot.loggedTime]: "Logged time",
  [CardSlot.state]: "State",
};

export interface CardDisplayConfig {
  /** Enabled slots (order is canonical, not the array's). */
  slots: CardSlotValue[];
  /** Label chips shown before collapsing into a "+N" chip. */
  maxLabels: number;
  /** Surface zoom, 0.7–1.3 (CSS `zoom` on the items container). */
  scale: number;
}

/** Matches what list rows showed before slots existed, plus the state pill. */
export const DEFAULT_LIST_SLOTS: readonly CardSlotValue[] = [
  CardSlot.type,
  CardSlot.labels,
  CardSlot.team,
  CardSlot.priority,
  CardSlot.assignee,
  CardSlot.progress,
  CardSlot.state,
];

/** Matches the pre-slots board card (state is the column, so off by default);
 * logged time rides along by default and quiet-degrades to nothing on
 * projects that don't log time. */
export const DEFAULT_BOARD_SLOTS: readonly CardSlotValue[] = [
  CardSlot.type,
  CardSlot.parent,
  CardSlot.labels,
  CardSlot.cycle,
  CardSlot.release,
  CardSlot.team,
  CardSlot.priority,
  CardSlot.assignee,
  CardSlot.progress,
  CardSlot.loggedTime,
];

/** Queues (spec 64) have a FIXED column set — no DisplayMenu. Reporter and
 *  the always-on SLA chip are queue table columns (spec 108), so `sla` is
 *  deliberately not in this list. */
export const DEFAULT_QUEUE_SLOTS: readonly CardSlotValue[] = [
  CardSlot.type,
  CardSlot.labels,
  CardSlot.priority,
  CardSlot.assignee,
  CardSlot.state,
];

export const DEFAULT_MAX_LABELS = 3;
export const SCALE_MIN = 0.7;
export const SCALE_MAX = 1.3;

export function defaultCardDisplay(slots: readonly CardSlotValue[]): CardDisplayConfig {
  return { slots: [...slots], maxLabels: DEFAULT_MAX_LABELS, scale: 1 };
}

function readStored(surfaceKey: string, defaults: CardDisplayConfig): CardDisplayConfig {
  try {
    const raw = window.localStorage.getItem(cardDisplayStorageKey(surfaceKey));
    if (!raw) return defaults;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return defaults;
    const candidate = parsed as Partial<CardDisplayConfig>;
    const known = new Set<string>(Object.values(CardSlot));
    return {
      slots: Array.isArray(candidate.slots)
        ? candidate.slots.filter((slot): slot is CardSlotValue => known.has(slot))
        : defaults.slots,
      maxLabels:
        typeof candidate.maxLabels === "number" && candidate.maxLabels >= 0
          ? candidate.maxLabels
          : defaults.maxLabels,
      scale:
        typeof candidate.scale === "number"
          ? Math.min(SCALE_MAX, Math.max(SCALE_MIN, candidate.scale))
          : defaults.scale,
    };
  } catch {
    return defaults;
  }
}

export interface CardDisplayState {
  display: CardDisplayConfig;
  update: (patch: Partial<CardDisplayConfig>) => void;
  toggleSlot: (slot: CardSlotValue) => void;
  reset: () => void;
}

/** Card display config for one surface, persisted per surface key. */
export function useCardDisplay(
  surfaceKey: string,
  defaultSlots: readonly CardSlotValue[],
): CardDisplayState {
  const defaults = defaultCardDisplay(defaultSlots);
  // Keyed state: re-seed from storage when the surface changes (view → view nav)
  // OR the defaults change (the view's type resolves after load — a board's
  // defaults must not be pinned to the pre-load list preset).
  const seedKey = `${surfaceKey}|${defaultSlots.join(",")}`;
  const [entry, setEntry] = useState(() => ({
    key: seedKey,
    config: readStored(surfaceKey, defaults),
  }));
  const display = entry.key === seedKey ? entry.config : readStored(surfaceKey, defaults);
  if (entry.key !== seedKey) setEntry({ key: seedKey, config: display });

  const write = (config: CardDisplayConfig) => {
    setEntry({ key: seedKey, config });
    try {
      window.localStorage.setItem(cardDisplayStorageKey(surfaceKey), JSON.stringify(config));
    } catch {
      // Best-effort — the config still applies for the session.
    }
  };

  return {
    display,
    update: (patch) => write({ ...display, ...patch }),
    toggleSlot: (slot) =>
      write({
        ...display,
        slots: display.slots.includes(slot)
          ? display.slots.filter((s) => s !== slot)
          : [...display.slots, slot],
      }),
    reset: () => {
      setEntry({ key: seedKey, config: defaults });
      try {
        window.localStorage.removeItem(cardDisplayStorageKey(surfaceKey));
      } catch {
        // Best-effort.
      }
    },
  };
}
