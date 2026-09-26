import { useMemo } from "react";
import type { PluginContribution } from "./plugin";
import { SlotId } from "./slots";
import { modeContribution, useContributedModes, type ContributedMode, type ModeSpec } from "./contributed-modes";

/**
 * Query-bar INPUT MODES (RADD-1400). The query bar is an SLQ editor; an input mode is another way
 * to fill it — free text in, an SLQ query and an explanation out. The bar applies the query in its
 * SLQ editor, so every run is visible SLQ, and shows the explanation under the bar until the
 * query is edited. There is deliberately no auto-detection: a mistyped query must fail loudly as
 * SLQ, never silently become a mode's input.
 *
 * The bar owns the policy: with any mode available it shows an SLQ | mode toggle, mod+I cycles
 * through them, and an EMPTY bar opens on the first available mode (a query carried in the URL
 * opens SLQ, so the applied query stays visible). With none available the bar is plain SLQ with
 * no toggle.
 */

/** The SLQ dialects a bar can query (spec 98): the dialect is rooted at the entity it returns. */
export const QueryDialect = {
  /** Issues — every view, report and dashboard. */
  items: "items",
  /** Worklogs — the timesheet; issue fields ride `issue.`. */
  worklog: "worklog",
} as const;
export type QueryDialectValue = (typeof QueryDialect)[keyof typeof QueryDialect];

/** A mode's answer: the SLQ to apply, and a sentence saying what it means. */
export interface QueryDraft {
  query: string;
  explanation: string;
}

export interface QueryInputModeSpec extends ModeSpec {
  /** The input's placeholder while the mode is on; `hint` is its tooltip. */
  placeholder: string;
  /** The input's accessible name (default: the placeholder). */
  ariaLabel?: string;
  /** Said under the bar while a draft is on its way (default "Working…"). */
  busyLabel?: string;
  /** The dialects it can write (default: every dialect). */
  dialects?: readonly QueryDialectValue[];
  /**
   * Turn `text` into SLQ in `dialect`. The bar aborts `signal` when it goes away or the plugin is
   * withdrawn, and drops a draft that arrives after either. Reject with a presentable error: its
   * message is shown under the bar.
   */
  toQuery: (text: string, context: { dialect: QueryDialectValue; signal: AbortSignal }) => Promise<QueryDraft>;
}

export type QueryInputMode = ContributedMode<QueryInputModeSpec>;

/** The contribution row for `definePlugin({ contributions: [queryInputMode({...})] })`. */
export function queryInputMode(spec: QueryInputModeSpec): PluginContribution {
  return modeContribution(SlotId.queryInputMode, spec, `${spec.label} in the query bar`);
}

const acceptQuery = (meta: Readonly<Record<string, unknown>>) =>
  typeof meta.toQuery === "function" && typeof meta.placeholder === "string"
  && (meta.dialects === undefined || (Array.isArray(meta.dialects) && meta.dialects.every((d) => typeof d === "string")));

/** The bar's available modes for `dialect`, and the gates it must render (none are offered without). */
export function useQueryInputModes(dialect: QueryDialectValue) {
  const { modes, gates } = useContributedModes<QueryInputModeSpec>(SlotId.queryInputMode, acceptQuery, true);
  const serving = useMemo(() => modes.filter((mode) => !mode.dialects || mode.dialects.includes(dialect)), [modes, dialect]);
  return { modes: serving, gates };
}
