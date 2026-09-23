import { ApiError, errorMessage } from "./api";
import { fieldInScope } from "./field-scope";
import { FieldType, type FieldDef, type FieldTypeValue } from "./types";

/**
 * SLQ (Radd Query language) — client-side mirror of spec 10's FROZEN grammar.
 * The frontend never parses SLQ; this module only feeds the syntax cheat sheet
 * and renders the backend's positioned 422 parse errors. Keep in sync with
 * `docs/specs/10-slq-views2.md` (`server/src/radd/modules/items/slq/`).
 */

export interface SlqFieldHelp {
  /** Field name as typed in a query (case-sensitive). */
  field: string;
  /** Accepted values, human form. */
  values: string;
  example: string;
}

/** Builtin queryable fields (spec 10) — custom fields are appended live from the registry. */
export const SLQ_BUILTIN_FIELDS: readonly SlqFieldHelp[] = [
  { field: "project", values: "project key", example: "project = TD" },
  { field: "state", values: "state name", example: "state != Done" },
  { field: "category", values: "state category", example: "category IN (todo, in_progress)" },
  { field: "kind", values: "epic | issue | subtask", example: "kind = epic" },
  { field: "priority", values: "low | normal | high | blocker", example: "priority IN (high, blocker)" },
  { field: "assignee", values: "email | me | none", example: "assignee = me" },
  { field: "reporter", values: "email | me | none", example: "reporter = me" },
  { field: "team", values: "team name | none", example: 'team = "FX"' },
  { field: "cycle.status", values: "active | upcoming | draft | completed", example: "cycle.status = completed" },
  { field: "cycle", values: "cycle name | none", example: 'cycle = "PIPE - 115"' },
  {
    field: "past_cycle",
    values: "cycle name | none (cycles the issue LEFT — carryovers)",
    example: "past_cycle IS NOT EMPTY",
  },
  { field: "label", values: "label name (= has, != lacks, IN = has any)", example: "label IN (urgent, blocked)" },
  { field: "title", values: "text (~ = contains, case-insensitive)", example: 'title ~ "render farm"' },
  { field: "key", values: "issue key", example: "key = TD-12" },
  { field: "parent", values: "parent key | none", example: "parent = TD-3" },
  { field: "epic", values: "epic key | none — an epic counts as its own (also epic.state/category/assignee/priority + the parent.* twins)", example: 'epic.state = "In Progress"' },
  { field: "number", values: "issue number", example: "number > 100" },
  { field: "created", values: "YYYY-MM-DD | today±Nd/Nw", example: "created >= today-2w" },
  { field: "updated", values: "YYYY-MM-DD | today±Nd/Nw", example: "updated < 2026-07-01" },
  { field: "target", values: "YYYY-MM-DD | today±Nd/Nw", example: "target <= today+3d" },
  { field: "flagged", values: "true | false", example: "flagged = true" },
  { field: "starred", values: "true | false (your personal stars)", example: "starred = true" },
];

export interface SlqOperatorHelp {
  op: string;
  meaning: string;
}

export const SLQ_OPERATORS: readonly SlqOperatorHelp[] = [
  { op: "=  !=", meaning: "equals / not equals" },
  { op: "~", meaning: "contains, case-insensitive (title & text fields)" },
  { op: ">  <  >=  <=", meaning: "compare numbers and YYYY-MM-DD dates" },
  { op: "IN (a, b)  /  NOT IN (…)", meaning: "any of / none of the listed values" },
  { op: "IS EMPTY  /  IS NOT EMPTY", meaning: "value unset / set" },
  { op: "AND  OR  NOT  ( )", meaning: "combine conditions — AND binds tighter than OR" },
  { op: "ORDER BY field [ASC|DESC], …", meaning: "sort the results (default: created DESC); state sorts in workflow order, category in tier order" },
];

/** Value forms accepted on the right-hand side (spec 10). */
export const SLQ_VALUE_NOTES: readonly string[] = [
  "Bare words need no quotes; use 'single' or \"double\" quotes for spaces.",
  "Keywords are case-insensitive; field names are case-sensitive.",
  "me = the current user (assignee); none = unset relation (≡ IS EMPTY).",
  "!= and NOT IN on a relation (assignee, team, cycle, epic.…, parent.…) also match issues that have none — = and != always split the set.",
];

