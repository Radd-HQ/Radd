import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, FolderSync, Lock, UserRoundPlus } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath, RoutePath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { instanceStatusQuery, ldapSyncStatusQuery, queryKeys } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import {
  InstanceRole,
  SettingScope,
  type DirectorySyncState,
  type UserSyncResult,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Spinner";
import { QueryError } from "../../components/QueryError";
import { DirectoryGroupsSection } from "../../components/settings/DirectoryGroupsSection";
import { MirroredGroupsSection } from "../../components/settings/MirroredGroupsSection";
import { ImportUsersDialog } from "../../components/settings/DirectoryImportDialogs";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { StatusPill } from "./instance";
import { ErrorText } from "../../components/ErrorText";
import { formatDateTime } from "../../lib/dates";

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/** One sync's last-run line: timestamp + the numeric summary + error count. */
function lastRunLine(state: DirectorySyncState | null | undefined): string {
  if (!state) return "Never ran.";
  const counts = Object.entries(state.last_result)
    .filter((entry): entry is [string, number] => typeof entry[1] === "number")
    .map(([key, value]) => `${value} ${key.replace(/_/g, " ")}`)
    .join(" · ");
  const errors = Array.isArray(state.last_result.errors) ? state.last_result.errors.length : 0;
  const errorSuffix = errors > 0 ? ` · ${errors} error${errors === 1 ? "" : "s"}` : "";
  return `Last run ${formatDateTime(state.last_run_at)}: ${counts}${errorSuffix}`;
}

/**
 * Consolidated Directory (LDAP/AD) settings (spec 85) — instance admins only:
 * deploy status, the automatic user sync (cascade-backed base + toggles,
 * "Sync now", last-run line), and the group browser with import/link/unlink.
 * The Users page keeps ACCOUNT administration; the per-team picker on Teams
 * stays for contextual linking.
 */
export function DirectorySettingsPage() {
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;
  const queryClient = useQueryClient();
  const status = useQuery({ ...instanceStatusQuery, enabled: isInstanceAdmin, retry: false });
  const syncStatus = useQuery({ ...ldapSyncStatusQuery, enabled: isInstanceAdmin });
  const directoryReady = Boolean(status.data?.ldap_bind_account);
  const [importingUsers, setImportingUsers] = useState(false);

  const syncNow = useMutation({
    mutationFn: () => api.post<UserSyncResult>(ApiPath.ldapSyncUsers, {}),
    onSuccess: async (result) => {
      pushToast(
        `User sync: ${result.provisioned} provisioned · ${result.updated} updated · ${result.deactivated} deactivated`,
        result.errors.length > 0 ? ToastKind.error : ToastKind.success,
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.ldapSyncStatus });
      await queryClient.invalidateQueries({ queryKey: ["usersAdmin"] });
      await queryClient.invalidateQueries({ queryKey: queryKeys.users });
    },
  });
  const syncGroupsNow = useMutation({
    mutationFn: () =>
      api.post<{ groups: number; added: number; removed: number; errors: string[] }>(
        ApiPath.ldapSyncGroups,
        {},
      ),
    onSuccess: async (result) => {
      pushToast(
        `Group sync: ${result.groups} groups · ${result.added} joined · ${result.removed} left`,
        result.errors.length > 0 ? ToastKind.error : ToastKind.success,
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.ldapSyncStatus });
      await queryClient.invalidateQueries({ queryKey: queryKeys.teams });
    },
  });

  return (
    <SettingsPage history={{ entities: ["group", "user", "scoped_setting"] }}
      title="Directory"
      description="Your LDAP or Active Directory: the connection, automatic user sync from a search base, and which directory groups link to teams."
    >
      {/* Reached via the Server page's LDAP/AD status row — no nav tab. */}
      <Link
        to={RoutePath.settingsInstance}
        className="-mt-2 mb-2 inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg"
      >
        <ArrowLeft size={12} aria-hidden />
        Server settings
      </Link>
      {!isInstanceAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage the directory." />
      ) : (
        <div className="flex flex-col gap-8">
          <section>
            <h2 className={sectionHeadClasses}>Status</h2>
            {status.isPending ? (
              <Spinner label="Loading status…" />
            ) : status.isError ? (
              <QueryError label="status" error={status.error} />
            ) : (
              <div className="grid gap-2 sm:grid-cols-3">
                <StatusPill label="LDAP / AD sign-in" on={status.data.ldap_enabled} />
                <StatusPill label="Bind (service) account" on={status.data.ldap_bind_account} />
                <StatusPill label="Background workers" on={status.data.workers_enabled} />
              </div>
            )}
          </section>

          <section>
            <h2 className={sectionHeadClasses}>Connection</h2>
            {/* RADD-846: the connection is editable here — deliberately NOT
                gated on directoryReady, since configuring it is exactly what
                an unready instance needs. Env (RADD_LDAP_*) stays the seed:
                each field's default is the deploy value, a saved override
                beats it, and clearing the override falls back. Applies on the
                next request — no restart. */}
            <div className="mb-3">
              <ScopedSettingsEditor
                scope={SettingScope.instance}
                section="directory.connection"
              />
            </div>
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className={`${sectionHeadClasses} mb-0`}>User sync</h2>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  onClick={() => setImportingUsers(true)}
                  disabled={!directoryReady}
                >
                  <UserRoundPlus size={14} aria-hidden />
                  Import users…
                </Button>
                <Button
                  onClick={() => syncNow.mutate()}
                  disabled={!directoryReady || syncNow.isPending}
                >
                  <FolderSync size={14} aria-hidden />
                  {syncNow.isPending ? "Syncing…" : "Sync now"}
                </Button>
              </div>
            </div>
            {!directoryReady && (
              <p className="mb-3 text-xs text-amber-400/90">
                No bind account is configured — directory searches and sync are unavailable
                until the Connection section above (or the deploy&apos;s RADD_LDAP_* env)
                sets one.
              </p>
            )}
            <ScopedSettingsEditor
              scope={SettingScope.instance}
              section="directory.usersync"
              disabled={!directoryReady}
            />
            {syncNow.isError && (
              <ErrorText className="mt-2" error={syncNow.error} />
            )}
            <p className="mt-2 text-xs text-fg-muted">
              {syncStatus.isPending ? "Loading last run…" : lastRunLine(syncStatus.data?.user_sync)}
            </p>
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className={`${sectionHeadClasses} mb-0`}>Groups</h2>
              {/* RADD-848: force the reconcile after a known AD change — the
                  revocation happens on this click, not within the interval. */}
              <Button
                onClick={() => syncGroupsNow.mutate()}
                disabled={!directoryReady || syncGroupsNow.isPending}
              >
                <FolderSync size={14} aria-hidden />
                {syncGroupsNow.isPending ? "Syncing…" : "Sync groups now"}
              </Button>
            </div>
            <div className="mb-3">
              <ScopedSettingsEditor
                scope={SettingScope.instance}
                section="directory.groups"
                disabled={!directoryReady}
              />
            </div>
            <DirectoryGroupsSection directoryReady={directoryReady} />
            {/* RADD-931: what Radd has actually mirrored, and — the control the
                deleted Settings → Groups tab never had — who it grants roles to. */}
            <MirroredGroupsSection directoryReady={directoryReady} />
            <p className="mt-2 text-xs text-fg-muted">
              {syncStatus.isPending
                ? "Loading last run…"
                : `Linked-team reconcile — ${lastRunLine(syncStatus.data?.group_sync)}`}
            </p>
          </section>
        </div>
      )}
      {importingUsers && <ImportUsersDialog onClose={() => setImportingUsers(false)} />}
    </SettingsPage>
  );
}
