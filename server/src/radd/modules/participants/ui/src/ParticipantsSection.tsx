import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Avatar, Select, tokens, type Item } from "@radd/plugin-sdk";
import { Users, X } from "lucide-react";

/**
 * Participants (spec 72) as a FEDERATED remote (spec 94): users + whole TEAMS an item is shared
 * with — the requester loop. Extracted from the host's IssueProperties into the `participants`
 * plugin's own UI bundle; the host renders it only through the `issue.panel.section` slot. Styled
 * from `@radd/plugin-sdk` tokens/primitives — no hardcoded color, so it tracks the host theme.
 */

interface Ref {
  id: string;
  name: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
}
interface ParticipantRow {
  id: string;
  user: Ref | null;
  team: { id: string; name: string } | null;
  added_by: { name: string } | null;
}
interface ParticipantsData {
  rows: ParticipantRow[];
  can_manage: boolean;
}
interface UserLite extends Ref {
  active: boolean;
}
interface TeamLite {
  id: string;
  name: string;
}

const participantsKey = (itemId: string) => ["radd-remote", "participants", itemId] as const;

export function ParticipantsSection({ item }: { item: Item }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: participantsKey(item.id),
    queryFn: () => api.get<ParticipantsData>(`/items/${item.id}/participants`),
  });
  const canManage = Boolean(data?.can_manage);
  const users = useQuery({
    queryKey: ["radd-remote", "participants-users"],
    queryFn: () => api.get<UserLite[]>("/users"),
    enabled: canManage,
  });
  const teams = useQuery({
    queryKey: ["radd-remote", "participants-teams"],
    queryFn: () => api.get<TeamLite[]>("/teams"),
    enabled: canManage,
  });
  const leave = useQuery({
    queryKey: ["radd-remote", "leave-current"],
    queryFn: () => api.get<{ user_id: string }[]>("/leave/current"),
    staleTime: 5 * 60_000,
  });
  const onLeaveIds = new Set((leave.data ?? []).map((entry) => entry.user_id));
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: participantsKey(item.id) });
  const onError = (e: unknown) => setError(e instanceof Error ? e.message : "Something went wrong");
  const add = useMutation({
    mutationFn: (subject: { user_id?: string; team_id?: string }) =>
      api.post<ParticipantRow>(`/items/${item.id}/participants`, subject),
    onError,
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (participantId: string) =>
      api.delete<void>(`/items/${item.id}/participants/${participantId}`),
    onError,
    onSettled: refresh,
  });

  if (!data || (data.rows.length === 0 && !data.can_manage)) return null;

  const participantUserIds = new Set(data.rows.flatMap((r) => (r.user ? [r.user.id] : [])));
  const participantTeamIds = new Set(data.rows.flatMap((r) => (r.team ? [r.team.id] : [])));
  const busy = add.isPending || remove.isPending;

  const chip: React.CSSProperties = {
    display: "inline-flex",
    maxWidth: "100%",
    alignItems: "center",
    gap: 6,
    borderRadius: tokens.radius,
    border: `1px solid ${tokens.borderStrong}`,
    background: tokens.panel,
    padding: "2px 6px 2px 4px",
    fontSize: 12,
    color: tokens.text,
  };
  const removeBtn: React.CSSProperties = {
    flexShrink: 0,
    background: "none",
    border: "none",
    cursor: "pointer",
    color: tokens.textFaint,
    fontSize: 11,
  };

  return (
    <div style={{ padding: "12px 16px" }} data-plugin-section="participants">
      <p
        style={{
          marginBottom: 6,
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12,
          fontWeight: 500,
          color: tokens.textMuted,
        }}
      >
        <Users size={12} aria-hidden />
        Participants
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
        {data.rows.map((row) => (
          <span key={row.id} style={chip} title={row.added_by ? `Added by ${row.added_by.name}` : undefined}>
            {row.user ? (
              <>
                <Avatar user={row.user} size="xs" />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {row.user.name}
                  {onLeaveIds.has(row.user.id) ? " (away)" : ""}
                </span>
              </>
            ) : row.team ? (
              <>
                <Users size={12} aria-hidden style={{ color: tokens.accent, marginLeft: 2 }} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {row.team.name}
                </span>
              </>
            ) : null}
            {canManage && (
              <button
                type="button"
                onClick={() => remove.mutate(row.id)}
                disabled={busy}
                aria-label="Remove participant"
                style={removeBtn}
              >
                <X size={11} aria-hidden />
              </button>
            )}
          </span>
        ))}
        {canManage && (
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            aria-expanded={adding}
            style={{
              borderRadius: tokens.radius,
              border: `1px dashed ${tokens.borderStrong}`,
              padding: "2px 6px",
              fontSize: 11,
              color: tokens.textMuted,
              background: "none",
              cursor: "pointer",
            }}
          >
            {adding ? "Close" : "+ Add"}
          </button>
        )}
      </div>
      {canManage && adding && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          <Select
            label="Add user"
            value=""
            onChange={(e) => e.target.value && add.mutate({ user_id: e.target.value })}
          >
            <option value="">Choose a user…</option>
            {(users.data ?? [])
              .filter((u) => u.active && !participantUserIds.has(u.id))
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                  {onLeaveIds.has(u.id) ? " (away)" : ""}
                </option>
              ))}
          </Select>
          <Select
            label="Add team"
            value=""
            onChange={(e) => e.target.value && add.mutate({ team_id: e.target.value })}
          >
            <option value="">Choose a team…</option>
            {(teams.data ?? [])
              .filter((t) => !participantTeamIds.has(t.id))
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
          </Select>
        </div>
      )}
      {error && <p style={{ marginTop: 6, fontSize: 11, color: tokens.danger }}>{error}</p>}
      <p style={{ marginTop: 4, fontSize: 11, color: tokens.textFaint }}>
        Participants follow this issue's updates
      </p>
    </div>
  );
}
