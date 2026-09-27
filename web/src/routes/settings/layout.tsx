import { fieldSettingsSummaryQuery } from "../../lib/queries/field-settings";
import { Link, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useDisabledNavPaths, useIsInstanceAdmin } from "@radd/plugin-sdk";
import {
  Bell,
  Blocks,
  BookOpen,
  Bot,
  CalendarRange,
  CircleUserRound,
  Clock,
  DatabaseBackup,
  HardDrive,
  KeyRound,
  Link2,
  MessageSquareQuote,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Tags,
  UserRoundCog,
  UsersRound,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { iconOrFallback } from "../../lib/icons";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { capabilitiesQuery } from "../../lib/queries";
import { Permission, type PermissionValue, type CapabilitiesManifest } from "../../lib/types";

/** Predicate helpers a nav item uses to decide whether the viewer may see it. */
interface NavGate {
  fieldSettings?: boolean;
  /** The viewer holds `permission` at global scope (or is admin). */
  global: (permission: PermissionValue) => boolean;
  /** The viewer holds `permission` on at least one accessible project. */
  any: (permission: PermissionValue) => boolean;
  anySpace: (permission: PermissionValue) => boolean;
  /** The viewer is an instance admin (spec 50 — gates the Instance tab). */
  instanceAdmin: boolean;
  /** The viewer owns or manages at least one team (spec 87). Per-team
   * delegation is invisible to the permission union, so it needs its own flag. */
  managesTeams: boolean;
}

interface SettingsNavItem {
  to: string;
  order?: number;
  label: string;
  icon: LucideIcon;
  show: (g: NavGate) => boolean;
  /** The optional plugin this tab is a surface OF (RADD-928): disabling it unmounts its router, so
   *  the tab is withdrawn with it. Omitted = always mounted. */
  plugin?: string;
}

/** The settings nav, grouped; a group header renders only when one of its items does. `show` gates
 *  each tab by scope (spec 50); the backend enforces the same gates. */
const SETTINGS_NAV_GROUPS: readonly { label: string; items: readonly SettingsNavItem[] }[] = [
  {
    label: "Account",
    items: [
      { to: RoutePath.settingsProfile, label: "Profile", icon: CircleUserRound, show: () => true },
      {
        to: RoutePath.settingsNotifications,
        label: "Notifications",
        icon: Bell,
        show: () => true,
      },
      { to: RoutePath.settingsTokens, label: "API tokens", icon: KeyRound, show: () => true },
    ],
  },
  {
    label: "Issues",
    items: [
      {
        to: RoutePath.settingsFields,
        label: "Fields",
        icon: SlidersHorizontal,
        // deliberately-global: instance-wide field.manage opens the tab even with no visible project.
        show: (g) => Boolean(g.fieldSettings) || g.global(Permission.fieldManage) || g.any(Permission.fieldManage),
      },
      {
        to: RoutePath.settingsLinkTypes,
        label: "Link types",
        icon: Link2,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsLabels,
        label: "Labels",
        icon: Tags,
        show: (g) => g.global(Permission.labelUpdate),
      },
      {
        to: RoutePath.settingsCycles,
        label: "Cycles",
        icon: CalendarRange,
        show: (g) => g.global(Permission.cycleUpdate),
      },
      {
        to: RoutePath.settingsTimelogging,
        label: "Time logging",
        icon: Clock,
        show: (g) => g.global(Permission.globalManage),
      },
      {
        to: RoutePath.settingsCanned,
        label: "Canned responses",
        icon: MessageSquareQuote,
        show: (g) => g.global(Permission.cannedUpdate),
      },
    ],
  },
  {
    label: "People",
    items: [
      {
        to: RoutePath.settingsUsers,
        label: "Users",
        icon: UserRoundCog,
        show: (g) => g.global(Permission.globalManage) || g.instanceAdmin,
      },
      {
        to: RoutePath.settingsServiceAccounts,
        label: "Service accounts",
        icon: Bot,
        show: (g) => g.global(Permission.globalManage),
      },
      {
        to: RoutePath.settingsTeams,
        label: "Teams",
        icon: UsersRound,
        // A team leader holds no global team atom; `manages_teams` keeps the page reachable (spec 87).
        show: (g) => g.global(Permission.teamUpdate) || g.global(Permission.teamCreate) || g.global(Permission.teamDelete) || g.managesTeams,
      },
      {
        to: RoutePath.settingsRoles,
        label: "Roles",
        icon: ShieldCheck,
        show: (g) => g.global(Permission.roleUpdate),
      },
    ],
  },
  {
    label: "Server",
    items: [
      {
        to: RoutePath.settingsInstance,
        order: 0,
        label: "Server status",
        icon: Server,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsGeneral,
        order: 10,
        label: "General",
        icon: SlidersHorizontal,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsPages,
        order: 20,
        label: "Page spaces",
        icon: BookOpen,
        plugin: "pages",
        show: (g) => g.anySpace(Permission.pageManage),
      },
      {
        to: RoutePath.settingsStorage,
        order: 40,
        label: "Storage",
        icon: HardDrive,
        show: (g) => g.instanceAdmin,
      },
      {
        // The MFA policy (core auth) plus contributed sign-in sections; it names no owner plugin.
        to: RoutePath.settingsSignIn,
        order: 70,
        label: "Sign-in",
        icon: KeyRound,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsBackups,
        order: 80,
        label: "Backups",
        icon: DatabaseBackup,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsWebhooks,
        order: 90,
        label: "Webhooks",
        icon: Webhook,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsPlugins,
        order: 110,
        label: "Plugins",
        icon: Blocks,
        show: (g) => g.instanceAdmin,
      },
    ],
  },
];

/** Where a plugin's settings live, for the Plugins page: its contributed settings page, else the
 *  host tab naming it as `plugin`, else a page it contributes a `settings.section` to (a section's
 *  key is its page's segment). Derived from the table the nav renders, so the two cannot disagree. */
export function settingsPathForPlugin(
  name: string,
  manifest?: CapabilitiesManifest,
  sectionKeys: readonly string[] = [],
): { to: string; label: string } | null {
  const contributed = manifest?.nav.find(n => n.plugin === name && n.section === "settings");
  if (contributed) return { to: contributed.path, label: contributed.label };
  for (const group of SETTINGS_NAV_GROUPS) {
    const match = group.items.find((item) => item.plugin === name);
    if (match) return { to: match.to, label: match.label };
  }
  for (const key of sectionKeys) {
    const page = settingsPageAt(`${RoutePath.settings}/${key}`, manifest);
    if (page) return page;
  }
  return null;
}

/** The settings page at `path` — a host tab or a plugin-contributed one — as a link. */
function settingsPageAt(path: string, manifest?: CapabilitiesManifest): { to: string; label: string } | null {
  const contributed = manifest?.nav.find(n => n.section === "settings" && n.path === path);
  if (contributed) return { to: contributed.path, label: contributed.label };
  for (const group of SETTINGS_NAV_GROUPS) {
    const item = group.items.find((candidate) => candidate.to === path);
    if (item) return { to: item.to, label: item.label };
  }
  return null;
}

/** Settings shell: secondary nav on the left (scope-gated), active section in the Outlet. */
export function SettingsLayout() {
  const perms = usePermissions();
  const user = useCurrentUser();
  const instanceAdmin = useIsInstanceAdmin();
  const { data: manifest } = useQuery(capabilitiesQuery);

  const fields = useQuery({ ...fieldSettingsSummaryQuery(), enabled: manifest?.plugins.includes("fields") ?? false });

  const gate: NavGate = {
    fieldSettings: fields.data?.can_access,
    global: (permission) => perms.global(permission),
    any: perms.anyProject,
    anySpace: perms.anySpace,
    instanceAdmin,
    managesTeams: Boolean(user?.manages_teams),
  };
  // `plugins` is what is MOUNTED now; while the manifest is in flight every gated tab is hidden —
  // a tab that appears late reads as loading, one that vanishes reads as a bug.
  const mounted = new Set(manifest?.plugins ?? []);
  const isMounted = (item: SettingsNavItem) => !item.plugin || mounted.has(item.plugin);
  // Builtin rows fall back to index × 10; the Server group pins its numbers instead, because
  // plugins slot their pages between them by `order` (AI 25, Email 45, Directory 55, Automations
  // 90…) and a row that moved out would otherwise renumber everything after it.
  const visibleGroups = SETTINGS_NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.map((item, index) => ({ ...item, order: item.order ?? index * 10 })).filter((item) => item.show(gate) && isMounted(item)),
  })).filter((group) => group.items.length > 0);

  // Plugin-contributed settings pages (spec 94): federated plugins register a `settings.page` slot
  // and a `section: "settings"` nav item; they appear here alongside the builtin tabs, gated by the
  // viewer's atoms + the plugin's capability — with no edit to this array. A `group` no builtin
  // group carries becomes its own heading after them: "Import" is the importers' (RADD-1382).
  const enabledCaps = new Set(
    (manifest?.capabilities ?? []).filter((c) => c.enabled).map((c) => c.key),
  );
  // A turned-off settings.page contribution (spec 94) also drops its nav link here.
  const disabledNav = useDisabledNavPaths();
  const pluginSettingsNav = (manifest?.nav ?? [])
    .filter((n) => n.section === "settings")
    .filter((n) => !n.capability || enabledCaps.has(n.capability))
    .filter((n) => !n.requires_admin || gate.instanceAdmin)
    .filter((n) => n.requires.every((r) => perms.global(r)))
    .filter((n) => (n.requires_any_project ?? []).every((r) => perms.anyProject(r)))
    .filter((n) => !disabledNav.has(n.path));
  for (const nav of pluginSettingsNav) {
    const label = nav.group || "Extensions";
    let group = visibleGroups.find(g => g.label === label);
    if (!group) { group = { label, items: [] }; visibleGroups.push(group); }
    if (!group.items.some(item => item.to === nav.path)) group.items.push({
      to: nav.path, label: nav.label, icon: iconOrFallback(nav.icon),
      order: nav.order, show: () => true,
    });
  }
  for (const group of visibleGroups) group.items.sort((a, b) => a.order - b.order);


  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-subtle px-6 py-3.5">
        <h1 className="text-sm font-semibold text-heading">Settings</h1>
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <nav
          aria-label="Settings sections"
          className="flex w-full shrink-0 gap-2 overflow-x-auto border-b border-subtle p-2 lg:block lg:w-48 lg:overflow-y-auto lg:border-b-0 lg:border-r"
        >
          {visibleGroups.map((group, index) => (
            <section key={group.label} aria-label={group.label}>
              <h2
                className={`hidden lg:block px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-fg-faint ${
                  index === 0 ? "pt-1" : "pt-4"
                }`}
              >
                {group.label}
              </h2>
              <ul className="flex gap-0.5 lg:flex-col">
                {group.items.map(({ to, label, icon: Icon }) => (
                  <li key={to}>
                    <Link
                      to={to}
                      className="flex items-center whitespace-nowrap gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-focus [&.active]:bg-elevated [&.active]:text-heading"
                    >
                      <Icon size={14} aria-hidden />
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}

        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