export const SLQ_EXAMPLES: readonly string[] = [
  "state != Done AND priority IN (high, blocker)",
  "assignee = me AND category = in_progress",
  '(team = "FX" OR team = "Comp") AND label = urgent',
  "assignee IS EMPTY ORDER BY created ASC",
  "updated >= 2026-01-01 ORDER BY priority DESC, updated DESC",
  "category != done ORDER BY state, updated DESC",
];

/** Operator hint for a registry custom field, by its type (spec 10 table). */
export function cfOpsHint(type: FieldTypeValue): string {
  switch (type) {
    case FieldType.select:
    case FieldType.text:
      return "=  !=  ~  IN";
    case FieldType.multi_select:
      return "= (contains)  IN";
    case FieldType.number:
    case FieldType.duration:
    case FieldType.date:
      return "=  !=  >  <  >=  <=";
    case FieldType.boolean:
      return "= true | false";
    default:
      return "=  !=";
  }
}

/** Custom fields queryable in a view's scope (all types — every key is a field). */
export function cheatSheetFields(fields: FieldDef[], projectId: string | null): FieldDef[] {
  return fields.filter((field) => fieldInScope(field, projectId));
}

// ---------------------------------------------------------------------------
// Positioned parse errors (422 {detail, position})
// ---------------------------------------------------------------------------

export interface SlqError {
  message: string;
  /** Character offset into the query, or null when the backend gave none. */
  position: number | null;
}

/** Extract a spec-10 SLQ parse error from a thrown value; null for anything else. */
export function slqErrorOf(error: unknown): SlqError | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const { detail } = error;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const payload = detail as { detail?: unknown; position?: unknown };
    if (typeof payload.detail === "string") {
      return {
        message: payload.detail,
        position: typeof payload.position === "number" ? payload.position : null,
      };
    }
  }
  return { message: errorMessage(error), position: null };
}

export interface SlqErrorContext {
  /** The query line containing the offending offset. */
  line: string;
  /** Same-length whitespace run ending in `^` under the offending column. */
  caret: string;
}

/**
 * Resolve a character offset to its line + a caret marker, for rendering the
 * "offending spot" under the editor. Clamps out-of-range offsets.
 */
export function slqErrorContext(query: string, position: number): SlqErrorContext {
  const offset = Math.max(0, Math.min(position, query.length));
  const before = query.slice(0, offset);
  const lineStart = before.lastIndexOf("\n") + 1;
  const lineEnd = query.indexOf("\n", offset);
  const line = query.slice(lineStart, lineEnd === -1 ? query.length : lineEnd);
  const column = offset - lineStart;
  return { line, caret: `${" ".repeat(column)}^` };
}

const ORDER_BY_RE = /\border\s+by\b/i;

/**
 * AND active quick-filter conditions into a view's SLQ, keeping any ORDER BY at
 * the tail (the grammar only allows it there). Every part is parenthesized so
 * OR precedence inside the base query or a filter can't leak. Filters are
 * conditions-only (enforced server-side on save).
 */
export function combineQueryWithFilters(query: string, filters: string[]): string {
  if (filters.length === 0) return query;
  const match = ORDER_BY_RE.exec(query);
  const base = (match ? query.slice(0, match.index) : query).trim();
  const orderTail = match ? " " + query.slice(match.index).trim() : "";
  const parts = [...(base ? [base] : []), ...filters].map((part) => `(${part})`);
  return parts.join(" AND ") + orderTail;
}

/** Split an SLQ into its condition part and its `ORDER BY …` tail. */
export function splitQueryOrder(query: string): { where: string; order: string } {
  const match = ORDER_BY_RE.exec(query);
  if (!match) return { where: query.trim(), order: "" };
  return {
    where: query.slice(0, match.index).trim(),
    order: query.slice(match.index).trim(),
  };
}

/**
 * Compose the COMMITTED ad-hoc bar query INTO a view's effective query
 * (pagination wave): conditions AND in like a quick filter, and
 * the bar's ORDER BY (when present) REPLACES the view's. This is what makes
 * `ORDER BY updated DESC` in the bar actually re-sort the view — the old
 * intersect-with-one-page semantics read as "4 cards out of 1800 loaded"
 * on a big instance.
 */
export function composeQueryWithBar(viewQuery: string, barQuery: string): string {
  const bar = splitQueryOrder(barQuery);
  const base = splitQueryOrder(viewQuery);
  const where = [base.where, bar.where]
    .filter(Boolean)
    .map((part) => `(${part})`)
    .join(" AND ");
  const order = bar.order || base.order;
  return [where, order].filter(Boolean).join(" ");
}
