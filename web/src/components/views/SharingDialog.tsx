import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ErrorText, type SharingDialogProps } from "@radd/plugin-sdk";
import { emptySharingDraft, sharingEdits } from "../../lib/sharing-draft";
import type { ShareLevelValue } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { ViewSharingEditor, SERVER_PRIVATE } from "./ViewSharingEditor";

/**
 * The SDK's SharingDialog, as the shell provides it (RADD-1393): the house sharing editor over a
 * LOCAL draft — server-wide access, grant changes, ownership transfer — committed by the owning
 * plugin's `onSave` in one owner-authorized transaction, with the expectations it started from.
 */
export function SharingDialog({ title, resourceType, resourceId, ownerId, globalAccess, canBroadcast, onSave, onClose }: SharingDialogProps) {
  const [serverAccess, setServerAccess] = useState<ShareLevelValue | typeof SERVER_PRIVATE>(
    (globalAccess as ShareLevelValue | null) ?? SERVER_PRIVATE,
  );
  const [draft, setDraft] = useState(emptySharingDraft);
  const [base] = useState({ owner: ownerId, access: globalAccess });
  const [transferTo, setTransferTo] = useState("");
  const save = useMutation({
    mutationFn: () => onSave({
      sharing: { global_access: serverAccess === SERVER_PRIVATE ? null : serverAccess },
      grants: sharingEdits(draft), transfer_to: transferTo || undefined,
      expected_owner_id: base.owner, expected_global_access: base.access,
    }),
    onSuccess: onClose,
  });
  return (
    <Modal title={title} onClose={() => { if (!save.isPending) onClose(); }}>
      <fieldset disabled={save.isPending} className="flex min-w-0 flex-col gap-4">
        <ViewSharingEditor serverAccess={serverAccess} onServerAccess={setServerAccess} shares={[]} onShares={() => {}}
          existing={{ id: resourceId, draft, onChange: setDraft }} canBroadcast={canBroadcast}
          transferTo={transferTo} onTransferTo={setTransferTo} noun={resourceType} />
        {save.isError && <div role="alert"><ErrorText error={save.error} /></div>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save sharing"}</Button>
        </div>
      </fieldset>
    </Modal>
  );
}
