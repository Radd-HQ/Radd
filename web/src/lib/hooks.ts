import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  RoutePath,
  SLQ_PROBE_DEBOUNCE_MS,
  SLQ_SUGGEST_DEBOUNCE_MS,
} from "./constants";
import {
  allowedTransitionsQuery,
  authStateQuery,
  fieldWritabilityQuery,
  instanceConfigQuery,
  itemByKeyQuery,
  projectsQuery,
  resolvedSettingQuery,
  slqValidateQuery,
} from "./queries";
import { DEFAULT_DURATION_CONFIG, type DurationConfig } from "./duration";
import { AuthStatus, type AuthState } from "./auth";
import { slqErrorOf, type SlqError } from "./slq";
import {
  fetchSlqSuggest,
  suggestContextLabel,
  type SlqSuggestion,
} from "./slq-suggest";
import {
  InstanceRole,
  Permission,
  SettingKey,
  type Item,
  type Me,
  type PageSpace,
  type PermissionValue,
  type Project,
} from "./types";

/** Auth state from the boot query; the app-layout gate guarantees it resolved. */
export function useAuthState(): AuthState | undefined {
  const { data } = useQuery(authStateQuery);
  return data;
}

/** The signed-in user, or null in anonymous dev mode / while loading. */
export function useCurrentUser(): Me | null {
  const authState = useAuthState();
  return authState?.status === AuthStatus.authenticated ? authState.user : null;
}

/**
 * Issue side panel (spec 25): the `?peek=<itemKey>` search param opens the
 * detail drawer over the CURRENT view. Because it's just a search param on the
 * current route, the browser Back button closes the panel (returning you to the
 * view) and the URL is shareable. `expand` swaps to the full `/issues/$key` page.
 */
export function usePeek() {
  const navigate = useNavigate();
  const peekKey = useRouterState({
    select: (state) => (state.location.search as { peek?: string }).peek,
  });
  return {
    peekKey,
    // `to: "."` = the current route (preserves path params); only the search
    // changes, so the panel overlays the current view. (Omitting `to` targets
    // the root route, which would navigate away.)
    open: (itemKey: string) =>
      void navigate({ to: ".", search: (prev) => ({ ...prev, peek: itemKey }) }),
    close: () => void navigate({ to: ".", search: (prev) => ({ ...prev, peek: undefined }) }),
    // Replace the transient panel history entry so Back from the full page
    // returns to the clean view rather than reopening the panel.
    expand: (itemKey: string) =>
      void navigate({ to: RoutePath.issue, params: { itemKey }, replace: true }),
  };
}

/**
 * True inside the peek panel's subtree (IssuePanel provides it). The full
 * issue page and the peek share ItemDetailBody, so components that must
 * behave differently per surface — e.g. issue-reference cards, which can't
 * open a second peek from inside the first — ask this instead of a prop
 * threaded through every layer.
 */
export const PeekSurfaceContext = createContext(false);

/**
 * Click behavior for issue REFERENCE cards (similar issues, deflection):
 * a plain click opens the peek panel over whatever the user is doing, so the
 * half-typed form or the issue being read survives the detour. From INSIDE
 * the peek — where a second panel can't stack — it promotes the peeked issue
 * to the full page and peeks the clicked one in a single navigation, so the
 * reading thread is never lost. Rows keep their real /issues/$key href:
 * modified clicks (cmd/ctrl/shift/alt, middle-click) return false untouched
 * so the browser's new-tab behavior still works.
 *
 * Returns whether it consumed the click — callers with extra UI to tear down
 * (a popover hosting the list) close it only on true.
 */
