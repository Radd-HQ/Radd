import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  CalendarClock,
  CalendarRange,
  Clock,
  ConciergeBell,
  GanttChartSquare,
  House,
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
import { RoutePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { projectsQuery, viewsQuery } from "../../lib/queries";
import { pinKey, useNavPins, type NavPin } from "../../lib/topbar-prefs";
import { Permission, type Project, type View } from "../../lib/types";
import { NewItemModal } from "../items/NewItemModal";
import { DropdownMenu } from "../DropdownMenu";
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
  const views = useQuery(viewsQuery());
  const projects = useQuery(projectsQuery());
  const [menu, setMenu] = useState<{ x: number; y: number; entry: PinnedEntry } | null>(null);
  const [renaming, setRenaming] = useState<PinnedEntry | null>(null);

  // Resolve view pins → views; ids that no longer resolve (deleted, unshared)
  // simply don't render — the preference self-heals next time pins change.
  // Link pins (any other nav destination) need no resolution.
  const pinned = pins
    .map((pin): PinnedEntry | null => {
      if (pin.kind === "link") return { pin };
      const view = (views.data ?? []).find((entry) => entry.id === pin.id);
      return view ? { pin, view } : null;
    })
    .filter((entry): entry is PinnedEntry => entry !== null);
  const projectKey = (projectId: string | null) =>
    (projects.data ?? []).find((project) => project.id === projectId)?.key;

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
        <Link
          to={RoutePath.home}
          activeOptions={{ exact: true }}
          activeProps={{ className: `${tabBase} ${tabActive}` }}
          inactiveProps={{ className: tabBase }}
        >
          <House size={13} aria-hidden />
          My Work
        </Link>
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
      <NewItemButton projects={projects.data ?? []} />
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

const newItemButtonClasses =
  "inline-flex h-7 shrink-0 cursor-pointer select-none items-center gap-1.5 rounded-md " +
  "bg-accent px-2.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/**
 * The always-visible create button (every surface, not just item views).
 * Context-aware: inside a project it creates there in one click; anywhere
 * else it offers the projects the user can create in. Hidden only when the
 * user can create nowhere.
 */
function NewItemButton({ projects }: { projects: Project[] }) {
  const perms = usePermissions();
  const { projectKey } = useParams({ strict: false });
  const [creating, setCreating] = useState<Project | null>(null);
  const creatable = projects.filter((project) =>
    perms.project(project, Permission.itemCreate),
  );
  if (creatable.length === 0) return null;
  const routeProject = creatable.find((project) => project.key === projectKey);
  const direct = routeProject ?? (creatable.length === 1 ? creatable[0] : null);
  return (
    <>
      {direct ? (
        <button
          type="button"
          onClick={() => setCreating(direct)}
          title={`New item in ${direct.key}`}
          className={newItemButtonClasses}
        >
          <Plus size={13} aria-hidden />
          New item
        </button>
      ) : (
        <DropdownMenu
          label="New item"
          align="end"
          widthClass="w-56"
          items={creatable.map((project) => ({
            kind: "action" as const,
            label: `${project.key} — ${project.name}`,
            onSelect: () => setCreating(project),
          }))}
          trigger={({ ref, open, toggle }) => (
            <button
              ref={ref}
              type="button"
              onClick={toggle}
              aria-haspopup="menu"
              aria-expanded={open}
              className={newItemButtonClasses}
            >
              <Plus size={13} aria-hidden />
              New item
            </button>
          )}
        />
      )}
      {creating && <NewItemModal project={creating} onClose={() => setCreating(null)} />}
    </>
  );
}
