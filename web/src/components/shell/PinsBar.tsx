import { useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  CalendarClock,
  CalendarRange,
  Clock,
  ConciergeBell,
  GanttChartSquare,
  House,
  Star,
  Inbox,
  Layers,
  LayoutDashboard,
  Link2,
  List,
  ListOrdered,
  Pencil,
  PinOff,
  Plus,
  Settings,
  SquareKanban,
  type LucideIcon,
} from "lucide-react";
import { ContextMenu } from "../ContextMenu";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath, RoutePath } from "../../lib/constants";
import { pageLink } from "../../lib/page-links";
import { usePermissions, useIsAuthenticated } from "../../lib/hooks";
import { pageByPathQuery, pageSpaceByIdentityQuery, projectByIdQuery, projectByKeyQuery, viewQuery } from "../../lib/queries";
import { useNavFacts } from "../../lib/nav-facts";
import { pinKey, useNavPins, type NavPin } from "../../lib/topbar-prefs";
import { Permission, type Page, type PageCreate, type Project, type View } from "../../lib/types";
import { NewItemModal } from "../items/NewItemModal";
import { ProjectPicker } from "../projects/ProjectPicker";
import { Button } from "../Button";
import { RenamePinDialog } from "./RenamePinDialog";

const tabBase =
  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-[13px] text-fg-secondary " +
  "hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus";
const tabActive = "bg-elevated text-heading font-medium";

/** A resolved pinned tab: view pins carry their live view, link pins don't. */
interface PinnedEntry {
  pin: NavPin;
  view?: View;
}

const VIEW_TYPE_ICONS: Record<string, LucideIcon> = {
  board: SquareKanban,
  planning: CalendarClock,
  roadmap: GanttChartSquare,
  queue: ListOrdered,
};

const LINK_ICONS: [prefix: string, icon: LucideIcon][] = [
  ["/inbox", Inbox],
  ["/starred", Star],
  ["/timesheet", Clock],
  ["/reports", BarChart3],
  ["/docs", BookOpen],
  ["/dashboards", LayoutDashboard],
  ["/cycles", CalendarRange],
  ["/portal", ConciergeBell],
  ["/projects", Layers],
  ["/p/", Layers],
  ["/settings", Settings],
];

/** Every pinned tab carries an icon — labels alone read as text, not nav. */
function tabIcon({ pin, view }: PinnedEntry): LucideIcon {
  if (view) return VIEW_TYPE_ICONS[view.view_type] ?? List;
  if (pin.kind !== "link") return List;
  return LINK_ICONS.find(([prefix]) => pin.path.startsWith(prefix))?.[1] ?? Link2;
}

/**
 * The top bar's SECOND row (Cairn-inspired): the user's pinned tabs — My Work
 * always first — plus the always-there New item button at the right edge.
 * Full viewport width, above the sidebar + content split.
 */
export function PinsBar() {
  const { pins, toggle, rename } = useNavPins();
  const authenticated = useIsAuthenticated(); // spec 121 (RADD-1149)
  const pinnedViewIds = pins.filter(pin => pin.kind === "view").map(pin => pin.id);
  const viewReads = useQueries({ queries: pinnedViewIds.map(viewQuery) });
  const views = viewReads.flatMap(query => query.data ? [query.data] : []);
  const projectIds = [...new Set(views.flatMap(view => view.project_id ? [view.project_id] : []))];
  const projects = useQueries({ queries: projectIds.map(projectByIdQuery) });
  const [menu, setMenu] = useState<{ x: number; y: number; entry: PinnedEntry } | null>(null);
  const [renaming, setRenaming] = useState<PinnedEntry | null>(null);

  // Resolve view pins → views; ids that no longer resolve (deleted, unshared)
  // simply don't render — the preference self-heals next time pins change.
  // Link pins (any other nav destination) need no resolution.
  const navFacts = useNavFacts();
  const pinned = pins
    .map((pin): PinnedEntry | null => {
      // RADD-843: a link pin to an area the actor cannot use is dropped from
      // RENDER but kept in prefs — access can return (the view-pin rule).
      if (pin.kind === "link") return navFacts.forPath(pin.path) ? { pin } : null;
      const view = views.find((entry) => entry.id === pin.id);
      return view ? { pin, view } : null;
    })
    .filter((entry): entry is PinnedEntry => entry !== null);
  const projectKey = (projectId: string | null) =>
    projects.find(query => query.data?.id === projectId)?.data?.key;

  // Tab text: the user's custom label wins; otherwise the view name / link
  // title — with the project key prefixed when several view pins share a name
  // ("Board" three times is which board?). Right-click offers Rename/Unpin.
  const nameCount = new Map<string, number>();
  for (const { view } of pinned)
    if (view) nameCount.set(view.name, (nameCount.get(view.name) ?? 0) + 1);
  const tabLabel = ({ pin, view }: PinnedEntry) => {
    if (pin.label) return pin.label;
    if (!view) return pin.kind === "link" ? pin.title : "";
    const key = projectKey(view.project_id);
    return (nameCount.get(view.name) ?? 0) > 1 && key ? `${key} · ${view.name}` : view.name;
  };

  return (
    // z-[45]: this row's own popovers (the New item project menu) must paint
    // over in-page sticky headers (z-40), while the query bar's floating UI in
    // the row ABOVE (z-50) must still paint over this row.
    <div className="relative z-[45] flex h-10 shrink-0 items-center gap-3 border-b border-subtle bg-base px-4">
      <nav
        aria-label="Pinned"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto"
      >
        {authenticated && (
          <Link
            to={RoutePath.home}
            activeOptions={{ exact: true }}
            activeProps={{ className: `${tabBase} ${tabActive}` }}
            inactiveProps={{ className: tabBase }}
          >
            <House size={13} aria-hidden />
            My Work
          </Link>
        )}
        {pinned.map((entry) => {
          const { pin, view } = entry;
          const key = view ? projectKey(view.project_id) : undefined;
          const identity = view
            ? key
              ? `${key} · ${view.name}`
              : view.name
            : pin.kind === "link"
              ? pin.title
              : "";
          const tabProps = {
            title: identity,
            onContextMenu: (event: React.MouseEvent) => {
              event.preventDefault();
              setMenu({ x: event.clientX, y: event.clientY, entry });
            },
            activeProps: { className: `${tabBase} ${tabActive} max-w-40` },
            inactiveProps: { className: `${tabBase} max-w-40` },
          };
          const Icon = tabIcon(entry);
          const text = (
            <>
              <Icon size={13} className="shrink-0" aria-hidden />
              <span className="truncate">{tabLabel(entry)}</span>
            </>
          );
          // A view tab routes by params (live key); a link tab replays the
          // captured URL (`to` is typed against the route tree and this path
          // is only known at runtime, hence the cast — same as plugin nav).
          if (!view)
            return (
              <Link
                key={pinKey(pin)}
                to={(pin.kind === "link" ? pin.path : "") as never}
                {...tabProps}
              >
                {text}
              </Link>
            );
          return view.project_id && key ? (
            <Link
              key={pinKey(pin)}
              to={RoutePath.projectView}
              params={{ projectKey: key, viewId: view.id }}
              {...tabProps}
            >
              {text}
            </Link>
          ) : (
            <Link
              key={pinKey(pin)}
              to={RoutePath.allProjectsView}
              params={{ viewId: view.id }}
              {...tabProps}
            >
              {text}
            </Link>
          );
        })}
      </nav>
      <NewItemButton />
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            {
              kind: "action",
              label: "Rename tab…",
              icon: Pencil,
              onSelect: () => setRenaming(menu.entry),
            },
            {
              kind: "action",
              label: "Unpin from top bar",
              icon: PinOff,
              onSelect: () => toggle(menu.entry.pin),
            },
          ]}
        />
      )}
      {renaming && (
        <RenamePinDialog
          fallbackName={
            renaming.view?.name ?? (renaming.pin.kind === "link" ? renaming.pin.title : "")
          }
          label={renaming.pin.label}
          onSave={(label) => rename(pinKey(renaming.pin), label)}
          onClose={() => setRenaming(null)}
        />
      )}
    </div>
  );
}