export function useOpenIssueRef() {
  const navigate = useNavigate();
  const inPeek = useContext(PeekSurfaceContext);
  const { peekKey, open, expand } = usePeek();
  return (itemKey: string, event?: ReactMouseEvent): boolean => {
    if (
      event &&
      (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
    ) {
      return false;
    }
    event?.preventDefault();
    if (inPeek && peekKey) {
      if (itemKey === peekKey) {
        expand(itemKey);
      } else {
        void navigate({
          to: RoutePath.issue,
          params: { itemKey: peekKey },
          search: { peek: itemKey },
        });
      }
    } else {
      open(itemKey);
    }
    return true;
  };
}

/**
 * Effective-permission checks for the current user (spec 09):
 * - `global(p)` — the caller's GLOBAL permission union off `/auth/me`
 *   (spec 86 stage 3: the flat top-level `permissions` array). Instance
 *   admins pass everything.
 * - `project(project, p)` — from `ProjectRead.permissions`, the backend's
 *   per-project union for the CURRENT user.
 * Anonymous dev mode (auth backend absent, API open) allows everything so
 * dev stays usable. The api client's global 403 toast is the backstop.
 */
export interface PermissionChecks {
  global: (permission: PermissionValue) => boolean;
  project: (
    project: Pick<Project, "permissions"> | null | undefined,
    permission: PermissionValue,
  ) => boolean;
  /**
   * The caller holds `permission` on AT LEAST ONE project they can see — the
   * client mirror of `authz.require_anywhere` (RADD-788).
   *
   * Use it for surfaces that span projects, where there is no single project to
   * resolve against: an all-projects view, the New-view affordance for the
   * all-projects scope. `global` is the wrong question there and looked like the
   * right one — a grant on this instance is normally SCOPED to a project, which
   * contributes nothing to the global union, so every such gate was false for
   * ordinary members the moment the Baseline role was emptied.
   *
   * The server still enforces per row; this only decides whether the affordance
   * is offered at all.
   */
  anyProject: (permission: PermissionValue) => boolean;
  /**
   * The caller holds `permission` IN THIS SPACE (RADD-814): the space leg of
   * the scope ladder, resolved from the per-space union `GET /page-spaces`
   * carries — the RADD-810 class was space-scoped atoms asked as global
   * questions because no space-shaped question existed to ask.
   */
  space: (
    space: Pick<PageSpace, "permissions"> | null | undefined,
    permission: PermissionValue,
  ) => boolean;
}

export function usePermissions(): PermissionChecks {
  const authState = useAuthState();
  // Already fetched app-wide (the sidebar renders the project tree), so this is
  // a cache read rather than a request. `permissions` on each row is the
  // backend's per-project union for the current user.
  const { data: projects } = useQuery(projectsQuery());

  return useMemo(() => {
    const allowAll =
      authState?.status === AuthStatus.anonymousDev ||
      (authState?.status === AuthStatus.authenticated &&
        authState.user.instance_role === InstanceRole.admin);
    // Spec 86 stage 3: the flat top-level `permissions` array IS the global set.
    const globalPermissions = new Set<PermissionValue>(
      authState?.status === AuthStatus.authenticated
        ? authState.user.permissions
        : [],
    );

    return {
      global: (permission) => allowAll || globalPermissions.has(permission),
      project: (project, permission) =>
        allowAll || Boolean(project?.permissions?.includes(permission)),
      anyProject: (permission) =>
        allowAll ||
        globalPermissions.has(permission) ||
        (projects ?? []).some((p) => p.permissions?.includes(permission)),
      space: (space, permission) =>
        allowAll || Boolean(space?.permissions?.includes(permission)),
    };
  }, [authState, projects]);
}

/**
 * The instance's working day/week lengths for client-side duration formatting
 * (spec 67): `timelog_hours_per_day` / `timelog_days_per_week` off the cached
 * `GET /instance` query. Falls back to the server-mirroring 8h/5d defaults
 * only while that query is in flight. Pass the result to `formatDuration`.
 */
export function useDurationConfig(): DurationConfig {
  const { data } = useQuery(instanceConfigQuery);
  return useMemo(
    () =>
      data
        ? { hoursPerDay: data.timelog_hours_per_day, daysPerWeek: data.timelog_days_per_week }
        : DEFAULT_DURATION_CONFIG,
    [data],
  );
}

/**
 * Whether story points are enabled in a scope (spec 70): the cascade-RESOLVED
 * `estimation_points` value — the project override when `projectId` is given,
 * else the instance default. EVERY points surface gates on this; false while
 * loading, so a project that hasn't opted in never flashes points UI.
 */
export function usePointsEnabled(projectId?: string): boolean {
  const { data } = useQuery(resolvedSettingQuery(SettingKey.estimationPoints, projectId));
  return data?.value === true;
}

/**
 * Allowed workflow transitions for an item's state pickers (spec 61): which
 * target states are reachable from the item's current state, and why not.
 * Shared by the detail rail and the peek panel (both render IssueProperties).
 * While loading — or when enforcement is off — nothing is disabled.
 */
export function useAllowedTransitions(itemId: string | undefined) {
  const query = useQuery({
    ...allowedTransitionsQuery(itemId ?? ""),
    enabled: Boolean(itemId),
  });
  return useMemo(() => {
    const targets = new Map(
      (query.data?.targets ?? []).map((target) => [target.state_id, target] as const),
    );
    return {
      /** Unknown state ids (still loading) stay enabled — the server re-checks. */
      isAllowed: (stateId: string) => targets.get(stateId)?.allowed ?? true,
      failuresFor: (stateId: string) => targets.get(stateId)?.failures ?? [],
    };
  }, [query.data]);
}

export interface ItemWritability {
  /** `item.update` on the project — the coarse gate for title/description/flag and every field. */
  canEdit: boolean;
  /** Whether a builtin field NAME (e.g. "priority", "assignee") or custom field KEY may be written:
   *  item.update AND not restricted by a field grant. Use on EDIT surfaces. */
  fieldWritable: (nameOrKey: string) => boolean;
  /** Whether a field is restricted by a GRANT alone (independent of item.update). Use on the CREATE
   *  surface, where item.create already gates the whole form. */
  restricted: (nameOrKey: string) => boolean;
  /** The reason a locked control shows (empty when writable) — for a `title` tooltip / inline note. */
  reasonFor: (nameOrKey: string) => string;
}

/**
 * Per-item edit writability (spec 92 access resolution): the coarse `item.update` gate plus the
 * per-field grant restrictions resolved server-side (`GET /fields/writable`). Every editable field
 * surface consults this to DISABLE controls the user can't write — dimmed, with a reason — instead
 * of letting the edit fail on save. Item-independent per project, so it's cached.
 */
export function useItemWritability(
  project: Pick<Project, "id" | "permissions"> | null | undefined,
): ItemWritability {
  const perms = usePermissions();
  const { data } = useQuery(fieldWritabilityQuery(project?.id));
  const canEdit = project ? perms.project(project, Permission.itemUpdate) : false;
  const readonly = useMemo(() => new Set(data?.readonly_fields ?? []), [data]);
  return useMemo(
    () => ({
      canEdit,
      fieldWritable: (name: string) => canEdit && !readonly.has(name),
      restricted: (name: string) => readonly.has(name),
      reasonFor: (name: string) =>
        readonly.has(name)
          ? "This field is restricted — you don't have permission to edit it."
          : !canEdit
            ? "You don't have permission to edit this issue."
            : "",
    }),
    [canEdit, readonly],
  );
}

/**
 * Global single-key shortcut (e.g. `c` = new item on the board). Ignores
 * chords with modifiers and keystrokes aimed at editable controls or dialogs.
 */
export function useKeyboardShortcut(key: string, onTrigger: () => void) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== key || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) {
        return;
      }
      event.preventDefault();
      onTrigger();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [key, onTrigger]);
}

