import { Link, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useDisabledNavPaths } from "@radd/plugin-sdk";
import {
  Activity,
  Blocks,
  BookOpen,
  Bot,
  CalendarOff,
  CalendarRange,
  CircleUserRound,
  Clock,
  DatabaseBackup,
  DatabaseZap,
  GitBranch,
  HardDrive,
  KeyRound,
  Link2,
  MessageSquareQuote,
  ScrollText,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tags,
  UserRoundCog,
  UsersRound,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { capabilitiesQuery, projectsQuery } from "../../lib/queries";
import { InstanceRole, Permission, type PermissionValue } from "../../lib/types";

/** Predicate helpers a nav item uses to decide whether the viewer may see it. */
interface NavGate {
  /** The viewer holds `permission` at global scope (or is admin). */
  ws: (permission: PermissionValue) => boolean;
  /** The viewer holds `permission` on at least one accessible project. */
  any: (permission: PermissionValue) => boolean;
  /** The viewer is an instance admin (spec 50 — gates the Instance tab). */
  instanceAdmin: boolean;
  /** The viewer owns or manages at least one team (spec 87). Per-team
   * delegation is invisible to the permission union, so it needs its own flag. */
  managesTeams: boolean;
}

interface SettingsNavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  show: (g: NavGate) => boolean;
}

/**
 * The settings nav, GROUPED (reorg): Account (personal), Issues
 * (work-item configuration), People (accounts + access), Server (operator +
 * deploy). A group header renders only when the viewer can see at least one
 * of its items; `show` gates each tab by scope (spec 50) and the backend
 * enforces the same gates (403). Section URLs are unchanged — this regroups
 * navigation, it does not move pages.
 */
const SETTINGS_NAV_GROUPS: readonly { label: string; items: readonly SettingsNavItem[] }[] = [
  {
    label: "Account",
    items: [
      { to: RoutePath.settingsProfile, label: "Profile", icon: CircleUserRound, show: () => true },
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
        show: (g) => g.ws(Permission.fieldManage) || g.any(Permission.fieldManage),
      },
      {
        // Issue link types (spec 91) — instance admins manage the catalog.
        to: RoutePath.settingsLinkTypes,
        label: "Link types",
        icon: Link2,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsLabels,
        label: "Labels",
        icon: Tags,
        show: (g) => g.ws(Permission.labelManage),
      },
      {
        to: RoutePath.settingsCycles,
        label: "Cycles",
        icon: CalendarRange,
        show: (g) => g.ws(Permission.cycleManage),
      },
      {
        to: RoutePath.settingsTimelogging,
        label: "Work categories",
        icon: Clock,
        show: (g) => g.ws(Permission.globalManage),
      },
      {
        to: RoutePath.settingsAutomations,
        label: "Automations",
        icon: Zap,
        show: (g) => g.ws(Permission.automationManage),
      },
      {
        to: RoutePath.settingsCanned,
        label: "Canned responses",
        icon: MessageSquareQuote,
        show: (g) => g.ws(Permission.cannedManage),
      },
      {
        // Spec 111 — version-control hosts and their repositories.
        to: RoutePath.settingsForgejo,
        label: "Forgejo",
        icon: GitBranch,
        show: (g) => g.ws(Permission.globalManage),
      },
    ],
  },
  {
    label: "People",
    items: [
      {
        // THE people page (spec 84; instance_role ladder since spec 86):
        // accounts + the server-wide role. Visible to global-manage holders
        // and instance admins (everything).
        to: RoutePath.settingsUsers,
        label: "Users",
        icon: UserRoundCog,
        show: (g) => g.ws(Permission.globalManage) || g.instanceAdmin,
      },
      {
        // Spec 113 — principals that authenticate by API key only.
        to: RoutePath.settingsServiceAccounts,
        label: "Service accounts",
        icon: Bot,
        show: (g) => g.ws(Permission.globalManage),
      },
      {
        to: RoutePath.settingsTeams,
        label: "Teams",
        icon: UsersRound,
        // Spec 87: a team leader holds no global team atom — `manages_teams`
        // says they own or manage one, so their page stays reachable.
        show: (g) => g.ws(Permission.teamManage) || g.managesTeams,
      },
      {
        to: RoutePath.settingsRoles,
        label: "Roles",
        icon: ShieldCheck,
        show: (g) => g.ws(Permission.roleManage),
      },
      {
        // Per-team public holidays — the admin half of the old Leave page
        // (personal absences live on Profile since the reorg).
        to: RoutePath.settingsHolidays,
        label: "Holidays",
        icon: CalendarOff,
        show: (g) => g.instanceAdmin,
      },
    ],
  },
  // Directory/LDAP settings (spec 85) deliberately have NO nav tab — they're
  // reached by clicking the LDAP/AD row on the Server Overview page (the
  // status rows ARE the navigation for deploy-level surfaces;).
  {
    label: "Server",
    items: [
      {
        // Deploy status (spec 50; status-only since spec 67).
        to: RoutePath.settingsInstance,
        label: "Overview",
        icon: Server,
        show: (g) => g.instanceAdmin,
      },
      {
        // Instance-scope product defaults (spec 67): writes are instance-scope,
        // so the tab is admin-only like the rest of the group.
        to: RoutePath.settingsGeneral,
        label: "General",
        icon: SlidersHorizontal,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsDocs,
        label: "Doc spaces",
        icon: BookOpen,
        show: (g) => g.ws(Permission.docManage),
      },
      {
        // AI provider registry + roles + feature toggles + presets (spec 101).
        to: RoutePath.settingsAi,
        label: "AI",
        icon: Sparkles,
        show: (g) => g.instanceAdmin,
      },
      {
        // Attachment storage hosts + delivery modes (spec 102).
        to: RoutePath.settingsStorage,
        label: "Storage",
        icon: HardDrive,
        show: (g) => g.instanceAdmin,
      },
      {
        // SSO providers + per-provider signup domain allowlists (spec 110).
        to: RoutePath.settingsSignIn,
        label: "Sign-in",
        icon: KeyRound,
        show: (g) => g.instanceAdmin,
      },
      {
        // Backups (spec 99) — schedules, artifacts, restore.
        to: RoutePath.settingsBackups,
        label: "Backups",
        icon: DatabaseBackup,
        show: (g) => g.instanceAdmin,
      },
      {
        // Operator monitoring: DB health, counts, worker lag.
        to: RoutePath.settingsMonitoring,
        label: "Monitoring",
        icon: Activity,
        show: (g) => g.instanceAdmin,
      },
      {
        // Jira import wizard (spec 90) — the connection speaks for a service
        // account and importing rewrites projects.
        to: RoutePath.settingsJiraImport,
        label: "Import from Jira",
        icon: DatabaseZap,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsPlugins,
        label: "Plugins",
        icon: Blocks,
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsAudit,
        label: "Audit log",
        icon: ScrollText,
        show: (g) => g.ws(Permission.globalManage),
      },
    ],
  },
];

