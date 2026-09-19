import { fieldSettingsSummaryQuery } from "../../lib/queries/field-settings";
import { Link, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useDisabledNavPaths } from "@radd/plugin-sdk";
import {
  Activity,
  Bell,
  Blocks,
  BookOpen,
  Bot,
  CalendarRange,
  CircleUserRound,
  Clock,
  DatabaseBackup,
  DatabaseZap,
  GitBranch,
  HardDrive,
  Mail,
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
  FolderTree,
  UsersRound,
  Zap,
  type LucideIcon,
  Webhook,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { capabilitiesQuery } from "../../lib/queries";
import { InstanceRole, Permission, type PermissionValue } from "../../lib/types";

/** Predicate helpers a nav item uses to decide whether the viewer may see it. */
interface NavGate {
  fieldSettings?: boolean;
  /** The viewer holds `permission` at global scope (or is admin). */
  ws: (permission: PermissionValue) => boolean;
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
  label: string;
  icon: LucideIcon;
  show: (g: NavGate) => boolean;
  /**
   * The plugin this tab is a surface OF (RADD-928). A `core=False` plugin can be
   * disabled at runtime, which unmounts its router — so a tab left behind
   * renders a page whose every fetch 404s. Naming the owner here is what lets
   * the gate below withdraw the tab with the plugin.
   *
   * Only optional plugins need it: a core plugin cannot be disabled, so
   * omitting it means "always mounted", not "unknown". A LIST means the tab
   * is a surface of several plugins and stays while any one is mounted
   * (Version control, RADD-1262).
   */
  plugin?: string | readonly string[];
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
      {
        // Spec 118 — the kind × scope matrix and its subscriptions. Its own tab
        // rather than a Profile section: it is a grid plus a list, and a
        // preference nobody can find is a preference nobody changes.
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
        show: (g) => Boolean(g.fieldSettings) || g.ws(Permission.fieldManage) || g.any(Permission.fieldManage),
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
        show: (g) => g.ws(Permission.labelUpdate),
      },
      {
        to: RoutePath.settingsCycles,
        label: "Cycles",
        icon: CalendarRange,
        show: (g) => g.ws(Permission.cycleUpdate),
      },
      {
        // RADD-932: was "Work categories" — a tab named after one of its
        // sections. Now every instance-scope time policy, holidays included.
        to: RoutePath.settingsTimelogging,
        label: "Time logging",
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
        show: (g) => g.ws(Permission.cannedUpdate),
      },
      {
        // RADD-1262 — ONE entry for every version-control host kind (Forgejo
        // since spec 111, GitHub since RADD-1129, GitLab since RADD-1253); the
        // page holds a tab per kind. Shown while ANY of the three is mounted.
        to: RoutePath.settingsVcs,
        label: "Version control",
        icon: GitBranch,
        plugin: ["forgejo", "github", "gitlab"],
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
        show: (g) => g.ws(Permission.teamUpdate) || g.ws(Permission.teamCreate) || g.ws(Permission.teamDelete) || g.managesTeams,
      },
      {
        to: RoutePath.settingsRoles,
        label: "Roles",
        icon: ShieldCheck,
        show: (g) => g.ws(Permission.roleUpdate),
      },
    ],
  },
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
        to: RoutePath.settingsPages,
        label: "Page spaces",
        icon: BookOpen,
        plugin: "pages",
        show: (g) => g.anySpace(Permission.pageManage),
      },
      {
        // AI provider registry + roles + feature toggles + presets (spec 101).
        to: RoutePath.settingsAi,
        label: "AI",
        icon: Sparkles,
        plugin: "ai",
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
        // Mail sources/senders + the routing chain (RADD-958). Configuration
        // that used to be environment-only, which meant an operator with sops
        // rather than an admin with a form.
        to: RoutePath.settingsEmail,
        label: "Email",
        icon: Mail,
        show: (g) => g.instanceAdmin,
      },
      {
        // RADD-931: the directory is CONFIGURATION — connection, sync schedules,
        // group mirror — and was reachable only by clicking a status row on
        // Overview, a hangover from when it was status.
        to: RoutePath.settingsDirectory,
        label: "Directory",
        icon: FolderTree,
        plugin: "ldap",
        show: (g) => g.instanceAdmin,
      },
      {
        // SSO providers + per-provider signup domain allowlists (spec 110).
        to: RoutePath.settingsSignIn,
        label: "Sign-in",
        icon: KeyRound,
        plugin: "sso",
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
        // Outbound webhooks (RADD-1096): endpoints, secrets, the delivery log.
        to: RoutePath.settingsWebhooks,
        label: "Webhooks",
        icon: Webhook,
        show: (g) => g.instanceAdmin,
      },
      {
        // Operator monitoring: DB health, counts, worker lag.
        to: RoutePath.settingsMonitoring,
        label: "Monitoring",
        icon: Activity,
        plugin: "monitoring",
        show: (g) => g.instanceAdmin,
      },
      {
        to: RoutePath.settingsImportData,
        label: "Import data",
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
        // Spec 123: a project manager reads their own project's trail.
        show: (g) => g.ws(Permission.globalManage) || g.any(Permission.projectManage),
      },
    ],
  },
];

