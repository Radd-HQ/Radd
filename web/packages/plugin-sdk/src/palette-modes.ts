import { useState } from "react";
import { queryOptions, useQuery } from "@tanstack/react-query";
import type { PluginContribution } from "./plugin";
import { SlotId } from "./slots";
import { modeContribution, useContributedModes, type ContributedMode, type ModeIcon, type ModeSpec } from "./contributed-modes";

/** Command-palette MODES: a trailing "<label>: “<query>” — <hint>" row enters one, and the mode
 *  ANSWERS the query with rows (drawn and navigated like the palette's own) or streamed text. The
 *  palette owns input, debounce, keyboard and row chrome; the mode owns meaning and destinations. */

/** One row of an answer. Choosing it closes the palette and goes to `href`. */
export interface PaletteRow {
  /** Unique within the answer. */
  id: string;
  title: string;
  /** Where the row goes: a site-relative address (`/issues/TD-12`). */
  href: string;
  /** A short code before the title, set in the palette's key pill (an issue key). */
  badge?: string;
  /** An icon before the title. */
  icon?: ModeIcon;
  /** A line under the title. */
  subtitle?: string;
  /** Trailing and faint: a score, a kind. */
  hint?: string;
}

/** An answer of rows. `heading` labels them; `empty` is said when there are none. */
export interface PaletteRows {
  rows: PaletteRow[];
  heading?: string;
  empty?: string;
}

/** An answer in words. */
export interface PaletteText {
  text: string;
  heading?: string;
}

export type PaletteAnswer = PaletteRows | PaletteText;

export interface PaletteModeSpec extends ModeSpec {
  /** The input's placeholder inside the mode ("Search by meaning…"). */
  placeholder: string;
  /** Said while nothing is typed ("Type to search by meaning."). */
  prompt?: string;
  /** Said while the first answer is on its way (default "Searching…"). */
  busyLabel?: string;
  /**
   * Answer `query` (trimmed, debounced, never empty). Resolve rows or text; for text, `onText`
   * reports the answer so far (the whole text, not a chunk) while it streams. The palette aborts
   * `signal` when the query changes, the palette closes or the plugin is withdrawn. Reject with a
   * presentable error: its message is shown.
   */
  answer: (
    query: string,
    progress: { signal: AbortSignal; onText: (text: string) => void },
  ) => Promise<PaletteAnswer>;
}

export type PaletteMode = ContributedMode<PaletteModeSpec>;

/** The contribution row for `definePlugin({ contributions: [paletteMode({...})] })`. */
export function paletteMode(spec: PaletteModeSpec): PluginContribution {
  return modeContribution(SlotId.paletteMode, spec, `${spec.label} in the command palette`);
}

const acceptPalette = (meta: Readonly<Record<string, unknown>>) =>
  typeof meta.answer === "function" && typeof meta.placeholder === "string";

/** The palette's available modes, and the gates it renders while `open` (none are offered without). */
export function usePaletteModes(open: boolean) {
  return useContributedModes<PaletteModeSpec>(SlotId.paletteMode, acceptPalette, open);
}

export const isPaletteText = (answer: PaletteAnswer | null | undefined): answer is PaletteText =>
  Boolean(answer && typeof (answer as PaletteText).text === "string");

/**
 * ONE query per (mode, query). The key starts with the owner's name, so withdrawing the plugin
 * drops its answers (the loader removes a plugin's own keys) and a re-registration — a new
 * generation — reads afresh. Unused answers abort: the signal reaches `answer`.
 */
export function paletteAnswerQuery(mode: PaletteMode | null, query: string, onText: (text: string) => void) {
  const q = query.trim();
  const key = [mode?.plugin ?? "", "palette-mode", mode?.generation ?? 0, mode?.id ?? "", q] as const;
  return queryOptions({
    queryKey: key,
    queryFn: ({ signal }) => {
      if (!mode) throw new Error("This palette mode is unavailable");
      return mode.answer(q, { signal, onText });
    },
    enabled: mode !== null && q !== "",
    // While the next answer loads, the previous one stays — but only the SAME mode's: one palette
    // serves every mode, and another mode's rows must never stand in for this one's.
    placeholderData: (previous, previousQuery) =>
      previousQuery && [0, 2, 3].every((i) => previousQuery.queryKey[i] === key[i]) ? previous : undefined,
    retry: false,
  });
}

/** The active mode's answer to `query`: the settled answer, the streamed text so far, and whether
 *  one is on its way. */
export function usePaletteAnswer(mode: PaletteMode | null, query: string) {
  const q = query.trim();
  const identity = mode ? JSON.stringify([mode.plugin, mode.generation, mode.id, q]) : "";
  const [streamed, setStreamed] = useState<{ identity: string; text: string } | null>(null);
  const result = useQuery(paletteAnswerQuery(mode, q, (text) => setStreamed({ identity, text })));
  const answer = mode && q !== "" ? (result.data ?? null) : null;
  const text = isPaletteText(answer) ? answer.text : streamed?.identity === identity ? streamed.text : null;
  return { answer, text, fetching: result.isFetching, error: result.isError ? result.error : null };
}
