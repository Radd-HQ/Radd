import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMobileNavigation } from "../components/shell/mobile-navigation";
import {
  RoutePath, SLQ_PROBE_DEBOUNCE_MS, ITEMS_PAGE_LIMIT, ITEMS_PAGE_LIMIT_PHONE, ITEMS_PAGE_SIZES,
  ITEMS_PAGE_SIZE_STORAGE_KEY,
} from "./constants";
import { allowedTransitionsQuery, authStateQuery, fieldWritabilityQuery, effectiveScreenQuery, statesQuery, instanceConfigQuery, itemByKeyQuery, resolvedSettingQuery, slqValidateQuery } from "./queries";
import { DEFAULT_DURATION_CONFIG, type DurationConfig } from "./duration";
import { AuthStatus, type AuthState, currentPath } from "./auth";
import { InstanceRole, Permission, SettingKey, type Item, type Me, type PermissionValue } from "./types";
import { pageSpaceSummaryQuery } from "@radd-plugin-ui/pages/queries";
import type { PageSpace } from "@radd-plugin-ui/pages/types";
import { useDebounced, positionedErrorOf } from "@radd/plugin-sdk";
import { fieldsQuery } from "@radd-plugin-ui/fields/catalog";
import { projectSummaryQuery, projectByKeyQuery, projectByIdQuery } from "@radd-plugin-ui/projects/directory-queries";
import type { PositionedError } from "@radd/plugin-sdk";
import type { Project } from "@radd-plugin-ui/projects/types";

/** Auth state from the boot query; the app-layout gate guarantees it resolved. */
export function useAuthState(): AuthState | undefined {
  const { data } = useQuery(authStateQuery);
  return data;
}