/** `value`, trailing-debounced. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/** Live SLQ probe outcome (specs 11/55) — drives the editor's validation line. */
export const SlqProbeStatus = {
  /** Query empty — nothing to validate; an empty query matches everything. */
  idle: "idle",
  /** Typing not yet settled, or a request is in flight. */
  checking: "checking",
  /** Draft compiles but hasn't been run — Enter executes (page bars only). */
  ready: "ready",
  /** Valid. `count` present when a surface ran the query; absent = validate-only. */
  valid: "valid",
  /** Backend 422 parse error — `error` carries {message, position}. */
  invalid: "invalid",
  /** Non-parse failure (network, 5xx…) — `failure` is the message. */
  failed: "failed",
} as const;
export type SlqProbeStatusValue = (typeof SlqProbeStatus)[keyof typeof SlqProbeStatus];

export interface SlqProbe {
  status: SlqProbeStatusValue;
  /** The debounced query text the current status corresponds to. */
  query: string;
  error: SlqError | null;
  failure: string | null;
  /** Result numbers — only on surfaces that actually ran the query. */
  count?: number;
  atCap?: boolean;
}

/**
 * Debounced live validation for an SLQ draft (spec 55): parse + compile via
 * `GET /items/slq/validate` — the server NEVER executes the query, so this is
 * safe on every settled keystroke at any project size. Execution (and match
 * counts) happen only when a surface commits the query (`useSlqPageFilter`) or
 * fetches its saved result. Empty drafts skip the request entirely.
 */
