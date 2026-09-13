import { useMobileNavigation, closeMobileNavigation } from "./mobile-navigation";
import { useDialogFocus } from "../../lib/dialog-focus";
import { registerDismiss } from "../../lib/dismiss-stack";
import { useState, useEffect, useRef, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useLocation, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useDisabledNavPaths } from "@radd/plugin-sdk";
import {
  BarChart3,
  Clock,
  ConciergeBell,
  Eye,
  EyeOff,
  House,
  Layers,
  LayoutDashboard,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings,
  UserRound,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { DirectoryPager } from "../DirectoryPager";
import { useProjectDirectory } from "../../lib/useProjectDirectory";
import { usePermissions, useIsAuthenticated } from "../../lib/hooks";
import { useNavFacts } from "../../lib/nav-facts";
import {
  pinKey,
  useNavPins,
  useRelatedProjectsVisibility,
  type NavPin,
} from "../../lib/topbar-prefs";
import { ContextMenu } from "../ContextMenu";
import {
  capabilitiesQuery,
  cycleSummaryQuery,
  projectSummaryQuery,
  projectByKeyQuery,
} from "../../lib/queries";
import { Permission, ViewType, type Project } from "../../lib/types";
import { openCommandPalette } from "../CommandPalette";
import { DashboardModal } from "../dashboards/DashboardModal";
import { NewItemModal } from "../items/NewItemModal";
import { NewProjectModal } from "../projects/NewProjectModal";
import { ViewModal } from "../views/ViewModal";
import { useSidebarPrefs } from "./sidebar-prefs";
import { useViewDirectory, useDashboardDirectory } from "../../lib/useSharedDirectory";
import { SidebarDirectory } from "./SidebarDirectory";
import { SidebarSpaces } from "./SidebarSpaces";
import { useCycleDirectory } from "../../lib/useCycleDirectory";
import { SidebarRail } from "./SidebarRail";
import {
  CycleRow,
  InboxLink,
  QueueLinks,
  SectionHeader,
  ViewRowContent,
  navLinkClasses,
} from "./SidebarRows";
import { SidebarProjectRow } from "./SidebarProjectRow";
import { UserMenu } from "./UserMenu";
import { modShortcut } from "../../lib/platform";

/** Scope a New-view dialog was opened for: a project, or all-projects (null). */
type ViewModalScope = { project: Project | null };

export function Sidebar() {
  const mobileNav = useMobileNavigation();
  const path = useLocation({ select: location => location.pathname });
  const panelRef = useRef<HTMLElement>(null);
  useDialogFocus(panelRef, mobileNav.mobile && mobileNav.open);
  useEffect(() => closeMobileNavigation(), [path]);
  useEffect(() => {
    if (mobileNav.mobile && mobileNav.open) return registerDismiss(() => { closeMobileNavigation(); return true; });
  }, [mobileNav.mobile, mobileNav.open]);
  const perms = usePermissions();
  // Plugin-contributed nav from the backend UI manifest (spec 93 / A7, chokepoint
  // 3): an enabled plugin's nav item appears here with no edit to the shell.
  const { data: pluginManifest } = useQuery(capabilitiesQuery);
  const enabledCaps = new Set(
    (pluginManifest?.capabilities ?? []).filter((c) => c.enabled).map((c) => c.key),
  );
  // A plugin's route page can be turned off per-user/instance-wide (spec 94); when it is, drop its
  // manifest-driven nav link too — otherwise the link would dead-end on a hidden page.
  const disabledNav = useDisabledNavPaths();
  const pluginNav = (pluginManifest?.nav ?? [])
    .filter((n) => n.section === "main")
    .filter((n) => !n.capability || enabledCaps.has(n.capability))
    // RADD-843: `requires` through the scope-aware seam — a project-scoped
    // atom held on one project satisfies its nav link (the RADD-810 class).
    .filter((n) => n.requires.every((r) => perms.global(r) || perms.anyProject(r)))
    .filter((n) => !disabledNav.has(n.path));
  const nav = useNavFacts();
  const { data: projectSummary } = useQuery(projectSummaryQuery());
  const globalViews = useViewDirectory({ globalOnly: true, excludeType: ViewType.queue });
  const queues = useViewDirectory({ viewType: ViewType.queue });
  const cycles = useCycleDirectory({ includeCompleted: false });
  const cycleSummary = useQuery(cycleSummaryQuery());
  // Spec 121: dashboards are an account's surface; a visitor's rail skips the fetch.
  const authenticated = useIsAuthenticated();
  const dashboards = useDashboardDirectory(authenticated);
  /** Project the "New item" modal was opened for (from its sidebar row). */
  const [newItemProject, setNewItemProject] = useState<Project | null>(null);
  const [viewModalScope, setViewModalScope] = useState<ViewModalScope | null>(null);
  // RADD-1133: on an instance with NO projects the section used to vanish, and
  // with it the only path to "New project" — the first admin of a fresh install
  // had nowhere to start. project.create is global-scope (spec 06).
  const canCreateProject = perms.global(Permission.projectCreate);
  const [creatingProject, setCreatingProject] = useState(false);
  const [newDashboardOpen, setNewDashboardOpen] = useState(false);
  // Completed cycles are hidden by default to keep the rail focused
  // on what's live/upcoming; revealed on demand ("only explicitly ask for previous").
  // Spec 60: sections fold (persisted); project trees default COLLAPSED, with the
  // current route's project auto-expanded unless explicitly folded.
  const { prefs, toggleSection, toggleProject } = useSidebarPrefs();
  const { projectKey: currentProjectKey } = useParams({ strict: false });
  const currentProject = useQuery(projectByKeyQuery(currentProjectKey ?? ""));
  const sectionCollapsed = (id: string) => prefs.collapsedSections.includes(id);
  const projectExpanded = (project: Project) =>
    prefs.expandedProjects.includes(project.id) ||
    (project.key === currentProjectKey && !prefs.collapsedProjects.includes(project.id));

  // RADD-1041: the rail's own "related projects" preference — DISPLAY only.
  // `via: "related"` rows are exactly the ones `visible_projects` (RADD-937)
  // shows only because the person's own work makes a qualified item.read
  // count, never because of a grant; hiding them from this tree changes
  // nothing about whether they can still open one by URL, search, or My Work.
  const relatedProjectsPref = useRelatedProjectsVisibility();
  const directory = useProjectDirectory(relatedProjectsPref.mode === "never");
  const railProjects = directory.rows;
  const projectFilter = directory.filter;
  const contextProject = currentProject.data && !directory.filter.trim()
    && !railProjects.some(project => project.id === currentProject.data?.id)
    && (relatedProjectsPref.mode !== "never" || currentProject.data.via !== "related")
    ? currentProject.data : null;
  const setProjectFilter = directory.setFilter;
  const hiddenRelatedProjectCount = relatedProjectsPref.mode === "never" ? projectSummary?.related_count ?? 0 : 0;
  const showRelatedProjectsToggle = relatedProjectsPref.mode === "never" || (projectSummary?.related_count ?? 0) > 0;

  // Queue views (spec 64) get their own badged section below — the generic
  // view lists skip them so a queue never renders twice.
  const queueViews = queues.rows;
  const allProjectsViews = globalViews.rows;
  // New-view affordances mirror the server (RADD-824): creating a PERSONAL
  // view needs only item.read in scope (views/service.PERSONAL_VIEW_PERMISSION)
  // — sharing is gated separately inside the modal. The all-projects scope
  // means "anywhere", not "globally" (RADD-788).
  const canCreateView = perms.anyProject(Permission.itemRead);
  const cycleCount = Object.values(cycleSummary.data ?? {}).reduce((sum, count) => sum + count, 0);
  const liveCycles = cycles.rows;
  const canManageCycles = perms.global(Permission.cycleUpdate);

  const railed = !mobileNav.mobile && prefs.railCollapsed;

  // Right-click ANY nav link → pin/unpin it as a top-bar tab. One delegated
  // handler on the aside makes every sidebar destination pinnable — present
  // and future links alike — instead of wiring each row type. View links are
  // recognized by URL and stored as live-resolving view pins; everything else
  // is a link pin capturing {path, title}.
  const navPins = useNavPins();
  const [pinMenu, setPinMenu] = useState<{ x: number; y: number; pin: NavPin } | null>(null);
  const onNavContextMenu = (event: ReactMouseEvent) => {
    const target = event.target as HTMLElement;
    if (target.closest('[role="dialog"]')) return; // modals render inside the aside
    const anchor = target.closest("a");
    if (!anchor) return;
    const path = anchor.getAttribute("href");
    // "/" is the permanent My Work tab — a second pin of it would be noise.
    if (!path || !path.startsWith("/") || path === RoutePath.home) return;
    event.preventDefault();
    const viewId = /^(?:\/p\/[^/]+)?\/v\/([^/?#]+)$/.exec(path)?.[1];
    setPinMenu({
      x: event.clientX,
      y: event.clientY,
      pin: viewId
        ? { kind: "view", id: viewId }
        : { kind: "link", path, title: anchorPinTitle(anchor) },
    });
  };

  return (
    <>
    {mobileNav.mobile && mobileNav.open && <div className="fixed inset-0 z-30 bg-black/50" onClick={closeMobileNavigation} aria-hidden />}
    <aside
      ref={panelRef}
      tabIndex={-1}
      role={mobileNav.mobile ? "dialog" : undefined}
      aria-modal={mobileNav.mobile && mobileNav.open ? true : undefined}
      aria-label="Navigation"
      onContextMenu={onNavContextMenu}
      className={
        (mobileNav.mobile ? (mobileNav.open ? "fixed inset-y-0 left-0 z-40 flex pt-12 max-w-[85vw] " : "hidden ") : "flex ") +
        "shrink-0 flex-col border-r border-subtle bg-base transition-[width] duration-150 " +
        (railed ? "w-14" : "w-60")
      }
    >
      {/* Brand + the collapse toggle moved to the full-width top bar (row 1);
          the sidebar starts directly with nav under the two bars. */}
      {railed && <SidebarRail pluginNav={pluginNav} />}

      {!railed && (
      <nav className="flex-1 overflow-y-auto px-2 py-1">
        <button
          type="button"
          onClick={openCommandPalette}
          className={`${navLinkClasses} w-full cursor-pointer`}
        >
          <Search size={14} aria-hidden />
          Search
          <kbd className="ml-auto rounded border border-subtle px-1 text-[10px] text-fg-muted">
            {modShortcut('K')}
          </kbd>
        </button>

        {/* Spec 121: a visitor has no inbox and no My Work (RADD-1149). */}
        {authenticated && (
          <>
            <InboxLink />

            <Link to={RoutePath.home} className={navLinkClasses} activeOptions={{ exact: true }}>
              <House size={14} aria-hidden />
              My Work
            </Link>
          </>
        )}

        {/* RADD-843: fixed destinations render only where the area can be
            useful to the actor (useNavFacts — the same predicate the rail,
            palette and pins consume). Hiding is presentation; every area
            still enforces its own authz on direct navigation. */}
        {nav.portal && (
          <Link to={RoutePath.portal} className={navLinkClasses}>
            <ConciergeBell size={14} aria-hidden />
            Submission Portal
          </Link>
        )}

        {nav.projects && (
          <Link to={RoutePath.projects} className={navLinkClasses} activeOptions={{ exact: true }}>
            <Layers size={14} aria-hidden />
            Projects
          </Link>
        )}

        {nav.reports && (
          <Link to={RoutePath.reports} className={navLinkClasses}>
            <BarChart3 size={14} aria-hidden />
            Reports
          </Link>
        )}

        {nav.timesheet && (
          <Link to={RoutePath.timesheet} className={navLinkClasses}>
            <Clock size={14} aria-hidden />
            Timesheet
          </Link>
        )}

        {/* Plugin-contributed nav (spec 93 / A7), routed CLIENT-SIDE through the
            `$` splat that spec 94 added for `route.page` (router.tsx). These were
            plain <a> until then, which meant a full document reload — bundle
            re-download, white flash, every query refetched — on Notes/Milestones
            and nothing else. `to` is typed against the route tree and these
            paths are only known at runtime, hence the cast. */}
        {pluginNav.map((n) => (
          <Link
            key={n.key}
            to={n.path as never}
            className={navLinkClasses}
            title={n.label}
            data-plugin-nav={n.key}
          >
            <Layers size={14} aria-hidden />
            {n.label}
          </Link>
        ))}

        {(globalViews.total > 0 || Boolean(globalViews.filter) || globalViews.isError || canCreateView) && (
          <div className="mt-3">
            <SectionHeader
              label="Views"
              collapsed={sectionCollapsed("views")}
              onToggle={() => toggleSection("views")}
              actions={
                canCreateView && (
                  <button
                    type="button"
                    onClick={() => setViewModalScope({ project: null })}
                    aria-label="New global view"
                    title="New global view"
                    className="ml-auto rounded p-0.5 text-fg-faint opacity-0 transition-opacity hover:bg-overlay hover:text-fg focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus group-hover/section:opacity-100 cursor-pointer"
                  >
                    <Plus size={12} />
                  </button>
                )
              }
            />
            {!sectionCollapsed("views") && (
              <SidebarDirectory directory={globalViews} label="global views"><ul>
                {allProjectsViews.map((view) => (
                  <li key={view.id}>
                    <Link
                      to={RoutePath.allProjectsView}
                      params={{ viewId: view.id }}
                      className={navLinkClasses}
                    >
                      <ViewRowContent view={view} />
                    </Link>
                  </li>
                ))}
              </ul></SidebarDirectory>
            )}
          </div>
        )}

        {/* Dashboards (spec 75): the visible composable dashboards + a New
            row. RADD-843: the section renders only when there is something to
            show or the actor can create one (the Views-section rule). */}
        {nav.dashboards && (
        <div className="mt-3">
          <SectionHeader
            label="Dashboards"
            collapsed={sectionCollapsed("dashboards")}
            onToggle={() => toggleSection("dashboards")}
          />
          {!sectionCollapsed("dashboards") && (
            <SidebarDirectory directory={dashboards} label="dashboards"><ul>
              {dashboards.rows.map((dashboard) => (
                <li key={dashboard.id}>
                  <Link
                    to={RoutePath.dashboard}
                    params={{ dashboardId: dashboard.id }}
                    className={navLinkClasses}
                  >
                    <LayoutDashboard size={14} aria-hidden />
                    <span className="truncate">{dashboard.name}</span>
                    {!dashboard.shared && (
                      <UserRound
                        size={11}
                        className="ml-auto shrink-0 text-fg-faint"
                        aria-label="Personal dashboard"
                      />
                    )}
                  </Link>
                </li>
              ))}
              {perms.anyProject(Permission.dashboardCreate) && (
                <li>
                  <button
                    type="button"
                    onClick={() => setNewDashboardOpen(true)}
                    className={`${navLinkClasses} w-full cursor-pointer text-fg-muted!`}
                  >
                    <Plus size={14} aria-hidden />
                    New dashboard
                  </button>
                </li>
              )}
            </ul></SidebarDirectory>
          )}
        </div>
        )}

        {/* Queues (spec 64): queue views with live count badges — one batched
            counts call for the whole section; hidden when no queues exist. */}
        {(queues.total > 0 || Boolean(queues.filter) || queues.isError) && (
          <div className="mt-3">
            <SectionHeader
              label="Queues"
              collapsed={sectionCollapsed("queues")}
              onToggle={() => toggleSection("queues")}
            />
            {!sectionCollapsed("queues") && (
              <SidebarDirectory directory={queues} label="queues"><QueueLinks views={queueViews} /></SidebarDirectory>
            )}
          </div>
        )}

        <SidebarSpaces collapsed={sectionCollapsed("pages")} onToggle={() => toggleSection("pages")}
          canManage={perms.anySpace(Permission.pageManage)} />

        {(cycleCount > 0 || canManageCycles) && (
          <div className="mt-3">
            <SectionHeader
              label="Cycles"
              collapsed={sectionCollapsed("cycles")}
              onToggle={() => toggleSection("cycles")}
              actions={
                canManageCycles && (
                  <Link
                    to={RoutePath.settingsCycles}
                    aria-label="Manage cycles"
                    title="Manage cycles"
                    className="ml-auto rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
                  >
                    <Settings size={12} />
                  </Link>
                )
              }
            />
            {!sectionCollapsed("cycles") && <div aria-busy={cycles.busy}>
              {cycleCount > 10 && <input type="search" value={cycles.filter} onChange={event => cycles.setFilter(event.target.value)}
                placeholder="Find a live cycle…" aria-label="Find a live cycle"
                className="mx-1 mb-1 h-7 w-[calc(100%-0.5rem)] rounded-md border border-subtle bg-surface px-2 text-xs text-heading placeholder:text-fg-faint focus-visible:outline-2 focus-visible:outline-focus" />}
              {cycles.isError ? <p className="px-2 text-xs text-status-danger-ink">Cycles could not load.</p>
                : cycles.isPending ? <p className="px-2 text-xs text-fg-muted">Loading cycles…</p>
                : liveCycles.length === 0 ? <p className="px-2 pb-1 text-xs text-fg-faint">No matching live cycles.</p>
                : <ul>{liveCycles.map(cycle => <CycleRow key={cycle.id} cycle={cycle} />)}</ul>}
              <DirectoryPager {...cycles} onPage={cycles.setPage} label="sidebar cycles" />
            </div>}
          </div>
        )}

        {((projectSummary?.total ?? 0) > 0 || directory.isError || canCreateProject) && (
          <div className="mt-3">
            <SectionHeader
              label="Projects"
              collapsed={sectionCollapsed("projects")}
              onToggle={() => toggleSection("projects")}
              actions={
                showRelatedProjectsToggle && (
                  <button
                    type="button"
                    onClick={() =>
                      relatedProjectsPref.setMode(
                        relatedProjectsPref.mode === "never" ? "always" : "never",
                      )
                    }
                    aria-pressed={relatedProjectsPref.mode === "never"}
                    aria-label={
                      relatedProjectsPref.mode === "never"
                        ? "Show related projects"
                        : "Hide related projects"
                    }
                    title={
                      relatedProjectsPref.mode === "never"
                        ? "Show projects you can only see through your own work"
                        : "Hide projects you can only see through your own work (open, search, and My Work still reach them)"
                    }
                    className="ml-auto rounded p-0.5 text-fg-faint opacity-0 transition-opacity hover:bg-overlay hover:text-fg focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus group-hover/section:opacity-100 cursor-pointer"
                  >
                    {relatedProjectsPref.mode === "never" ? (
                      <EyeOff size={12} />
                    ) : (
                      <Eye size={12} />
                    )}
                  </button>
                )
              }
            />
            {!sectionCollapsed("projects") && ((projectSummary?.total ?? 0) > 10 || Boolean(projectFilter)) && (
              <input
                type="search"
                value={projectFilter}
                onChange={(event) => setProjectFilter(event.target.value)}
                placeholder="Filter projects…"
                aria-label="Filter projects by name or key"
                className="mx-1 mb-1 h-7 w-[calc(100%-0.5rem)] rounded-md border border-subtle bg-surface px-2 text-xs text-heading placeholder:text-fg-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
              />
            )}
            {!sectionCollapsed("projects") && (
            <div aria-busy={directory.busy}>
            {contextProject && <div className="mb-2 border-b border-subtle pb-1">
              <p className="px-2 text-[11px] text-fg-muted">Current project</p>
              <ul><SidebarProjectRow project={contextProject}
                expanded={projectExpanded(contextProject)} permissions={perms}
                onToggle={() => toggleProject(contextProject.id, projectExpanded(contextProject))}
                onNewItem={() => setNewItemProject(contextProject)} onNewView={() => setViewModalScope({ project: contextProject })} /></ul>
            </div>}
            {directory.isError && <p className="px-2 text-xs text-status-danger-ink">Projects could not load.</p>}
            {directory.isPending && <p className="px-2 text-xs text-fg-muted">Loading projects…</p>}
            {!directory.isPending && !directory.isError && railProjects.length === 0 && (
              <p className="px-2 text-xs text-fg-muted">
                {(projectSummary?.total ?? 0) === 0 && !projectFilter.trim() ? "No projects yet." : "No matching projects."}
              </p>
            )}
            <ul>
              {canCreateProject && (projectSummary?.total ?? 0) === 0 && !directory.isPending && (
                <li>
                  <button
                    type="button"
                    onClick={() => setCreatingProject(true)}
                    className={`${navLinkClasses} w-full cursor-pointer text-fg-muted!`}
                  >
                    <Plus size={14} aria-hidden />
                    New project
                  </button>
                </li>
              )}
              {railProjects.map((project) => (
                <SidebarProjectRow key={project.id} project={project}
                  expanded={projectExpanded(project)} permissions={perms}
                  onToggle={() => toggleProject(project.id, projectExpanded(project))}
                  onNewItem={() => setNewItemProject(project)} onNewView={() => setViewModalScope({ project })} />
              ))}
            </ul>
            <DirectoryPager {...directory} onPage={directory.setPage} label="sidebar projects" />
            </div>
            )}
            {/* RADD-1041: a project you can read but don't SEE reads as a bug
                without this — say what's hidden and offer the one click back. */}
            {!sectionCollapsed("projects") && hiddenRelatedProjectCount > 0 && (
              <p className="px-2 pb-1 text-[11px] text-fg-faint">
                {hiddenRelatedProjectCount} related project
                {hiddenRelatedProjectCount === 1 ? "" : "s"} hidden —{" "}
                <button
                  type="button"
                  onClick={() => relatedProjectsPref.setMode("always")}
                  className="text-accent-text hover:text-accent-text-strong hover:underline cursor-pointer"
                >
                  Show
                </button>
              </p>
            )}
          </div>
        )}
      </nav>
      )}

      {!railed && (
        <div className="border-t border-subtle px-2 py-2">
          {authenticated && (
            <Link to={RoutePath.settings} className={navLinkClasses}>
              <Settings size={14} aria-hidden />
              Settings
            </Link>
          )}
          <UserMenu />
        </div>
      )}


      {pinMenu && (
        <ContextMenu
          x={pinMenu.x}
          y={pinMenu.y}
          onClose={() => setPinMenu(null)}
          items={[
            navPins.isPinned(pinKey(pinMenu.pin))
              ? {
                  kind: "action",
                  label: "Unpin from top bar",
                  icon: PinOff,
                  onSelect: () => navPins.toggle(pinMenu.pin),
                }
              : {
                  kind: "action",
                  label: "Pin to top bar",
                  icon: Pin,
                  onSelect: () => navPins.toggle(pinMenu.pin),
                },
          ]}
        />
      )}
      {newItemProject && (
        <NewItemModal project={newItemProject} onClose={() => setNewItemProject(null)} />
      )}
      {viewModalScope && (
        <ViewModal project={viewModalScope.project} onClose={() => setViewModalScope(null)} />
      )}
      {newDashboardOpen && <DashboardModal onClose={() => setNewDashboardOpen(false)} />}
      {creatingProject && <NewProjectModal onClose={() => setCreatingProject(false)} />}
    </aside>
    </>
  );
}

/** The pin title for a nav anchor: an explicit override (`data-pin-label`,
 * for rows whose text carries volatile decoration like unread counts), else
 * the title/aria-label, else the visible text nodes joined with spaces (so a
 * project row's key chip + name reads "DEV Development", not "DEVDevelopment"). */
function anchorPinTitle(anchor: HTMLAnchorElement): string {
  const explicit =
    anchor.dataset.pinLabel || anchor.getAttribute("title") || anchor.getAttribute("aria-label");
  if (explicit) return explicit;
  const walker = document.createTreeWalker(anchor, NodeFilter.SHOW_TEXT);
  const parts: string[] = [];
  while (walker.nextNode()) {
    const text = walker.currentNode.textContent?.trim();
    if (text) parts.push(text);
  }
  return parts.join(" ") || (anchor.getAttribute("href") ?? "Link");
}
