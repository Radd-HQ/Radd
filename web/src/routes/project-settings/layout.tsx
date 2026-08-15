import { Link, Outlet, useParams } from "@tanstack/react-router";
import {
  ClipboardList,
  Clock,
  LayoutList,
  Rocket,
  Shapes,
  SlidersHorizontal,
  Timer,
  UserRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { useProjectByKey, usePermissions, type PermissionChecks } from "../../lib/hooks";
import { PROJECT_HOMED_SECTIONS, Permission, SettingScope, type Project } from "../../lib/types";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { Spinner } from "../../components/Spinner";
import { IssueTypesSettingsPage } from "./issue-types";
import { ScreensSettingsPage } from "./screens";
import { ProjectAccessSettingsPage } from "./projects";
import { StatesSettingsPage } from "./states";
import { ReleasesSettingsPage } from "./releases";
import { FormsSettingsPage } from "./forms";
import { ProjectTimeloggingSettingsPage } from "./timelogging";
import { ProjectSlaSettingsPage } from "./sla";

/** Resolve the URL's `$projectKey` to its project (shared by layout + wrappers). */
function useUrlProject() {
  const { projectKey = "" } = useParams({ strict: false });
  return { projectKey, ...useProjectByKey(projectKey) };
}

const navLinkClasses =
  "flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-elevated " +
  "hover:text-heading focus-visible:outline-2 focus-visible:outline-focus " +
  "[&.active]:bg-elevated [&.active]:text-heading";

/**
 * Project-settings sub-nav (spec 50). Each tab's `show` predicate gets the
 * permission checks + the URL's project; a tab is hidden when the viewer can't
 * manage it. Most tabs gate on a per-project permission — SLAs (spec 67) keeps
 * its global-scope `sla.manage` gate (policies are admin config). The
 * project key/name is shown in the header; an unresolved key renders empty.
 */
const PROJECT_SETTINGS_NAV: readonly {
  to: string;
  label: string;
  icon: LucideIcon;
  show: (perms: PermissionChecks, project: Project) => boolean;
}[] = [
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
    // project opens the screen; project.manage implies it.
    show: (perms, project) => perms.project(project, Permission.memberCreate),
  },
  {
    to: RoutePath.projectSettingsReleases,
    label: "Releases",
    icon: Rocket,
    show: (perms, project) => perms.project(project, Permission.releaseUpdate),
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
  {
    to: RoutePath.projectSettingsSla,
    label: "SLAs",
    icon: Timer,
    show: (perms) => perms.global(Permission.slaUpdate),
  },
];

export function ProjectSettingsLayout() {
  const { projectKey, project } = useUrlProject();
  const perms = usePermissions();

  if (project === undefined) {
    return <Spinner label="Loading settings…" />;
  }

  if (project === null) {
    return (
      <div className="flex h-full flex-col">
        <header className="border-b border-subtle px-6 py-3.5">
          <h1 className="text-sm font-semibold text-heading">Project settings</h1>
        </header>
        <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>
      </div>
    );
  }

  const visible = PROJECT_SETTINGS_NAV.filter((item) => item.show(perms, project));

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-subtle px-6 py-3.5">
        <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">
          {project.key}
        </span>
        <h1 className="text-sm font-semibold text-heading">{project.name}</h1>
        <span className="text-xs text-fg-muted">Project settings</span>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Project settings sections"
          className="w-44 shrink-0 border-r border-subtle p-2"
        >
          <ul className="flex flex-col gap-0.5">
            {visible.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <Link to={to} params={{ projectKey }} className={navLinkClasses}>
                  <Icon size={14} aria-hidden />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

/**
 * Section wrappers: resolve `$projectKey`→project and pass its id to the reused
 * settings page, which reads the project from that id (no in-page picker).
 */
export function ProjectGeneralSettings() {
  const { project } = useUrlProject();
  return (
    <SettingsPage
      title="General"
      description="Project overrides for the cascaded settings that don't belong to a tab of their own. Each falls back to the instance default (Settings → General)."
    >
      {project ? (
        // RADD-930: the REMAINDER, not everything. The release states, the
        // working week and the CSAT opt-in now declare their own tabs, and the
        // enforcement mode declares Workflow — which also retires the
        // hand-written `key !== WORKFLOW_TRANSITION_MODE_KEY` exclude that used
        // to keep a second, free-text copy of that dropdown off this page.
        <ScopedSettingsEditor
          scope={SettingScope.project}
          scopeId={project.id}
          homed={PROJECT_HOMED_SECTIONS}
          emptyLabel="Every cascaded setting for this project lives on one of the tabs beside this one."
        />
      ) : null}
    </SettingsPage>
  );
}

export function ProjectAccessSettings() {
  const { project } = useUrlProject();
  return <ProjectAccessSettingsPage projectId={project?.id} />;
}

export function ProjectWorkflowSettings() {
  const { project } = useUrlProject();
  return <StatesSettingsPage projectId={project?.id} />;
}

export function ProjectTypesSettings() {
  const { project } = useUrlProject();
  return <IssueTypesSettingsPage projectId={project?.id} />;
}

export function ProjectScreensSettings() {
  const { project } = useUrlProject();
  return <ScreensSettingsPage projectId={project?.id} />;
}

export function ProjectReleasesSettings() {
  const { project } = useUrlProject();
  return <ReleasesSettingsPage projectId={project?.id} />;
}

export function ProjectFormsSettings() {
  const { project } = useUrlProject();
  return <FormsSettingsPage projectId={project?.id} />;
}

export function ProjectTimeloggingSettings() {
  const { project } = useUrlProject();
  return <ProjectTimeloggingSettingsPage projectId={project?.id} />;
}

export function ProjectSlaSettings() {
  const { project } = useUrlProject();
  return <ProjectSlaSettingsPage projectId={project?.id} />;
}