export function useSlqValidation(
  projectId: string | null,
  draft: string,
  dialect?: string,
): SlqProbe {
  const debounced = useDebounced(draft, SLQ_PROBE_DEBOUNCE_MS);
  const trimmed = debounced.trim();
  const probe = useQuery({
    ...slqValidateQuery(projectId, trimmed, dialect),
    enabled: trimmed !== "",
  });

  const slqError = probe.isError ? slqErrorOf(probe.error) : null;
  const status: SlqProbeStatusValue =
    trimmed === ""
      ? SlqProbeStatus.idle
      : draft.trim() !== trimmed || probe.isPending || probe.isFetching
        ? SlqProbeStatus.checking
        : probe.isError
          ? slqError
            ? SlqProbeStatus.invalid
            : SlqProbeStatus.failed
          : SlqProbeStatus.valid;

  return {
    status,
    query: trimmed,
    error: slqError,
    failure:
      probe.isError && !slqError && probe.error instanceof Error ? probe.error.message : null,
  };
}

export interface ProjectByKey {
  /** undefined while loading, null when no project matches the key. */
  project: Project | null | undefined;
}

/** Resolve a route's $projectKey against the readable project list. */
export function useProjectByKey(projectKey: string): ProjectByKey {
  const { data: projects } = useQuery(projectsQuery());
  if (projects === undefined) return { project: undefined };
  return { project: projects.find((p) => p.key === projectKey) ?? null };
}

export interface ItemByKey {
  /**
   * The item's project, resolved from its `project_id` against the readable
   * project list. undefined while loading, null when the item/project is absent.
   */
  project: Project | null | undefined;
  /** The resolved item; undefined while loading, null when the key 404s. */
  item: Item | null | undefined;
  isPending: boolean;
  /** True when the by-key lookup failed (unknown key ⇒ 404). */
  isError: boolean;
}

/**
 * Resolve a canonical issue key (`TD-25`) to its item via the server's by-key
 * resolver (spec 21) — no client-side number→id list scan. The item carries
 * `project_id`; we resolve its project (the scope the detail editor needs for
 * states/fields/teams) from the cached project list.
 */
export function useItemByKey(itemKey: string): ItemByKey {
  const itemByKey = useQuery({ ...itemByKeyQuery(itemKey), enabled: itemKey !== "" });
  const item = itemByKey.data;
  const { data: projects } = useQuery(projectsQuery());

  const project =
    item === undefined || projects === undefined
      ? undefined
      : projects.find((p) => p.id === item.project_id) ?? null;

  return {
    project,
    item: itemByKey.isError ? null : item,
    isPending: itemByKey.isPending,
    isError: itemByKey.isError,
  };
}

