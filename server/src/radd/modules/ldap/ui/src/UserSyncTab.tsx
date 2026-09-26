import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSync, UserRoundPlus } from "lucide-react";
import { api, Button, ErrorText, ScopedSettings, toast, ToastKind } from "@radd/plugin-sdk";
import { ImportUsersDialog } from "./ImportUsersDialog";
import { refreshAfterImport, syncStatusQuery } from "./queries";
import { lastRunLine, sectionHeadClasses } from "./sync";
import { AffectedKeys, LdapPath, ldapKeys, type UserSyncResult } from "./types";

/** The user-sync tab: the cascade-backed search base + toggles, Sync now, and the AD import. */
export function UserSyncTab({ directoryReady }: { directoryReady: boolean }) {
  const queryClient = useQueryClient();
  const syncStatus = useQuery(syncStatusQuery);
  const [importing, setImporting] = useState(false);

  const syncNow = useMutation({
    mutationFn: () => api.post<UserSyncResult>(LdapPath.syncUsers, {}),
    onSuccess: async (result) => {
      toast(
        `User sync: ${result.provisioned} provisioned · ${result.updated} updated · ${result.deactivated} deactivated`,
        result.errors.length > 0 ? ToastKind.error : ToastKind.success,
      );
      await refreshAfterImport(queryClient, ldapKeys.syncStatus, AffectedKeys.usersAdmin, AffectedKeys.users);
    },
  });

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className={`${sectionHeadClasses} mb-0`}>User sync</h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => setImporting(true)} disabled={!directoryReady}>
            <UserRoundPlus size={14} aria-hidden />
            Import users…
          </Button>
          <Button onClick={() => syncNow.mutate()} disabled={!directoryReady || syncNow.isPending}>
            <FolderSync size={14} aria-hidden />
            {syncNow.isPending ? "Syncing…" : "Sync now"}
          </Button>
        </div>
      </div>
      {!directoryReady && (
        <p className="mb-3 text-xs text-status-warning-ink">
          No bind account is configured — directory searches and sync are unavailable until the
          Connection tab (or the deploy&apos;s RADD_LDAP_* env) sets one.
        </p>
      )}
      <ScopedSettings scope="instance" section="directory.usersync" disabled={!directoryReady} />
      {syncNow.isError && <ErrorText className="mt-2" error={syncNow.error} />}
      <p className="mt-2 text-xs text-fg-muted" data-user-sync-last-run>
        {syncStatus.isPending ? "Loading last run…" : lastRunLine(syncStatus.data?.user_sync)}
      </p>
      {importing && <ImportUsersDialog onClose={() => setImporting(false)} />}
    </section>
  );
}
