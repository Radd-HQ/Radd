import { Link, Navigate, Outlet, useParams } from "@tanstack/react-router";
import {
  ClipboardList,
  Clock,
  LayoutList,
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
import { ProjectIdentityCard } from "../../components/projects/ProjectIdentityCard";
import { DeleteProjectCard } from "../../components/projects/DeleteProjectCard";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { Spinner } from "../../components/Spinner";
import { IssueTypesSettingsPage } from "./issue-types";
import { ScreensSettingsPage } from "./screens";
import { ProjectAccessSettingsPage } from "./projects";
import { StatesSettingsPage } from "./states";
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
 * manage it. Every tab gates on a per-project permission — SLAs too, since
 * RADD-1303 (policies belong to the project). The
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
  {
    to: RoutePath.projectSettingsSla,
    label: "SLAs",
    icon: Timer,
    // RADD-1303: a project's Manager manages its SLAs.
    show: (perms, project) => perms.project(project, Permission.slaUpdate),
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
      <header className="flex flex-wrap items-center gap-3 border-b border-subtle px-6 py-3.5">
        <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">
          {project.key}
        </span>
        <h1 className="text-sm font-semibold text-heading">{project.name}</h1>
        <span className="text-xs text-fg-muted">Project settings</span>
        {project.description && (
          <p data-project-description className="basis-full truncate text-xs text-fg-secondary">
            {project.description}
          </p>
        )}
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <nav
          aria-label="Project settings sections"
          className="w-full shrink-0 overflow-x-auto border-b border-subtle p-2 lg:w-44 lg:border-b-0 lg:border-r"
        >
          <ul className="flex whitespace-nowrap gap-0.5 lg:flex-col">
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

/** Land on an available section, including access-only delegates. */
export function ProjectSettingsIndex() {
  const { projectKey, project } = useUrlProject();
  const perms = usePermissions();
  if (!project) return <Spinner label="Loading settings…" />;
  const first = PROJECT_SETTINGS_NAV.find(item => item.show(perms, project));
  return first ? <Navigate to={first.to} params={{ projectKey }} replace />
    : <p className="p-4 text-sm text-fg-muted">You have no project settings to manage here.</p>;
}

/**
 * Section wrappers: resolve `$projectKey`→project and pass its id to the reused
 * settings page, which reads the project from that id (no in-page picker).
 */
export function ProjectGeneralSettings() {
  const { project } = useUrlProject();
  const perms = usePermissions();
  return (
    <SettingsPage
      title="General"
      description="The project's name and description, then its overrides for the cascaded settings that don't belong to a tab of their own. Each of those falls back to the instance default (Settings → General)."
    >
      {project ? (
        <div className="flex flex-col gap-6">
          {/* RADD-1009: keyed on the project so a route change resets the drafts. */}
          <ProjectIdentityCard
            key={project.id}
            project={project}
            canManage={perms.project(project, Permission.projectManage)}
          />
          {/* RADD-930: the REMAINDER, not everything. The release states, the
              working week and the CSAT opt-in now declare their own tabs, and the
              enforcement mode declares Workflow — which also retires the
              hand-written `key !== WORKFLOW_TRANSITION_MODE_KEY` exclude that used
              to keep a second, free-text copy of that dropdown off this page. */}
          <ScopedSettingsEditor
            scope={SettingScope.project}
            scopeId={project.id}
            homed={PROJECT_HOMED_SECTIONS}
            emptyLabel="Every cascaded setting for this project lives on one of the tabs beside this one."
          />
          {/* RADD-1174: the GLOBAL atom, so a delegated project admin never sees it. */}
          {perms.global(Permission.projectDelete) && <DeleteProjectCard project={project} />}
        </div>
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

/** RADD-1290: releases are a project page now; the old settings address forwards. */
export function ProjectReleasesSettings() {
  const { projectKey = "" } = useParams({ strict: false });
  return <Navigate to={RoutePath.projectReleases} params={{ projectKey }} replace />;
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
