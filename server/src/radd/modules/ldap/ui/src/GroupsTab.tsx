import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSync } from "lucide-react";
import { api, Button, ErrorText, ScopedSettings, toast, ToastKind } from "@radd/plugin-sdk";
import { DirectoryGroupsSection } from "./DirectoryGroupsSection";
import { MirroredGroupsSection } from "./MirroredGroupsSection";
import { refreshAfterImport, syncStatusQuery } from "./queries";
import { lastRunLine, sectionHeadClasses } from "./sync";
import { AffectedKeys, LdapPath, ldapKeys, type GroupSyncResult } from "./types";

/** The groups tab: the group base + interval, the live browse, and what Radd has mirrored. */
export function GroupsTab({ directoryReady }: { directoryReady: boolean }) {
  const queryClient = useQueryClient();
  const syncStatus = useQuery(syncStatusQuery);
  const syncGroupsNow = useMutation({
    mutationFn: () => api.post<GroupSyncResult>(LdapPath.syncGroups, {}),
    onSuccess: async (result) => {
      toast(
        `Group sync: ${result.groups} groups · ${result.added} joined · ${result.removed} left`,
        result.errors.length > 0 ? ToastKind.error : ToastKind.success,
      );
      await refreshAfterImport(queryClient, ldapKeys.syncStatus, AffectedKeys.teams, AffectedKeys.groups);
    },
  });

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className={`${sectionHeadClasses} mb-0`}>Groups</h2>
        {/* RADD-848: force the reconcile after a known AD change — the revocation happens on this
            click, not within the interval. */}
        <Button onClick={() => syncGroupsNow.mutate()} disabled={!directoryReady || syncGroupsNow.isPending}>
          <FolderSync size={14} aria-hidden />
          {syncGroupsNow.isPending ? "Syncing…" : "Sync groups now"}
        </Button>
      </div>
      {syncGroupsNow.isError && <ErrorText className="mb-2" error={syncGroupsNow.error} />}
      <div className="mb-3">
        <ScopedSettings scope="instance" section="directory.groups" disabled={!directoryReady} />
      </div>
      <DirectoryGroupsSection directoryReady={directoryReady} />
      {/* RADD-931: what Radd has actually mirrored, and who it grants roles to. */}
      <MirroredGroupsSection directoryReady={directoryReady} />
      <p className="mt-2 text-xs text-fg-muted" data-group-sync-last-run>
        {syncStatus.isPending ? "Loading last run…" : `Linked-team reconcile — ${lastRunLine(syncStatus.data?.group_sync)}`}
      </p>
    </section>
  );
}
