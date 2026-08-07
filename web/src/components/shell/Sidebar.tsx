import { useState, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useDisabledNavPaths } from "@radd/plugin-sdk";
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Clock,
  ConciergeBell,
  FolderSearch,
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
import { usePermissions } from "../../lib/hooks";
import { useNavFacts } from "../../lib/nav-facts";
import { pinKey, useNavPins, type NavPin } from "../../lib/topbar-prefs";
import { ContextMenu } from "../ContextMenu";
import {
  capabilitiesQuery,
  cyclesQuery,
  dashboardsQuery,
  pageSpacesQuery,
  projectsQuery,
  viewsQuery,
} from "../../lib/queries";
import { Permission, ViewType, type Project } from "../../lib/types";
import { openCommandPalette } from "../CommandPalette";
import { DashboardModal } from "../dashboards/DashboardModal";
import { NewItemModal } from "../items/NewItemModal";
import { ViewModal } from "../views/ViewModal";
import { useSidebarPrefs } from "./sidebar-prefs";
import { selectableCycles } from "../../lib/view-utils";
import { SidebarRail } from "./SidebarRail";
import {
  CycleRow,
  InboxLink,
  ProjectFormLinks,
  QueueLinks,
  SectionHeader,
  ViewRowContent,
  navLinkClasses,
  subLinkClasses,
} from "./SidebarRows";
import { UserMenu } from "./UserMenu";
import { modShortcut } from "../../lib/platform";

/** Scope a New-view dialog was opened for: a project, or all-projects (null). */
type ViewModalScope = { project: Project | null };