/**
 * Where a plugin's own settings tab lives, if it has one (RADD-928).
 *
 * Derived from the SAME table the sidebar renders, so the Plugins page and the
 * sidebar cannot disagree about which surface belongs to which plugin — the
 * failure mode a second hardcoded map would have. This is what makes every
 * plugin's configuration reachable FROM its plugin, per `docs/plugin-ui.md`,
 * without duplicating the page into an accordion row.
 */
export function settingsPathForPlugin(name: string): { to: string; label: string } | null {
  if (name === "jiraimport" || name === "confluenceimport") return { to: RoutePath.settingsImportData, label: "Import data" };
  for (const group of SETTINGS_NAV_GROUPS) {
    const match = group.items.find((item) =>
      typeof item.plugin === "string" ? item.plugin === name : (item.plugin ?? []).includes(name),
    );
    if (match) return { to: match.to, label: match.label };
  }
  return null;
}

/** Settings shell: secondary nav on the left (scope-gated), active section in the Outlet. */
export function SettingsLayout() {
  const perms = usePermissions();
  const user = useCurrentUser();
  const { data: manifest } = useQuery(capabilitiesQuery);

  const fields = useQuery({ ...fieldSettingsSummaryQuery(), enabled: manifest?.plugins.includes("fields") ?? false });

  const gate: NavGate = {
    fieldSettings: fields.data?.can_access,
    // "ws" is historical shorthand — this is the GLOBAL-scope check (spec 67).
    ws: (permission) => perms.global(permission),
    any: perms.anyProject,
    anySpace: perms.anySpace,
    instanceAdmin: user?.instance_role === InstanceRole.admin,
    managesTeams: Boolean(user?.manages_teams),
  };
  // RADD-928: a tab whose owning plugin is disabled is withdrawn. `plugins` is
  // the manifest's list of what is actually MOUNTED right now, so this tracks a
  // hot enable/disable without a reload — and while the manifest is in flight
  // every gated tab is hidden, which is the right way round: a tab that appears
  // a beat late reads as loading, one that vanishes reads as a bug.
  const mounted = new Set(manifest?.plugins ?? []);
  const isMounted = (item: SettingsNavItem) =>
    !item.plugin ||
    (typeof item.plugin === "string" ? mounted.has(item.plugin) : item.plugin.some((name) => mounted.has(name)));
  const visibleGroups = SETTINGS_NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => item.show(gate) && isMounted(item)),
  })).filter((group) => group.items.length > 0);

  // Plugin-contributed settings pages (spec 94): federated plugins register a `settings.page` slot
  // and a `section: "settings"` nav item; they appear here alongside the builtin tabs, gated by the
  // viewer's atoms + the plugin's capability — with no edit to this array.
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
          {pluginSettingsNav.length > 0 && (
            <section aria-label="Extensions">
              <h2 className="hidden lg:block px-2 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-fg-faint">
                Extensions
              </h2>
              <ul className="flex gap-0.5 lg:flex-col">
                {pluginSettingsNav.map((n) => (
                  <li key={n.key}>
                    <a
                      href={n.path}
                      data-plugin-settings-nav={n.key}
                      className="flex items-center whitespace-nowrap gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
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
