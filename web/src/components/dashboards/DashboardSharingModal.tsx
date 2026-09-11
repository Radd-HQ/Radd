import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { apiDashboardPath } from "../../lib/constants";
import { emptySharingDraft, sharingEdits, type SharedSave } from "../../lib/sharing-draft";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { Permission, type Dashboard, type ShareLevelValue } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { ViewSharingEditor, SERVER_PRIVATE } from "../views/ViewSharingEditor";
import { ErrorText } from "../ErrorText";

/** Local sharing draft committed by one owner-authorized transaction. */
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
  const [sharingDraft, setSharingDraft] = useState(emptySharingDraft);
  const [sharingBase] = useState({ owner: dashboard.owner_id, access: dashboard.global_access });
  const [transferTo, setTransferTo] = useState("");

  const save = useMutation({
    mutationFn: () => api.post<Dashboard>(`${apiDashboardPath(dashboard.id)}/save`, {
      sharing: { global_access: serverAccess === SERVER_PRIVATE ? null : serverAccess },
      grants: sharingEdits(sharingDraft), transfer_to: transferTo || undefined,
      expected_owner_id: sharingBase.owner, expected_global_access: sharingBase.access,
    } satisfies SharedSave),
    onSuccess: async () => {
      await invalidateEntities(queryClient, Entity.dashboard, Entity.accessGrant);
      onClose();
    },
  });

  return (
    <Modal title="Share dashboard" onClose={() => { if (!save.isPending) onClose(); }}>
      <fieldset disabled={save.isPending} className="flex min-w-0 flex-col gap-4">
        <ViewSharingEditor
          serverAccess={serverAccess}
          onServerAccess={setServerAccess}
          shares={[]}
          onShares={() => {}}
          existing={{ id: dashboard.id, draft: sharingDraft, onChange: setSharingDraft }}
          canBroadcast={canBroadcast}
          transferTo={transferTo}
          onTransferTo={setTransferTo}
          noun="dashboard"
        />
        {save.isError && <div role="alert"><ErrorText error={save.error} /></div>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save sharing"}
          </Button>
        </div>
      </fieldset>
    </Modal>
  );
}
