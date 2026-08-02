import { useMemo } from "react";
import { PersonName } from "../PersonName";
import { useQuery } from "@tanstack/react-query";
import { Globe, Trash2 } from "lucide-react";
import { teamsQuery, usersQuery } from "../../lib/queries";
import { GrantSubject, ShareLevel, type ShareLevelValue } from "../../lib/types";
import { SubjectPicker, type Subject } from "../settings/SubjectPicker";
import { Select } from "../Select";

/**
 * Sharing editor for a view (spec 57), owner-only: what everyone on the server
 * gets (nothing / view / edit — the wire field is `global_access`,
 * spec 86) plus explicit per-person and per-team grants
 * at viewer|editor. The whole state is saved atomically via
 * PUT /views/{id}/sharing (or inline on POST for new views) — this component
 * only edits local state.
 */

export interface LocalShare {
  kind: "user" | "team";
  subjectId: string;
  level: ShareLevelValue;
}

/** Sentinel for "not server-wide visible" in the select (never a real level). */
export const SERVER_PRIVATE = "";

export function ViewSharingEditor({
  serverAccess,
  onServerAccess,
  shares,
  onShares,
  canBroadcast,
  transferTo,
  onTransferTo,
  noun = "view",
}: {
  serverAccess: ShareLevelValue | typeof SERVER_PRIVATE;
  onServerAccess: (value: ShareLevelValue | typeof SERVER_PRIVATE) => void;
  shares: LocalShare[];
  onShares: (next: LocalShare[]) => void;
  /** view.create in scope — server-wide visibility is a broadcast. */
  canBroadcast: boolean;
  /** Provided when editing an existing view: ownership transfer on save. */
  transferTo?: string;
  onTransferTo?: (userId: string) => void;
  /** What is being shared — the copy noun ("view" here, "dashboard" in spec 75). */
  noun?: string;
}) {
  const users = useQuery(usersQuery);
  const teams = useQuery(teamsQuery());

  // Users + teams as the reusable SubjectPicker's options (views share with people/teams).
  const subjects = useMemo<Subject[]>(
    () => [
      ...(users.data ?? []).map((u) => ({ type: GrantSubject.user, id: u.id, name: u.name })),
      ...(teams.data ?? []).map((t) => ({ type: GrantSubject.team, id: t.id, name: t.name })),
    ],
    [users.data, teams.data],
  );
  const subjectFor = (share: LocalShare): Subject | null =>
    share.subjectId ? subjects.find((s) => s.type === share.kind && s.id === share.subjectId) ?? null : null;

  const setShare = (index: number, patch: Partial<LocalShare>) =>
    onShares(shares.map((share, i) => (i === index ? { ...share, ...patch } : share)));

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium text-fg-secondary">
        Sharing
        <span className="ml-1.5 font-normal text-fg-faint">
          — you own this {noun}; grantees with “can edit” may change it, only you can re-share or
          delete it
        </span>
      </span>

      <label className="flex items-center gap-2 text-xs text-fg-secondary">
        <Globe size={13} className="shrink-0 text-fg-faint" aria-hidden />
        Everyone on this server
        <Select
          aria-label="Server-wide access"
          value={serverAccess}
          onChange={(level) => onServerAccess(level as ShareLevelValue | "")}
          disabled={!canBroadcast && serverAccess === SERVER_PRIVATE}
          title={
            canBroadcast
              ? undefined
              : `Server-wide sharing needs ${noun} management rights in this scope`
          }
          size="sm"
          options={[
            { value: SERVER_PRIVATE, label: "no access (only people listed below)" },
            { value: ShareLevel.viewer, label: "can view" },
            { value: ShareLevel.editor, label: "can edit" },
          ]}
        />
      </label>

      {shares.map((share, index) => (
        <div key={index} className="flex items-center gap-2">
          <SubjectPicker
            subjects={subjects}
            value={subjectFor(share)}
            onChange={(s) =>
              setShare(index, s ? { kind: s.type as "user" | "team", subjectId: s.id } : { subjectId: "" })
            }
            placeholder="Person or team…"
          />
          <Select
            aria-label="Access level"
            value={share.level}
            onChange={(level) => setShare(index, { level: level as ShareLevelValue })}
            size="sm"
            options={[
              { value: ShareLevel.viewer, label: "can view" },
              { value: ShareLevel.editor, label: "can edit" },
              { value: ShareLevel.owner, label: "co-owner" },
            ]}
          />
          <button
            type="button"
            aria-label="Remove share"
            onClick={() => onShares(shares.filter((_, i) => i !== index))}
            className="text-fg-faint hover:text-red-400 cursor-pointer"
          >
            <Trash2 size={13} aria-hidden />
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={() =>
          onShares([...shares, { kind: "user", subjectId: "", level: ShareLevel.viewer }])
        }
        className="w-fit text-xs text-fg-muted hover:text-fg cursor-pointer"
      >
        + Share with a person or team
      </button>

      {onTransferTo && (
        <label className="mt-1 flex items-center gap-2 border-t border-subtle/60 pt-2 text-xs text-fg-secondary">
          Transfer ownership to
          <Select
            aria-label="Transfer ownership to"
            value={transferTo ?? ""}
            onChange={onTransferTo}
            size="sm"
            className="min-w-0 flex-1"
            options={[
              { value: "", label: "— keep me as owner —" },
              ...(users.data ?? []).map((user) => ({ value: user.id, label: <PersonName user={user} /> })),
            ]}
          />
        </label>
      )}
      {onTransferTo && transferTo && (
        <p className="text-[11px] text-amber-400">
          On save, they become the owner (full control); you stay on as an editor.
        </p>
      )}
    </div>
  );
}