/**
 * Server-driven SLQ autocomplete controller (spec 13). Owns the debounced,
 * stale-dropping suggest fetch and the dropdown's open/active state; the editor
 * component reads the caret and applies the chosen `insert`. `scope` carries
 * an optional project_id; `null` disables autocomplete entirely.
 */
export interface SlqAutocomplete {
  open: boolean;
  suggestions: SlqSuggestion[];
  contextLabel: string | null;
  replaceFrom: number;
  activeIndex: number;
  setActiveIndex: (index: number) => void;
  /** Fetch suggestions for the caret; `immediate` skips the debounce (Ctrl+Space). */
  request: (query: string, cursor: number, immediate?: boolean) => void;
  /** Move the highlight over insertable rows only (hints are skipped), wrapping. */
  moveActive: (delta: number) => void;
  /** The highlighted row if it's insertable, else null. */
  activeSuggestion: () => SlqSuggestion | null;
  close: () => void;
}

const firstSelectable = (rows: SlqSuggestion[]): number => {
  const index = rows.findIndex((row) => row.insert !== "");
  return index === -1 ? 0 : index;
};

export function useSlqAutocomplete(
  scope: Record<string, string> | null,
  dialect?: string,
): SlqAutocomplete {
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<SlqSuggestion[]>([]);
  const [contextLabel, setContextLabel] = useState<string | null>(null);
  const [replaceFrom, setReplaceFrom] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const seqRef = useRef(0);
  const timerRef = useRef<number | undefined>(undefined);
  // Keep the latest scope in a ref so `request` stays a stable callback.
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  const close = useCallback(() => {
    seqRef.current += 1; // drop any in-flight response
    window.clearTimeout(timerRef.current);
    setOpen(false);
    setSuggestions([]);
  }, []);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const run = useCallback(async (query: string, cursor: number) => {
    const activeScope = scopeRef.current;
    if (activeScope === null) return;
    const seq = (seqRef.current += 1);
    const response = await fetchSlqSuggest(activeScope, query, cursor, dialect);
    if (seq !== seqRef.current) return; // a newer request superseded this one
    if (!response || response.suggestions.length === 0) {
      setOpen(false);
      setSuggestions([]);
      return;
    }
    setSuggestions(response.suggestions);
    setContextLabel(suggestContextLabel(response));
    setReplaceFrom(response.replace_from);
    setActiveIndex(firstSelectable(response.suggestions));
    setOpen(true);
  }, []);

  const request = useCallback(
    (query: string, cursor: number, immediate = false) => {
      window.clearTimeout(timerRef.current);
      if (scopeRef.current === null) return;
      if (immediate) {
        void run(query, cursor);
        return;
      }
      timerRef.current = window.setTimeout(() => void run(query, cursor), SLQ_SUGGEST_DEBOUNCE_MS);
    },
    [run],
  );

  const moveActive = useCallback(
    (delta: number) => {
      setActiveIndex((current) => {
        if (suggestions.length === 0) return current;
        let index = current;
        for (let step = 0; step < suggestions.length; step += 1) {
          index = (index + delta + suggestions.length) % suggestions.length;
          if (suggestions[index].insert !== "") return index;
        }
        return current;
      });
    },
    [suggestions],
  );

  const activeSuggestion = useCallback(() => {
    const row = suggestions[activeIndex];
    return row && row.insert !== "" ? row : null;
  }, [suggestions, activeIndex]);

  return {
    open: open && suggestions.length > 0,
    suggestions,
    contextLabel,
    replaceFrom,
    activeIndex,
    setActiveIndex,
    request,
    moveActive,
    activeSuggestion,
    close,
  };
}
