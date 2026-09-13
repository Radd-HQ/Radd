/** UI behavior constants: poll/debounce timings, realtime socket, validation patterns, hotkeys, page caps. */

import { API_BASE } from "./api";

/** Fallback poll for the unread badge — realtime (spec 27) is the primary signal. */
export const NOTIFICATIONS_POLL_MS = 30_000;

/** Debounce for command-palette search-as-you-type (spec 28). */
export const SEARCH_DEBOUNCE_MS = 150;
/** Result cap requested by the palette's issue section. */
export const PALETTE_SEARCH_LIMIT = 8;
/**
 * Parent-picker typeahead (spec 80): link-search's server cap. Candidates are
 * server-wide and kind-filtered client-side, so ask for the full page.
 */
export const PARENT_SEARCH_LIMIT = 25;
/** KB deflection (spec 66): debounce + minimum title length before querying. */
export const DEFLECT_DEBOUNCE_MS = 400;
export const DEFLECT_MIN_QUERY_CHARS = 3;
/** Similar-issues on the form pages (spec 106): each probe embeds the draft
 * server-side, so it settles noticeably later than the FTS deflection. */
export const FORM_SIMILAR_DEBOUNCE_MS = 800;

/** Realtime WebSocket (spec 27). */
export const REALTIME_WS_PATH = `${API_BASE}/ws`;
/** Burst coalescing: entity signals collect for a beat, then flush as one invalidation. */
export const REALTIME_COALESCE_MS = 200;
export const REALTIME_RECONNECT_BASE_MS = 1_000;
export const REALTIME_RECONNECT_MAX_MS = 30_000;

/**
 * Literal a clearing automation action (set_assignee/team/cycle/release) sends
 * to unset the field — mirror of the backend `CLEAR_VALUE`.
 */
export const AUTOMATION_CLEAR_VALUE = "none";

/**
 * GET /items caps `limit` at 200 (default 50). The prototype board/list fetch
 * one page at the cap; beyond that pagination is a known gap (modules.md).
 */
export const ITEMS_PAGE_LIMIT = 200;
/** RADD-1154: a phone shows one card per screen, so a 200-item page reads as
 *  "everything" and the pager sits 200 cards away — page smaller there. */
export const ITEMS_PAGE_LIMIT_PHONE = 50;

/** Client-side mirror of the ProjectCreate.key pattern in the API schema. */
export const PROJECT_KEY_PATTERN = /^[A-Za-z][A-Za-z0-9]{0,9}$/;
export const PROJECT_KEY_HINT = "1–10 letters/digits, starts with a letter";

/** Client-side mirror of the FieldDefinitionCreate.key pattern in the API schema. */
export const FIELD_KEY_PATTERN = /^[a-z][a-z0-9_]{0,49}$/;
export const FIELD_KEY_HINT = "snake_case, starts with a letter (create-only — keys are permanent)";

/** Client-side mirror of the RoleCreate.key pattern in the API schema. */
export const ROLE_KEY_PATTERN = /^[a-z0-9][a-z0-9-]{0,99}$/;
export const ROLE_KEY_HINT = "lowercase slug (letters, digits, dashes)";

/** Board keyboard shortcut: opens the New-item modal (spec 04 Phase 3). */
export const NEW_ITEM_HOTKEY = "c";

/** Debounce for live SLQ validation probes while typing (spec 11). */
export const SLQ_PROBE_DEBOUNCE_MS = 400;
/** Autocomplete reacts faster than validation (spec 13) — it's a keystroke aid. */
export const SLQ_SUGGEST_DEBOUNCE_MS = 150;

/** Poll cadence for an in-flight storage move job (spec 102). */
export const MOVE_JOB_POLL_MS = 2_000;

/** Peek drawer width: default + drag clamps (resizable, persisted globally —
 *  it is one drawer, not a per-view surface). WIDE by default: at 672px the
 *  item body stacked its fields rail ABOVE the description (below its @3xl
 *  container split), burying the content the peek exists to show. 1100px
 *  keeps description + rail side by side; `max-w-full` still caps it on
 *  small windows. */
export const PEEK_DEFAULT_WIDTH = 1100;
export const PEEK_MIN_WIDTH = 380;
export const PEEK_MAX_WIDTH = 1400;
