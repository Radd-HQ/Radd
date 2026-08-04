import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import {
  ApiPath,
  apiDashboardSharingPath,
  apiDashboardTransferPath,
} from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { Permission, type Dashboard, type ShareLevelValue } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { ViewSharingEditor, SERVER_PRIVATE, type LocalShare } from "../views/ViewSharingEditor";

/**
 * Sharing dialog for a dashboard (spec 75, on the spec-92 access framework since
 *) — the ViewModal sharing block
 * generalized: the server-wide level + per-user/team grant rows + ownership
 * transfer, saved atomically via PUT /dashboards/{id}/sharing (transfer LAST —
 * after it lands the actor may no longer hold manage rights).
 */
export function DashboardSharingModal({
  dashboard,
  onClose,
}: {
  dashboard: Dashboard;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const canBroadcast = perms.global(Permission.dashboardCreate);

  const [serverAccess, setServerAccess] = useState<ShareLevelValue | typeof SERVER_PRIVATE>(
    dashboard.global_access ?? SERVER_PRIVATE,
  );
  const [shareRows, setShareRows] = useState<LocalShare[]>(
    dashboard.shares.map((share) => ({
      kind: share.user ? "user" : share.team ? "team" : "group",
      subjectId: (share.user ?? share.team ?? share.group)?.id ?? "",
      level: share.level,
    })),
  );
  const [transferTo, setTransferTo] = useState("");

  /** Per-subject shares are access grants (spec 92 adopters): reconcile the local
   *  rows against the dashboard's current grants — add the new, delete the gone.
   *  Byte-for-byte the ViewModal idiom; only `resource_type` differs. */
  const reconcileShares = async () => {
    const current = (dashboard.shares ?? []).map((s) => ({
      id: s.id,
      key: s.user
        ? `user:${s.user.id}`
        : s.team
          ? `team:${s.team.id}`
          : `group:${s.group!.id}`,
      level: s.level as string,
    }));
    const desired = shareRows
      .filter((r) => r.subjectId)
      .map((r) => ({ key: `${r.kind}:${r.subjectId}`, level: r.level as string }));
    const desiredKeys = new Set(desired.map((d) => `${d.key}@${d.level}`));
    const currentKeys = new Set(current.map((c) => `${c.key}@${c.level}`));
    for (const c of current) {
      if (!desiredKeys.has(`${c.key}@${c.level}`)) await api.delete(`${ApiPath.grants}/${c.id}`);
    }
    for (const d of desired) {
      if (currentKeys.has(`${d.key}@${d.level}`)) continue;
      const [kind, id] = d.key.split(":");
      await api.post(ApiPath.grants, {
        resource_type: "dashboard",
        resource_id: dashboard.id,
        subject_type: kind,
        subject_id: id,
        access: d.level,
        project_ids: [],
      });
    }
  };

  const save = useMutation({
    mutationFn: async () => {
      // PUT /sharing carries only the PUBLIC level now; per-subject grants go
      // through the generic /grants API, exactly as views do.
      await reconcileShares();
      const payload = {
        global_access: serverAccess === SERVER_PRIVATE ? null : serverAccess,
      };
      let saved = await api.put<Dashboard>(apiDashboardSharingPath(dashboard.id), payload);
      if (transferTo) {
        saved = await api.post<Dashboard>(apiDashboardTransferPath(dashboard.id), {
          user_id: transferTo,
        });
      }
      return saved;
    },
    onSuccess: async () => {
      await invalidateEntities(queryClient, Entity.dashboard);
      onClose();
    },
  });

  return (
    <Modal title="Share dashboard" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <ViewSharingEditor
          serverAccess={serverAccess}
          onServerAccess={setServerAccess}
          shares={shareRows}
          onShares={setShareRows}
          canBroadcast={canBroadcast}
          transferTo={transferTo}
          onTransferTo={setTransferTo}
          noun="dashboard"
        />
        {save.isError && <p className="text-xs text-red-400">{errorMessage(save.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save sharing"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
