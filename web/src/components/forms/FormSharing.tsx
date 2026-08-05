import { useState } from "react";
import { useOnLeaveIds } from "../PersonName";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { api } from "../../lib/api";
import { apiFormSharingPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { queryKeys, teamsQuery, usersQuery } from "../../lib/queries";
import {
  type Form,
  type FormShare,
  type FormShareEntry,
  type FormSharingUpdate,
} from "../../lib/types";
import { TokenMultiSelect, type TokenOption } from "../TokenMultiSelect";
import { ErrorText } from "../ErrorText";

interface FormSharingProps {
  formId: string;
  projectId: string;
  /** The persisted share rows (`FormRead.shares`) the block starts from. */
  shares: FormShare[];
}

/**
 * Portal sharing block (spec 73) — the form builder's counterpart to the
 * public-link toggle: user/team chips whose presence means "sees the form on
 * the Portal and may submit it" (no levels; the share is the grant, no
 * item.create needed). Every add/remove PUTs the FULL list (full-replace,
 * the views-sharing idiom).
 */
export function FormSharing({ formId, projectId, shares: initial }: FormSharingProps) {
  const queryClient = useQueryClient();
  const [shares, setShares] = useState<FormShare[]>(initial);
  const users = useQuery(usersQuery);
  const teams = useQuery(teamsQuery());

  const put = useMutation({
    mutationFn: (entries: FormShareEntry[]) =>
      api.put<Form>(apiFormSharingPath(formId), { shares: entries } satisfies FormSharingUpdate),
    onSuccess: async (saved) => {
      setShares(saved.shares);
      await queryClient.invalidateQueries({ queryKey: queryKeys.forms(projectId) });
      await invalidateEntities(queryClient, Entity.form);
    },
  });

  // The token select works in "kind:id" strings; map to/from the share entries the API wants.
  const toEntry = (v: string): FormShareEntry => {
    const [kind, id] = v.split(":");
    return kind === "user" ? { user_id: id } : { team_id: id };
  };
  const value = shares.map((row) => (row.user_id ? `user:${row.user_id}` : `team:${row.team_id}`));
  const onLeaveIds = useOnLeaveIds();
  const options: TokenOption[] = [
    ...(teams.data ?? []).map((team) => ({
      value: `team:${team.id}`,
      label: team.name,
      group: "Teams",
      icon: <Users size={12} aria-hidden className="shrink-0 text-accent-text" />,
    })),
    ...(users.data ?? [])
      .filter((user) => user.active)
      .map((user) => ({ value: `user:${user.id}`, label: user.name + (onLeaveIds.has(user.id) ? " (away)" : ""), group: "People" })),
  ];

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3">
      <p className="text-[13px] text-fg">Portal sharing</p>
      <p className="text-xs text-fg-muted">
        People and teams who see this form on the Portal and can submit it — no other
        permissions needed.
      </p>

      <TokenMultiSelect
        value={value}
        onChange={(next) => put.mutate(next.map(toEntry))}
        options={options}
        disabled={put.isPending}
        placeholder="Share with a person or team…"
        ariaLabel="Portal sharing"
      />

      {put.isError && <ErrorText error={put.error} />}
    </div>
  );
}