/** RADD-1243 (radd-hq/radd#15): the button creates what the route holds. In
 *  the wiki it is "New page" — under the open page, or at the root of the
 *  space — and everywhere else the New item it always was. A space the person
 *  cannot write in falls back to the item button, so nothing disappears. */
function NewItemButton() {
  const { spaceSlug, _splat: pagePath = "" } = useParams({ strict: false }) as {
    spaceSlug?: string;
    _splat?: string;
  };
  if (spaceSlug) return <NewPageButton spaceSlug={spaceSlug} pagePath={pagePath} />;
  return <NewWorkItemButton />;
}

function NewPageButton({ spaceSlug, pagePath }: { spaceSlug: string; pagePath: string }) {
  const perms = usePermissions();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const space = useQuery(pageSpaceByIdentityQuery(spaceSlug));
  const page = useQuery({ ...pageByPathQuery(spaceSlug, pagePath), enabled: Boolean(pagePath) });
  const create = useMutation({
    mutationFn: () =>
      api.post<Page>(ApiPath.pages, {
        space_id: space.data!.id,
        parent_id: page.data?.id ?? null,
        title: "Untitled",
      } satisfies PageCreate),
    onSuccess: (created) => void navigate(pageLink(created.space.slug, created.path)),
    onSettled: () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace),
  });
  if (!space.data || !perms.space(space.data, Permission.pageWrite)) return <NewWorkItemButton />;
  const under = pagePath && page.data ? page.data.title : null;
  return (
    <Button
      size="sm"
      onClick={() => create.mutate()}
      disabled={create.isPending || (Boolean(pagePath) && !page.data)}
      title={under ? `New page under ${under}` : `New page in ${space.data.name}`}
      data-new-page
    >
      <Plus size={13} aria-hidden />New page
    </Button>
  );
}

/** The route project creates in one click; other scopes open server search. */
function NewWorkItemButton() {
  const perms = usePermissions();
  const { projectKey } = useParams({ strict: false });
  const routeProject = useQuery(projectByKeyQuery(projectKey ?? ""));
  const [creating, setCreating] = useState<Project | null>(null);
  const [choosing, setChoosing] = useState(false);
  if (!perms.anyProject(Permission.itemCreate)) return null;
  const direct = routeProject.data && perms.project(routeProject.data, Permission.itemCreate)
    ? routeProject.data : null;
  return <>
    <Button size="sm" onClick={() => direct ? setCreating(direct) : setChoosing(true)}
      title={direct ? `New issue in ${direct.key}` : "Choose a project for a new issue"}>
      <Plus size={13} aria-hidden />New issue
    </Button>
    {choosing && <ProjectPicker title="New issue — choose a project" permission={Permission.itemCreate}
      onClose={() => setChoosing(false)} onSelect={project => { setChoosing(false); setCreating(project); }} />}
    {creating && <NewItemModal project={creating} onClose={() => setCreating(null)} />}
  </>;
}
