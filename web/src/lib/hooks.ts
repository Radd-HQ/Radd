import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  RoutePath,
  SLQ_PROBE_DEBOUNCE_MS,
} from "./constants";
import {
  allowedTransitionsQuery,
  authStateQuery,
  capabilitiesQuery,
  fieldWritabilityQuery,
  instanceConfigQuery,
  itemByKeyQuery,
  pageSpaceSummaryQuery,
  projectSummaryQuery,
  projectByKeyQuery,
  projectByIdQuery,
  resolvedSettingQuery,
  slqValidateQuery,
} from "./queries";
import { DEFAULT_DURATION_CONFIG, type DurationConfig } from "./duration";
import { AuthStatus, type AuthState, currentPath } from "./auth";
import { slqErrorOf, type SlqError } from "./slq";
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

/** Spec 121: a real account is signed in (not the anonymous principal). */
export function useIsAuthenticated(): boolean {
  return useAuthState()?.status === AuthStatus.authenticated;
}

/** Spec 121: the visitor is browsing as the Anyone principal. */
export function useIsAnonymous(): boolean {
  return useAuthState()?.status === AuthStatus.anonymous;
}

/**
 * Spec 121: a visitor who hits something they cannot see is sent to sign in,
 * carrying the page — the issue they cannot read may be one they could read
 * signed in. Pass the page's "not found / refused" condition.
 */
export function useAnonymousBounce(when: boolean): void {
  const anonymous = useIsAnonymous();
  useEffect(() => {
    if (anonymous && when) {
      window.location.assign(`${RoutePath.login}?next=${encodeURIComponent(currentPath())}`);
    }
  }, [anonymous, when]);
}

/** The signed-in user, or null while unauthenticated or loading. */
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
 * The backend remains authoritative; these checks control affordances.
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
   * the scope ladder, resolved from the per-space union the direct space read
   * carries — the RADD-810 class was space-scoped atoms asked as global
   * questions because no space-shaped question existed to ask.
   */
  space: (
    space: Pick<PageSpace, "permissions"> | null | undefined,
    permission: PermissionValue,
  ) => boolean;
  /** Held in AT LEAST ONE readable space — the space mirror of `anyProject`,
   * for surfaces that span spaces (RADD-810: the item↔page link picker). */
  anySpace: (permission: PermissionValue) => boolean;
}

export function usePermissions(): PermissionChecks {
  const authState = useAuthState();
  // A paged directory must not truncate the permission union.
  const { data: projectSummary } = useQuery(projectSummaryQuery());
  const { data: spaceSummary } = useQuery(pageSpaceSummaryQuery());

  return useMemo(() => {
    const allowAll =
      (authState?.status === AuthStatus.authenticated &&
        authState.user.global_role === InstanceRole.admin);
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
        Boolean(projectSummary?.permissions.includes(permission)),
      space: (space, permission) =>
        allowAll || Boolean(space?.permissions?.includes(permission)),
      anySpace: (permission) =>
        allowAll ||
        globalPermissions.has(permission) ||
        Boolean(spaceSummary?.permissions.includes(permission)),
    };
  }, [authState, projectSummary, spaceSummary]);
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
 * Is this plugin currently enabled (RADD-928)?
 *
 * The backing field — `plugins` on the capabilities manifest — has existed
 * since spec 93 and was read by nothing: every optional plugin's host-side UI
 * was hardcoded, so disabling one left its settings tab and its sections in
 * place, pointed at endpoints the loader had just unmounted.
 *
 * Loading answers `false`, deliberately: a surface that flashes in and then
 * vanishes reads as a bug, whereas one that appears a beat late reads as
 * loading. Anything gated on this must therefore be additive — never the
 * disabled half of a switch.
 */
export function usePluginEnabled(name: string): boolean {
  const { data } = useQuery(capabilitiesQuery);
  return (data?.plugins ?? []).includes(name);
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

interface ItemWritability {
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
  /** RADD-842: the row itself, when the surface has one. Relations make
   * writability per-ROW (`item.update@own`), and the server's per-item
   * verdict OVERRIDES the project-level answer — a false here means this
   * specific issue is not theirs to edit. Absent capabilities fall back. */
  item?: Pick<Item, "capabilities"> | null,
): ItemWritability {
  const perms = usePermissions();
  const { data } = useQuery(fieldWritabilityQuery(project?.id));
  const projectLevel = project ? perms.project(project, Permission.itemUpdate) : false;
  const verdict = item?.capabilities?.can_update;
  const canEdit = verdict !== undefined && verdict !== null ? verdict : projectLevel;
  const rowDenied = projectLevel && canEdit === false;
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
            ? rowDenied
              ? "Your edit access is limited to your own or your team's issues — this isn't one."
              : "You don't have permission to edit this issue."
            : "",
    }),
    [canEdit, rowDenied, readonly],
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
type SlqProbeStatusValue = (typeof SlqProbeStatus)[keyof typeof SlqProbeStatus];

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

interface ProjectByKey {
  /** undefined while loading, null when no project matches the key. */
  project: Project | null | undefined;
}

/** Direct resolution remains available beyond the current directory page. */
export function useProjectByKey(projectKey: string): ProjectByKey {
  const query = useQuery(projectByKeyQuery(projectKey));
  return { project: query.isError ? null : query.data };
}

interface ItemByKey {
  /**
   * The item's project, resolved from its `project_id` through its direct
   * readable-project endpoint. undefined while loading, null when the item/project is absent.
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
 * states/fields/teams) through a direct project lookup.
 */
export function useItemByKey(itemKey: string): ItemByKey {
  const itemByKey = useQuery({ ...itemByKeyQuery(itemKey), enabled: itemKey !== "" });
  const item = itemByKey.data;
  const projectQuery = useQuery(projectByIdQuery(item?.project_id ?? ""));
  const project = projectQuery.isError ? null : projectQuery.data;

  return {
    project,
    item: itemByKey.isError ? null : item,
    isPending: itemByKey.isPending || (Boolean(item) && projectQuery.isPending),
    isError: itemByKey.isError || projectQuery.isError,
  };
}

export { useSlqAutocomplete } from "./useSlqAutocomplete";
