import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, tokens, useCurrentUser, usePermissions, type Item, type Project } from "@radd/plugin-sdk";
import { Check, ShieldCheck, X } from "lucide-react";

/**
 * Approvals card (spec 71) as a FEDERATED remote (spec 94): `GET /items/{id}/approvals` is
 * empty-quiet, so ungated items render nothing. Shows live requests (target state, votes x/N,
 * per-voter verdicts) with Approve/Decline for eligible approvers (the server resolves the
 * electorate), Cancel for the requester/manager, and "Request approval" affordances for the
 * server-computed gated targets. The deciding approve AUTO-APPLIES the move; banked-unlock guard
 * errors ride the vote response and surface inline. Extracted from the host's IssueProperties into
 * the `approvals` plugin's own UI bundle; styled from `@radd/plugin-sdk` tokens — no hardcoded color.
 */

// --- The permission atom this card checks (inlined; the host owns the enum) ---
const PROJECT_MANAGE = "project.manage";

// --- The approvals wire contract, inlined (a remote can't import the host's types) ---
const ApprovalStatus = {
  pending: "pending",
  approved: "approved",
  declined: "declined",
  canceled: "canceled",
  applied: "applied",
} as const;

const ApprovalVerdict = {
  approve: "approve",
  decline: "decline",
} as const;
type ApprovalVerdictValue = (typeof ApprovalVerdict)[keyof typeof ApprovalVerdict];

interface ApprovalUserRef {
  id: string;
  name: string;
}
interface ApprovalVote {
  user: ApprovalUserRef;
  verdict: ApprovalVerdictValue;
  note: string;
  created_at: string;
}
/** Per-entry rule progress (spec 107): a user entry needs that person's
 * approval; a team entry needs `required` approvals from current members. */
interface ApprovalEntry {
  kind: "user" | "team";
  id: string;
  name: string;
  required: number;
  approved_count: number;
  satisfied: boolean;
}
interface ApprovalRequest {
  id: string;
  item_id: string;
  to_state_id: string;
  to_state_name: string;
  status: (typeof ApprovalStatus)[keyof typeof ApprovalStatus];
  note: string;
  requested_by: ApprovalUserRef | null;
  entries: ApprovalEntry[];
  approvers: ApprovalUserRef[];
  approved_count: number;
  votes: ApprovalVote[];
  created_at: string;
}
interface ItemApprovals {
  live: ApprovalRequest[];
  history: ApprovalRequest[];
  requestable_to_states: { state_id: string; name: string }[];
}
interface ApprovalVoteResult {
  request: ApprovalRequest;
  applied: boolean;
  errors: string[];
}

const approvalsKey = (itemId: string) => ["radd-remote", "approvals", itemId] as const;