function readStoredPageSize(): number | null {
  try {
    const raw = Number(localStorage.getItem(ITEMS_PAGE_SIZE_STORAGE_KEY));
    return ITEMS_PAGE_SIZES.includes(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** Items per page: a size chosen on the pager (remembered per browser, never part of the shared
 *  view) wins over the phone/desktop default — the shell's own phone breakpoint. */
export function useItemsPageLimit(): [number, (size: number) => void] {
  const { mobile } = useMobileNavigation();
  const [stored, setStored] = useState<number | null>(readStoredPageSize);
  const set = useCallback((size: number) => {
    if (!ITEMS_PAGE_SIZES.includes(size)) return;
    setStored(size);
    try {
      localStorage.setItem(ITEMS_PAGE_SIZE_STORAGE_KEY, String(size));
    } catch {
      // Best-effort persistence — the choice still holds for the session.
    }
  }, []);
  return [stored ?? (mobile ? ITEMS_PAGE_LIMIT_PHONE : ITEMS_PAGE_LIMIT), set];
}

/** Spec 121: a real account is signed in (not the anonymous principal). */
export function useIsAuthenticated(): boolean {
  return useAuthState()?.status === AuthStatus.authenticated;
}

/** Spec 121: the visitor is browsing as the Anyone principal. */
function useIsAnonymous(): boolean {
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

/** `?peek=<itemKey>` opens the issue drawer over the current route: Back closes it, the URL is
 *  shareable, `expand` swaps to the full `/issues/$key` page. */
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
    // `comment` (RADD-1297): open the peek ON one of the issue's comments.
    open: (itemKey: string, comment?: string) =>
      void navigate({ to: ".", search: (prev) => ({ ...prev, peek: itemKey, comment }) }),
    close: () =>
      void navigate({ to: ".", search: (prev) => ({ ...prev, peek: undefined, comment: undefined }) }),
    // Replace the transient panel history entry so Back from the full page
    // returns to the clean view rather than reopening the panel.
    expand: (itemKey: string) =>
      void navigate({ to: RoutePath.issue, params: { itemKey }, replace: true }),
  };
}

/** True inside the peek panel's subtree, so reference cards (which cannot open a second peek)
 *  can behave differently without prop threading. */
export const PeekSurfaceContext = createContext(false);

/** Click handler for issue REFERENCE cards: a plain click opens the peek; from inside the peek it
 *  promotes the peeked issue to the page and peeks the clicked one. Modified/middle clicks return
 *  false untouched so new-tab still works. Returns whether it consumed the click. */
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

/** Effective-permission checks for affordances (the backend stays authoritative). `global` reads
 *  `/auth/me` permissions; `project` reads `ProjectRead.permissions`. Instance admins pass all. */
export interface PermissionChecks {
  global: (permission: PermissionValue) => boolean;
  project: (
    project: Pick<Project, "permissions"> | null | undefined,
    permission: PermissionValue,
  ) => boolean;
  /** Held on at least one visible project — the client mirror of `authz.require_anywhere`
   *  (RADD-788). Use it on cross-project surfaces: project-scoped grants never reach the global
   *  union, so `global` is the wrong question there. The server still enforces per row. */
  anyProject: (permission: PermissionValue) => boolean;
  /** Held IN this space (RADD-814) — the space leg of the scope ladder. */
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

/** The instance's working day/week lengths for `formatDuration`; the 8h/5d defaults only while
 *  `GET /instance` is in flight. */
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

/** Story points on in this scope (the cascade-resolved `estimation_points`). Every points surface
 *  gates on it; false while loading, so points UI never flashes. */
export function usePointsEnabled(projectId?: string): boolean {
  const { data } = useQuery(resolvedSettingQuery(SettingKey.estimationPoints, projectId));
  return data?.value === true;
}

/** Which target states an item's state pickers may reach, and why not (spec 61). While loading, or
 *  with enforcement off, nothing is disabled. */
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

/** Per-item edit writability: `item.update` plus the per-field grant restrictions from
 *  `GET /fields/writable`. Editable surfaces DISABLE what the user cannot write, never edit-then-error. */
export function useItemWritability(
  project: Pick<Project, "id" | "permissions"> | null | undefined,
  /** The row, when the surface has one: relations make writability per-ROW (`item.update@own`), so
   *  the server's per-item verdict overrides the project-level answer (RADD-842). */
  item?: Pick<Item, "capabilities"> | null,
): ItemWritability {
  const perms = usePermissions();
  const { data, isError } = useQuery(fieldWritabilityQuery(project?.id));
  const projectLevel = project ? perms.project(project, Permission.itemUpdate) : false;
  const verdict = item?.capabilities?.can_update;
  const canEdit = verdict !== undefined && verdict !== null ? verdict : projectLevel;
  const rowDenied = projectLevel && canEdit === false;
  const readonly = useMemo(() => new Set(data?.readonly_fields ?? []), [data]);
  return useMemo(
    () => ({
      canEdit,
      fieldWritable: (name: string) => canEdit && data !== undefined && !readonly.has(name),
      restricted: (name: string) => readonly.has(name),
      reasonFor: (name: string) =>
        data === undefined && canEdit
          ? isError ? "Could not check field permissions." : "Checking field permissions…"
          : readonly.has(name)
          ? "This field is restricted — you don't have permission to edit it."
          : !canEdit
            ? rowDenied
              ? "Your edit access is limited to your own or your team's issues — this isn't one."
              : "You don't have permission to edit this issue."
            : "",
    }),
    [canEdit, rowDenied, readonly, data, isError],
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
  error: PositionedError | null;
  failure: string | null;
  /** Result numbers — only on surfaces that actually ran the query. */
  count?: number;
  atCap?: boolean;
}

/** Debounced live validation of an SLQ draft: `GET /items/slq/validate` parses and compiles but
 *  NEVER executes, so it is safe on every settled keystroke at any size. Empty drafts skip it. */
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

  const slqError = probe.isError ? positionedErrorOf(probe.error) : null;
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

/** Resolve an issue key (`TD-25`) through the server's by-key resolver, then its project (the scope
 *  the detail editor needs). */
export function useItemByKey(itemKey: string): ItemByKey {
  const itemByKey = useQuery({ ...itemByKeyQuery(itemKey), enabled: itemKey !== "" });
  const item = itemByKey.data;
  const projectQuery = useQuery(projectByIdQuery(item?.project_id ?? ""));
  // These determine the initial field layout and editability. Start alongside
  // the project read, and mount the detail with a coherent set of controls.
  // Shared query keys mean the body consumes these results without refetching.
  const states = useQuery({ ...statesQuery(item?.project_id ?? ""), enabled: Boolean(item) });
  const fields = useQuery({ ...fieldsQuery(), enabled: Boolean(item) });
  const screen = useQuery({
    ...effectiveScreenQuery(item?.project_id ?? "", item?.type?.id ?? null), enabled: Boolean(item),
  });
  const writability = useQuery(fieldWritabilityQuery(item?.project_id));
  const project = projectQuery.isError ? null : projectQuery.data;

  return {
    project,
    item: itemByKey.isError ? null : item,
    isPending: itemByKey.isPending || (Boolean(item) &&
      [projectQuery, states, fields, screen, writability].some(query => query.isPending)),
    isError: itemByKey.isError || projectQuery.isError,
  };
}
