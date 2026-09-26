import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Button, ErrorText, Modal, OptionSelect, toast, ToastKind } from "@radd/plugin-sdk";
import { refreshAfterImport } from "./queries";
import { AffectedKeys, LdapPath } from "./types";

/** RADD-829: put an already-mirrored group on an EXISTING team as a member. The team choice is
 *  the Teams plugin's own directory (`teams/directory`, id-valued). */
export function AddGroupToTeamDialog({ cn, groupId, onClose }: { cn: string; groupId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [teamId, setTeamId] = useState("");
  const add = useMutation({
    mutationFn: () => api.post<unknown>(LdapPath.teamGroups(teamId), { group_id: groupId }),
    onSuccess: async () => {
      toast(`Added ${cn} to the team`, ToastKind.success);
      await refreshAfterImport(queryClient, AffectedKeys.teams, AffectedKeys.teamMembers);
      onClose();
    },
  });

  return (
    <Modal title={`Add ${cn} to a team`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-fg-muted">
          The group's people (nested groups included) will count as members of the team; the
          directory sync keeps them current.
        </p>
        <OptionSelect resource="teams/directory" label="Team" value={teamId} onChange={setTeamId} />
        {add.isError && <ErrorText error={add.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => add.mutate()} disabled={!teamId || add.isPending}>
            {add.isPending ? "Adding…" : "Add group"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