/** Settings shell: secondary nav on the left (scope-gated), active section in the Outlet. */
export function SettingsLayout() {
  const perms = usePermissions();
  const user = useCurrentUser();
  const { data: projects } = useQuery(projectsQuery());

  const gate: NavGate = {
    // "ws" is historical shorthand — this is the GLOBAL-scope check (spec 67).
    ws: (permission) => perms.global(permission),
    any: (permission) => (projects ?? []).some((project) => perms.project(project, permission)),
    instanceAdmin: user?.instance_role === InstanceRole.admin,
    managesTeams: Boolean(user?.manages_teams),
  };
  const visibleGroups = SETTINGS_NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => item.show(gate)),
  })).filter((group) => group.items.length > 0);

  // Plugin-contributed settings pages (spec 94): federated plugins register a `settings.page` slot
  // and a `section: "settings"` nav item; they appear here alongside the builtin tabs, gated by the
  // viewer's atoms + the plugin's capability — with no edit to this array.
  const { data: manifest } = useQuery(capabilitiesQuery);
  const enabledCaps = new Set(
    (manifest?.capabilities ?? []).filter((c) => c.enabled).map((c) => c.key),
  );
  // A turned-off settings.page contribution (spec 94) also drops its nav link here.
  const disabledNav = useDisabledNavPaths();
  const pluginSettingsNav = (manifest?.nav ?? [])
    .filter((n) => n.section === "settings")
    .filter((n) => !n.capability || enabledCaps.has(n.capability))
    .filter((n) => n.requires.every((r) => perms.global(r)))
    .filter((n) => !disabledNav.has(n.path));

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-subtle px-6 py-3.5">
        <h1 className="text-sm font-semibold text-heading">Settings</h1>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Settings sections"
          className="w-48 shrink-0 overflow-y-auto border-r border-subtle p-2"
        >
          {visibleGroups.map((group, index) => (
            <section key={group.label} aria-label={group.label}>
              <h2
                className={`px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-fg-faint ${
                  index === 0 ? "pt-1" : "pt-4"
                }`}
              >
                {group.label}
              </h2>
              <ul className="flex flex-col gap-0.5">
                {group.items.map(({ to, label, icon: Icon }) => (
                  <li key={to}>
                    <Link
                      to={to}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-focus [&.active]:bg-elevated [&.active]:text-heading"
                    >
                      <Icon size={14} aria-hidden />
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {pluginSettingsNav.length > 0 && (
            <section aria-label="Extensions">
              <h2 className="px-2 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-fg-faint">
                Extensions
              </h2>
              <ul className="flex flex-col gap-0.5">
                {pluginSettingsNav.map((n) => (
                  <li key={n.key}>
                    <a
                      href={n.path}
                      data-plugin-settings-nav={n.key}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
                    >
                      <Blocks size={14} aria-hidden />
                      {n.label}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