export function Sidebar() {
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
  const { data: projects } = useQuery(projectsQuery());
  const { data: views } = useQuery(viewsQuery());
  const { data: cycles } = useQuery(cyclesQuery());
  // RADD-808: no atom gate. `page.read` is SPACE-scoped since RADD-791, so
  // `perms.global` was false for everyone holding it from a space or team
  // grant — the fetch never fired and the section below never rendered.
  // `GET /page-spaces` already answers exactly this question against the
  // spec-92 access grants (`readable_spaces`) and returns an empty list rather
  // than a 403, so the server's answer IS the gate. Re-deriving it client-side
  // from atoms is the second implementation RADD-779 rejected.
  const { data: pageSpaces } = useQuery(pageSpacesQuery());
  const { data: dashboards } = useQuery(dashboardsQuery());
  /** Project the "New item" modal was opened for (from its sidebar row). */
  const [newItemProject, setNewItemProject] = useState<Project | null>(null);
  // RADD-882: 82 projects at the perf dataset — the nav section gets a compact
  // filter (name or key) once it outgrows a glance. Kept as a slim inline input
  // rather than the settings-page ListSearchInput: the rail is nav, not a page.
  const [projectFilter, setProjectFilter] = useState("");
  const [viewModalScope, setViewModalScope] = useState<ViewModalScope | null>(null);
  const [newDashboardOpen, setNewDashboardOpen] = useState(false);
  // Completed cycles are hidden by default to keep the rail focused
  // on what's live/upcoming; revealed on demand ("only explicitly ask for previous").
  // Spec 60: sections fold (persisted); project trees default COLLAPSED, with the
  // current route's project auto-expanded unless explicitly folded.
  const { prefs, toggleSection, toggleProject } = useSidebarPrefs();
  const { projectKey: currentProjectKey } = useParams({ strict: false });
  const sectionCollapsed = (id: string) => prefs.collapsedSections.includes(id);
  const projectExpanded = (project: Project) =>
    prefs.expandedProjects.includes(project.id) ||
    (project.key === currentProjectKey && !prefs.collapsedProjects.includes(project.id));

  // Queue views (spec 64) get their own badged section below — the generic
  // view lists skip them so a queue never renders twice.
  const queueViews = (views ?? []).filter((view) => view.view_type === ViewType.queue);
  const allProjectsViews = (views ?? []).filter(
    (view) => view.project_id === null && view.view_type !== ViewType.queue,
  );
  const viewsOf = (project: Project) =>
    (views ?? []).filter(
      (view) => view.project_id === project.id && view.view_type !== ViewType.queue,
    );
  // New-view affordances mirror the server (RADD-824): creating a PERSONAL
  // view needs only item.read in scope (views/service.PERSONAL_VIEW_PERMISSION)
  // — sharing is gated separately inside the modal. The all-projects scope
  // means "anywhere", not "globally" (RADD-788).
  /**
   * The rail lists projects the viewer is ENTITLED to (RADD-934), not every
   * project they could open.
   *
   * `GET /projects` gates on `require_anywhere(item.read)`, and that gate is
   * lattice-aware: `item.read@own` HOLDS `item.read` (RADD-823). Correct for a
   * gate — someone holding @own may read their own items anywhere, so the
   * project must stay openable or an issue assigned to them in a project they
   * are not a member of becomes unreachable. Wrong for a discovery surface: an
   * account with no grants at all was shown every project on the instance, each
   * one empty when opened.
   *
   * `perms.project` matches atoms EXACTLY (no lattice), so asking it for plain
   * `item.read` is the distinction — no new wire field, the atoms are already
   * on each row.
   */
  const entitledProjects = (projects ?? []).filter((project) =>
    perms.project(project, Permission.itemRead),
  );
  const ownOnlyProjectCount = (projects ?? []).length - entitledProjects.length;

  const canCreateView = perms.anyProject(Permission.itemRead);
  const cycleList = cycles ?? [];
  const liveCycles = selectableCycles(cycleList);
  const canManageCycles = perms.global(Permission.cycleUpdate);

  const railed = prefs.railCollapsed;

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
    <aside
      onContextMenu={onNavContextMenu}
      className={
        "flex shrink-0 flex-col border-r border-subtle bg-base transition-[width] duration-150 " +
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

        <InboxLink />

        <Link to={RoutePath.home} className={navLinkClasses} activeOptions={{ exact: true }}>
          <House size={14} aria-hidden />
          My Work
        </Link>

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

        {(allProjectsViews.length > 0 || canCreateView) && (
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
              <ul>
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
              </ul>
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
            <ul>
              {(dashboards ?? []).map((dashboard) => (
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
            </ul>
          )}
        </div>
        )}

        {/* Queues (spec 64): queue views with live count badges — one batched
            counts call for the whole section; hidden when no queues exist. */}
        {queueViews.length > 0 && (
          <div className="mt-3">
            <SectionHeader
              label="Queues"
              collapsed={sectionCollapsed("queues")}
              onToggle={() => toggleSection("queues")}
            />
            {!sectionCollapsed("queues") && (
              <QueueLinks views={queueViews} projects={projects ?? []} />
            )}
          </div>
        )}

        {/* Pages (spec 43): page spaces, between Views and Cycles.
            Shown when the server returned spaces, or when the actor may create
            one — deliberately-global: `page.manage` with no space is the global
            check `create_space` itself makes, so that branch is what keeps
            "No spaces yet." reachable for an admin on a fresh instance. Someone
            with neither sees no section at all rather than a permanently empty
            header (RADD-808). */}
        {((pageSpaces ?? []).length > 0 || perms.global(Permission.pageManage)) && (
          <div className="mt-3">
            <SectionHeader
              label="Pages"
              labelTo={RoutePath.pages}
              collapsed={sectionCollapsed("pages")}
              onToggle={() => toggleSection("pages")}
              actions={
                // deliberately-global: links to space ADMIN (create/rename),
                // which the server checks with no space id (RADD-810).
                perms.global(Permission.pageManage) && (
                  <Link
                    to={RoutePath.settingsPages}
                    aria-label="Manage page spaces"
                    title="Manage page spaces"
                    className="ml-auto rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
                  >
                    <Settings size={12} />
                  </Link>
                )
              }
            />
            {!sectionCollapsed("pages") &&
              ((pageSpaces ?? []).length === 0 ? (
                <p className="px-2 pb-1 text-xs text-fg-faint">No spaces yet.</p>
              ) : (
                <ul>
                  {(pageSpaces ?? []).map((space) => (
                    <li key={space.id}>
                      <Link
                        to={RoutePath.pageSpace}
                        params={{ spaceSlug: space.slug }}
                        className={navLinkClasses}
                      >
                        <BookOpen size={14} aria-hidden />
                        <span className="truncate">{space.name}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ))}
          </div>
        )}

        {(cycleList.length > 0 || canManageCycles) && (
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
            {!sectionCollapsed("cycles") &&
              (liveCycles.length === 0 ? (
                <p className="px-2 pb-1 text-xs text-fg-faint">No active cycles.</p>
              ) : (
                <ul>
                  {/* Completed cycles never appear here. The sidebar is a list
                      of places you still work; finished cycles accumulate
                      forever and only ever grow. They live on Settings →
                      Cycles, which has a name filter for finding one. */}
                  {liveCycles.map((cycle) => (
                    <CycleRow key={cycle.id} cycle={cycle} />
                  ))}
                </ul>
              ))}
          </div>
        )}

        {projects && projects.length > 0 && (
          <div className="mt-3">
            <SectionHeader
              label="Projects"
              collapsed={sectionCollapsed("projects")}
              onToggle={() => toggleSection("projects")}
            />
            {!sectionCollapsed("projects") && entitledProjects.length > 10 && (
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
            <ul>
              {(projectFilter.trim()
                ? entitledProjects.filter((project) => {
                    const needle = projectFilter.trim().toLowerCase();
                    return (
                      project.name.toLowerCase().includes(needle) ||
                      project.key.toLowerCase().includes(needle)
                    );
                  })
                : entitledProjects
              ).map((project) => (
                <li key={project.id}>
                  <div className="group/project relative flex items-center">
                    <button
                      type="button"
                      onClick={() => toggleProject(project.id, projectExpanded(project))}
                      aria-expanded={projectExpanded(project)}
                      aria-label={`${projectExpanded(project) ? "Collapse" : "Expand"} ${project.key}`}
                      className="ml-0.5 rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg cursor-pointer"
                    >
                      {projectExpanded(project) ? (
                        <ChevronDown size={11} aria-hidden />
                      ) : (
                        <ChevronRight size={11} aria-hidden />
                      )}
                    </button>
                    <Link
                      to={RoutePath.project}
                      params={{ projectKey: project.key }}
                      activeOptions={{ exact: true }}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1.5 pr-7 text-[13px] text-fg-secondary hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
                    >
                      <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
                        {project.key}
                      </span>
                      <span className="truncate">{project.name}</span>
                    </Link>
                    {perms.project(project, Permission.itemCreate) && (
                      <button
                        type="button"
                        onClick={() => setNewItemProject(project)}
                        aria-label={`New item in ${project.key}`}
                        title={`New item in ${project.key}`}
                        className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-fg-faint opacity-0 transition-opacity hover:bg-overlay hover:text-fg focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus group-hover/project:opacity-100 cursor-pointer"
                      >
                        <Plus size={12} />
                      </button>
                    )}
                  </div>

                  {/* Per-project section: the project's VIEWS (projects ship with
                      Board/List/Planning/Roadmap as plain seeded views — no
                      special entries), then the non-view surfaces. Folded by
                      default; the current route's project auto-expands. */}
                  {projectExpanded(project) && (
                  <ul className="pb-1">
                    {viewsOf(project).map((view) => (
                      <li key={view.id}>
                        <Link
                          to={RoutePath.projectView}
                          params={{ projectKey: project.key, viewId: view.id }}
                          className={subLinkClasses}
                        >
                          <ViewRowContent view={view} small />
                        </Link>
                      </li>
                    ))}
                    <li>
                      <Link
                        to={RoutePath.projectReports}
                        params={{ projectKey: project.key }}
                        className={subLinkClasses}
                      >
                        <BarChart3 size={12} aria-hidden />
                        Reports
                      </Link>
                    </li>
                    {(perms.project(project, Permission.stateManage) ||
                      perms.project(project, Permission.projectManage) ||
                      perms.project(project, Permission.formManage) ||
                      perms.project(project, Permission.releaseUpdate)) && (
                      <li>
                        <Link
                          to={RoutePath.projectSettings}
                          params={{ projectKey: project.key }}
                          className={subLinkClasses}
                        >
                          <Settings size={12} aria-hidden />
                          Settings
                        </Link>
                      </li>
                    )}
                    {perms.project(project, Permission.itemRead) && (
                      <li>
                        <button
                          type="button"
                          onClick={() => setViewModalScope({ project })}
                          className={`${subLinkClasses} w-full cursor-pointer text-left text-fg-faint!`}
                        >
                          <Plus size={12} aria-hidden />
                          New view
                        </button>
                      </li>
                    )}
                    {perms.project(project, Permission.formManage) && (
                      <ProjectFormLinks project={project} />
                    )}
                  </ul>
                  )}
                </li>
              ))}
            </ul>
            )}
            {/* RADD-934: the rail is honest about what it is NOT showing. These
                projects stay fully reachable — My Work, search and a direct link
                all open them — they are just not advertised, because the viewer
                can only see rows they own there. */}
            {!sectionCollapsed("projects") && ownOnlyProjectCount > 0 && (
              <Link
                to={RoutePath.projects}
                className="mx-1 flex items-center gap-1.5 rounded-md px-1.5 py-1.5 text-[12px] text-fg-faint hover:bg-overlay hover:text-fg-secondary focus-visible:outline-2 focus-visible:outline-focus"
                title="You can open these, but only items you own or take part in are visible in them."
              >
                <FolderSearch size={12} aria-hidden />
                {ownOnlyProjectCount} more with only your own items
              </Link>
            )}
          </div>
        )}
      </nav>
      )}

      {!railed && (
        <div className="border-t border-subtle px-2 py-2">
          <Link to={RoutePath.settings} className={navLinkClasses}>
            <Settings size={14} aria-hidden />
            Settings
          </Link>
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
    </aside>
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