// --- Endpoint paths (inlined from the host's constants) ---
const itemApprovalsPath = (itemId: string) => `/items/${itemId}/approvals`;
const approvalPath = (requestId: string) => `/approvals/${requestId}`;
const approvalVotePath = (requestId: string) => `/approvals/${requestId}/vote`;

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function ApprovalsCard({ item, project }: { item: Item; project: Project }) {
  const me = useCurrentUser();
  const perms = usePermissions();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: approvalsKey(item.id),
    queryFn: ({ signal }) => api.get<ItemApprovals>(itemApprovalsPath(item.id), { signal }),
  });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: approvalsKey(item.id) });
  const vote = useMutation({
    mutationFn: (input: { requestId: string; verdict: ApprovalVerdictValue }) =>
      api.post<ApprovalVoteResult>(approvalVotePath(input.requestId), { verdict: input.verdict }),
    onSuccess: (result) => {
      setNotice(
        result.errors.length > 0
          ? `Approved — the move is still blocked: ${result.errors.join("; ")}`
          : null,
      );
    },
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: refresh,
  });
  const request = useMutation({
    mutationFn: (toStateId: string) =>
      api.post<ApprovalRequest>(itemApprovalsPath(item.id), { to_state_id: toStateId }),
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: refresh,
  });
  const cancel = useMutation({
    mutationFn: (requestId: string) => api.delete<void>(approvalPath(requestId)),
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: refresh,
  });

  if (!data || (data.live.length === 0 && data.requestable_to_states.length === 0)) {
    return null;
  }
  const canManage = perms.project(project, PROJECT_MANAGE);
  const busy = vote.isPending || request.isPending || cancel.isPending;

  const requestBox: React.CSSProperties = {
    borderRadius: tokens.radius,
    border: `1px solid ${tokens.border}`,
    padding: "8px 10px",
  };
  const verdictBtn = (accent: string): React.CSSProperties => ({
    borderRadius: tokens.radius,
    border: `1px solid ${accent}`,
    background: tokens.panel,
    color: accent,
    padding: "2px 8px",
    fontSize: 11,
    cursor: busy ? "default" : "pointer",
  });

  return (
    <div style={{ padding: "12px 16px" }} data-plugin-section="approvals">
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
        <ShieldCheck size={12} aria-hidden />
        Approvals
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {data.live.map((live) => {
          const isApprover = me != null && live.approvers.some((a) => a.id === me.id);
          const canCancel = me != null && (live.requested_by?.id === me.id || canManage);
          return (
            <div key={live.id} style={requestBox}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                <span
                  style={{
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    color: tokens.text,
                  }}
                >
                  → {live.to_state_name}
                </span>
                {live.status === ApprovalStatus.approved && (
                  <span
                    style={{
                      flexShrink: 0,
                      borderRadius: tokens.radius,
                      background: tokens.panel,
                      padding: "1px 6px",
                      fontSize: 10,
                      color: tokens.success,
                    }}
                  >
                    Approved
                  </span>
                )}
                {canCancel && (
                  <button
                    type="button"
                    onClick={() => cancel.mutate(live.id)}
                    disabled={busy}
                    style={{
                      marginLeft: "auto",
                      flexShrink: 0,
                      background: "none",
                      border: "none",
                      cursor: busy ? "default" : "pointer",
                      fontSize: 11,
                      color: tokens.textFaint,
                    }}
                  >
                    Cancel
                  </button>
                )}
              </div>
              {/* Per-entry progress (spec 107): every chip must go green —
                  "DevOps 1/2", "Hussein Jarrar ✓". */}
              {live.entries.length > 0 && (
                <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {live.entries.map((entry) => (
                    <span
                      key={`${entry.kind}:${entry.id}`}
                      style={{
                        borderRadius: tokens.radius,
                        border: `1px solid ${tokens.border}`,
                        background: tokens.panel,
                        padding: "1px 6px",
                        fontSize: 10,
                        color: entry.satisfied ? tokens.success : tokens.textMuted,
                      }}
                    >
                      {entry.kind === "team"
                        ? `${entry.name} ${entry.approved_count}/${entry.required}`
                        : entry.name}
                      {entry.satisfied ? " ✓" : ""}
                    </span>
                  ))}
                </div>
              )}
              {live.requested_by && (
                <p
                  title={live.note}
                  style={{
                    marginTop: 2,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontSize: 11,
                    color: tokens.textFaint,
                  }}
                >
                  Requested by {live.requested_by.name}
                  {live.note ? ` — “${live.note}”` : ""}
                </p>
              )}
              {live.votes.length > 0 && (
                <ul
                  style={{
                    marginTop: 4,
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                    listStyle: "none",
                    padding: 0,
                  }}
                >
                  {live.votes.map((entry) => (
                    <li
                      key={entry.user.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: 11,
                        color: tokens.textMuted,
                      }}
                    >
                      {entry.verdict === ApprovalVerdict.approve ? (
                        <Check size={11} aria-hidden style={{ flexShrink: 0, color: tokens.success }} />
                      ) : (
                        <X size={11} aria-hidden style={{ flexShrink: 0, color: tokens.danger }} />
                      )}
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {entry.user.name}
                      </span>
                      {entry.note && (
                        <span
                          title={entry.note}
                          style={{
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            color: tokens.textFaint,
                          }}
                        >
                          — {entry.note}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {isApprover && live.status === ApprovalStatus.pending && (
                <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    onClick={() => vote.mutate({ requestId: live.id, verdict: ApprovalVerdict.approve })}
                    disabled={busy}
                    style={verdictBtn(tokens.success)}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={() => vote.mutate({ requestId: live.id, verdict: ApprovalVerdict.decline })}
                    disabled={busy}
                    style={verdictBtn(tokens.danger)}
                  >
                    Decline
                  </button>
                </div>
              )}
            </div>
          );
        })}
        {data.requestable_to_states.map((target) => (
          <button
            key={target.state_id}
            type="button"
            onClick={() => request.mutate(target.state_id)}
            disabled={busy}
            style={{
              alignSelf: "flex-start",
              borderRadius: tokens.radius,
              border: `1px solid ${tokens.borderStrong}`,
              background: "none",
              padding: "4px 8px",
              fontSize: 11,
              color: tokens.textMuted,
              cursor: busy ? "default" : "pointer",
            }}
          >
            Request approval → {target.name}
          </button>
        ))}
      </div>
      {notice && <p style={{ marginTop: 6, fontSize: 11, color: tokens.danger }}>{notice}</p>}
    </div>
  );
}
