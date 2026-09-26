/**
 * A project's settings sections (spec 50): the host's own tabs plus the pages enabled plugins
 * contribute (RADD-1396 — a manifest `NavItemSpec(section="project_settings", path=<segment>)`
 * whose page is a `project.settings.page` contribution matched on that segment). One list feeds
 * the settings sub-nav, its index redirect and the sidebar's Settings link, so they cannot
 * disagree about whether a person has anything to manage in a project.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ClipboardList,
  Clock,
  LayoutList,
  Shapes,
  SlidersHorizontal,
  UserRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { SlotId, useDisabledMatches } from "@radd/plugin-sdk";
import { RoutePath } from "./constants";
import { usePermissions, type PermissionChecks } from "./hooks";
import { iconOrFallback } from "./icons";
import { capabilitiesQuery } from "./queries";
import { Permission } from "./types";
import type { Project } from "@radd-plugin-ui/projects/types";

/** Where a contributed nav entry lists itself when it is a project-settings page. */
const PROJECT_SETTINGS_NAV_SECTION = "project_settings";

interface ProjectSettingsEntry {
  /** A route template (`/p/$projectKey/settings/…`); links pass `{ projectKey }`. */
  to: string;
  label: string;
  icon: LucideIcon;
  order: number;
  /** The owning plugin, for a contributed page. */
  plugin?: string;
}

type Gate = (perms: PermissionChecks, project: Project) => boolean;

/** Every tab gates on a per-project permission. */
const HOST_SECTIONS: readonly (Omit<ProjectSettingsEntry, "order"> & { show: Gate })[] = [
  {
    to: RoutePath.projectSettingsGeneral,
    label: "General",
    icon: SlidersHorizontal,
    show: (perms, project) => perms.project(project, Permission.projectManage),
  },
  {
    to: RoutePath.projectSettingsWorkflow,
    label: "Workflow",
    icon: Workflow,
    show: (perms, project) => perms.project(project, Permission.stateManage),
  },
  {
    to: RoutePath.projectSettingsTypes,
    label: "Issue types",
    icon: Shapes,
    show: (perms, project) => perms.project(project, Permission.projectManage),
  },
  {
    to: RoutePath.projectSettingsScreens,
    label: "Screens",
    icon: LayoutList,
    show: (perms, project) => perms.project(project, Permission.projectManage),
  },
  {
    to: RoutePath.projectSettingsAccess,
    label: "Access",
    icon: UserRound,
    // RADD-826 (D3): delegated access management — member.create in THIS
    // project opens the screen; revoke-only and global role managers also belong here.
    show: (perms, project) => perms.global(Permission.roleUpdate) || perms.project(project, Permission.memberCreate) || perms.project(project, Permission.memberDelete),
  },
  {
    to: RoutePath.projectSettingsForms,
    label: "Forms",
    icon: ClipboardList,
    show: (perms, project) => perms.project(project, Permission.formManage),
  },
  {
    to: RoutePath.projectSettingsTimelogging,
    label: "Time logging",
    icon: Clock,
    show: (perms, project) => perms.project(project, Permission.projectManage),
  },
];

/** The sections `project` shows this person, in order — host tabs first by position (×10), and
 *  contributed pages at their declared `order`. A contributed entry's `requires` atoms are checked
 *  IN the project; its capability must be on, and a turned-off page contribution leaves it out. */
export function useProjectSettingsNav(project: Project | null | undefined): ProjectSettingsEntry[] {
  const perms = usePermissions();
  const { data: manifest } = useQuery(capabilitiesQuery);
  const disabled = useDisabledMatches(SlotId.projectSettingsPage);
  return useMemo(() => {
    if (!project) return [];
    const enabledCaps = new Set(
      (manifest?.capabilities ?? []).filter((capability) => capability.enabled).map((capability) => capability.key),
    );
    const own = HOST_SECTIONS.map(({ show, ...entry }, index) => ({ ...entry, show, order: index * 10 }))
      .filter((entry) => entry.show(perms, project))
      .map(({ show: _show, ...entry }) => entry);
    const contributed = (manifest?.nav ?? [])
      .filter((nav) => nav.section === PROJECT_SETTINGS_NAV_SECTION)
      .filter((nav) => !nav.capability || enabledCaps.has(nav.capability))
      .filter((nav) => nav.requires.every((atom) => perms.project(project, atom)))
      .filter((nav) => !disabled.has(nav.path))
      .map((nav) => ({
        to: `${RoutePath.projectSettings}/${nav.path}`,
        label: nav.label,
        icon: iconOrFallback(nav.icon),
        order: nav.order,
        plugin: nav.plugin,
      }));
    return [...own, ...contributed].sort((a, b) => a.order - b.order);
  }, [project, perms, manifest, disabled]);
}
