import { api } from "./api";
import { On401, ApiPath } from "./constants";

/** One row in the autocomplete dropdown (mirrors the backend Suggestion). */
export interface SlqSuggestion {
  value: string;
  /** Spliced verbatim over [replace_from, cursor); "" = non-insertable hint. */
  insert: string;
  label: string;
  detail: string;
}

export type SlqSuggestContext = "field" | "operator" | "value" | "keyword";

export interface SlqSuggestResponse {
  context: SlqSuggestContext;
  replace_from: number;
  field: string | null;
  suggestions: SlqSuggestion[];
}

/** Where a dialect's SLQ endpoints live. Items is the default; the timesheet
 *  passes the worklog dialect (spec 98), which serves the same contract. */
export const SlqDialect = {
  items: ApiPath.items,
  worklogs: ApiPath.timesheet,
} as const;

/**
 * Ask the server what the cursor position wants (spec 12). Best-effort:
 * autocomplete must never break typing, so any failure resolves to null and
 * the caller just shows no dropdown. `scope` carries an optional project_id.
 */
export async function fetchSlqSuggest(
  scope: Record<string, string>,
  query: string,
  cursor: number,
  dialect: string = SlqDialect.items,
  signal?: AbortSignal,
): Promise<SlqSuggestResponse | null> {
  try {
    return await api.get<SlqSuggestResponse>(`${dialect}/slq/suggest`, {
      signal,
      query: { ...scope, q: query, cursor: String(cursor) },
      on401: On401.throw,
    });
  } catch {
    return null;
  }
}

/** A header label for the dropdown ("fields", "operators", "values for state"). */
export function suggestContextLabel(response: SlqSuggestResponse): string {
  switch (response.context) {
    case "field":
      return "fields";
    case "operator":
      return "operators";
    case "keyword":
      return "keywords";
    case "value":
      return response.field ? `values for ${response.field}` : "values";
  }
}

/**
 * Splice an accepted suggestion's `insert` over [replaceFrom, cursor) and land
 * the caret one space past it — so re-querying advances to the next context
 * (field → operator → value → keyword) instead of re-reading the token just
 * completed. A space is only added when one isn't already there.
 */
export function applySuggestion(
  value: string,
  replaceFrom: number,
  cursor: number,
  insert: string,
): { value: string; cursor: number } {
  const after = value.slice(cursor);
  const spaced = after.startsWith(" ") ? insert : insert + " ";
  const next = value.slice(0, replaceFrom) + spaced + after;
  return { value: next, cursor: replaceFrom + insert.length + 1 };
}
