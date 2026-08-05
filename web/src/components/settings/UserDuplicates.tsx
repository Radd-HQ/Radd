import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { apiUserMergePath } from "../../lib/constants";
import { queryKeys, userDuplicatesQuery } from "../../lib/queries";
import { pushToast, ToastKind } from "../../lib/toast";
import {
  DuplicateKind,
  type DuplicateUserGroup,
  type User,
  type UserMergeRequest,
} from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SourceBadge } from "./UserSourceBadge";
import { ErrorText } from "../ErrorText";

const KIND_LABELS = {
  [DuplicateKind.emailLocalPart]: "Same email local part",
  [DuplicateKind.name]: "Same name",
} as const;

/** "Possible duplicates" cards (spec 84): pick a survivor, merge the rest into
 * it via the existing POST /users/{id}/merge — heuristic only, never automatic. */
export function DuplicatesSection() {
  const queryClient = useQueryClient();
  const duplicates = useQuery(userDuplicatesQuery);
  const [merging, setMerging] = useState<DuplicateUserGroup | null>(null);
  const groups = duplicates.data ?? [];
  if (duplicates.isError || (duplicates.isSuccess && groups.length === 0)) {
    return (
      <section className="mt-8">
        <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
          Possible duplicates
        </h3>
        <p className="text-xs text-fg-muted">
          {duplicates.isError ? errorMessage(duplicates.error) : "No duplicate candidates found."}
        </p>
      </section>
    );
  }
  return (
    <section className="mt-8">
      <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
        Possible duplicates
      </h3>
      <div className="grid gap-2 sm:grid-cols-2">
        {groups.map((group) => (
          <div
            key={`${group.kind}:${group.key}`}
            className="rounded-lg border border-subtle px-3.5 py-3"
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="rounded border border-amber-500/40 px-1.5 py-px text-[11px] text-amber-300">
                {KIND_LABELS[group.kind] ?? group.kind}
              </span>
              <span className="font-mono text-xs text-fg-muted">{group.key}</span>
            </div>
            <ul className="flex flex-col gap-1">
              {group.users.map((user) => (
                <li key={user.id} className="flex items-center gap-2 text-[13px]">
                  <span className="truncate text-fg">{user.email}</span>
                  <span className="truncate text-xs text-fg-muted">{user.name}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-1.5">
                    <SourceBadge source={user.source} />
                    {!user.active && <span className="text-[11px] text-red-400">inactive</span>}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-2.5">
              <Button variant="ghost" onClick={() => setMerging(group)}>
                Merge…
              </Button>
            </div>
          </div>
        ))}
      </div>
      {merging && (
        <MergeDialog
          group={merging}
          onClose={() => setMerging(null)}
          onMerged={async () => {
            setMerging(null);
            await queryClient.invalidateQueries({ queryKey: queryKeys.userDuplicates });
            await queryClient.invalidateQueries({ queryKey: ["usersAdmin"] });
            await queryClient.invalidateQueries({ queryKey: queryKeys.users });
          }}
        />
      )}
    </section>
  );
}

function MergeDialog({
  group,
  onClose,
  onMerged,
}: {
  group: DuplicateUserGroup;
  onClose: () => void;
  onMerged: () => Promise<void>;
}) {
  const [survivorId, setSurvivorId] = useState(group.users[0]?.id ?? "");
  const duplicates = group.users.filter((user) => user.id !== survivorId);

  const merge = useMutation({
    mutationFn: async () => {
      // The endpoint folds ONE duplicate into the survivor — run sequentially.
      for (const duplicate of duplicates) {
        await api.post<User>(apiUserMergePath(duplicate.id), {
          into_user_id: survivorId,
        } satisfies UserMergeRequest);
      }
    },
    onSuccess: async () => {
      pushToast(
        `Merged ${duplicates.length} account${duplicates.length === 1 ? "" : "s"}`,
        ToastKind.success,
      );
      await onMerged();
    },
  });

  return (
    <Modal title="Merge duplicate accounts" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-fg-secondary">
          Pick the account to KEEP. Everything referencing the other account
          {duplicates.length === 1 ? "" : "s"} — items, comments, worklogs, watchers,
          memberships, history — repoints to it; the duplicate
          {duplicates.length === 1 ? " is" : "s are"} signed out and deactivated (kept for audit).
        </p>
        <div className="flex flex-col gap-1" role="radiogroup" aria-label="Survivor account">
          {group.users.map((user) => (
            <label
              key={user.id}
              className="flex items-center gap-2 rounded-md border border-subtle px-2.5 py-2 text-[13px] hover:bg-surface/60 cursor-pointer"
            >
              <input
                type="radio"
                name="survivor"
                checked={survivorId === user.id}
                onChange={() => setSurvivorId(user.id)}
                className="accent-accent"
              />
              <span className="min-w-0">
                <span className="block truncate text-fg">{user.email}</span>
                <span className="block truncate text-xs text-fg-muted">{user.name}</span>
              </span>
              <span className="ml-auto shrink-0">
                <SourceBadge source={user.source} />
              </span>
            </label>
          ))}
        </div>
        {merge.isError && <ErrorText error={merge.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => merge.mutate()}
            disabled={!survivorId || duplicates.length === 0 || merge.isPending}
          >
            {merge.isPending ? "Merging…" : `Merge ${duplicates.length} into survivor`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
