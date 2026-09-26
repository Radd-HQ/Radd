import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2, Trash2, UserCheck } from "lucide-react";
import { api, errorMessage, invalidateEntities, type DirectoryChoice,
 Button, CollapsibleCard, IconButton, DirectorySelect, QueryError, Spinner, TextField } from "@radd/plugin-sdk";
import { useVcsList } from "./queries";
import { VcsMatchedBy, type VcsReplayResult, type VcsUserLink, type VcsUserLinkSet, type VcsUnmatchedAuthor } from "./types";
const apiVcsIdentitiesPath = (provider: string, id: string) => `/vcs/${encodeURIComponent(provider)}/connections/${encodeURIComponent(id)}/identities`;
const apiVcsUnmatchedPath = (provider: string, id: string) => `/vcs/${encodeURIComponent(provider)}/connections/${encodeURIComponent(id)}/unmatched`;
const apiVcsUnmatchedReplayPath = (provider: string, id: string) => apiVcsUnmatchedPath(provider, id)+"/replay";
const apiVcsIdentityPath = (id: string) => `/vcs/identities/${encodeURIComponent(id)}`;
/**
 * One connection's identity map (RADD-1258): which provider account is which
 * Radd user, and the accounts whose time entries are PARKED because nothing
 * matched them. Mapping an unmatched account replays its parked entries into
 * real worklogs in the same step — the answer to "someone logged time on an MR
 * and it never showed up" is one row here.
 *
 * The unmatched list is derived from the parked rows, so it empties itself as
 * mappings land; nothing is kept in sync by hand.
 */
export function VcsIdentityMap({ provider, connectionId }: { provider: string; connectionId: string }) {
  const identities = useVcsList<VcsUserLink[]>(provider, [connectionId, "identities"], apiVcsIdentitiesPath(provider, connectionId), ["vcsUserLink"]);
  const unmatched = useVcsList<VcsUnmatchedAuthor[]>(provider, [connectionId, "unmatched"], apiVcsUnmatchedPath(provider, connectionId), ["vcsUserLink", "worklog"]);
  const count = (identities.data?.length ?? 0) + (unmatched.data?.length ?? 0);
  if (identities.isPending || unmatched.isPending) return <div role="status"><Spinner />Loading time-tracking identities…</div>;
  return (
    <CollapsibleCard title="Time-tracking identities" count={count} defaultOpen={(unmatched.data?.length ?? 0) > 0}>
      <p className="mb-3 text-[12px] text-fg-muted">
        Time logged on a merge or pull request is mirrored into the linked issue as a worklog by
        the person who logged it. Accounts are matched by email; when the host hides emails, map
        them here. An account nobody matches has its entries held, not guessed.
      </p>
      {identities.isError ? (
        <QueryError label="identity map" error={identities.error} />
      ) : (
        <MappedList links={identities.data ?? []} provider={provider} connectionId={connectionId} />
      )}
      {unmatched.isError ? (
        <QueryError label="unmatched accounts" error={unmatched.error} />
      ) : (
        <UnmatchedList rows={unmatched.data ?? []} provider={provider} connectionId={connectionId} />
      )}
    </CollapsibleCard>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void invalidateEntities(queryClient, "vcsUserLink", "worklog");
  };
}

function MappedList({ links, provider, connectionId }: { links: VcsUserLink[]; provider: string; connectionId: string }) {
  const refresh = useRefresh();
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(apiVcsIdentityPath(id)),
    onSettled: refresh,
  });
  const [adding, setAdding] = useState(false);
  const [username, setUsername] = useState("");
  const [person, setPerson] = useState<DirectoryChoice | null>(null);
  const add = useMutation({
    mutationFn: () =>
      api.put<VcsUserLink>(apiVcsIdentitiesPath(provider, connectionId), {
        external_username: username.trim(),
        user_id: person!.id,
      } satisfies VcsUserLinkSet),
    onSuccess: () => {
      setAdding(false);
      setUsername("");
      setPerson(null);
      refresh();
    },
  });

  return (
    <section className="mb-4">
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">Mapped accounts</h4>
      {links.length === 0 ? (
        <p className="text-[12px] text-fg-faint">No accounts mapped yet. Matches by email appear here as they happen.</p>
      ) : (
        <ul className="divide-y divide-subtle/60 rounded-md border border-subtle">
          {links.map((link) => (
            <li key={link.id} className="flex items-center gap-2 px-3 py-1.5 text-[12px]">
              <Link2 size={12} className="text-fg-faint" aria-hidden />
              <span className="font-mono text-fg">{link.external_username}</span>
              <span className="text-fg-faint">→</span>
              <span className="text-heading">{link.user_name}</span>
              <span className="rounded bg-elevated px-1.5 py-px text-[10px] text-fg-muted">
                {link.matched_by === VcsMatchedBy.email ? "matched by email" : "mapped by hand"}
              </span>
              <IconButton
                danger
                className="ml-auto"
                aria-label={`Unmap ${link.external_username}`}
                onClick={() => remove.mutate(link.id)}
                disabled={remove.isPending}
              >
                <Trash2 size={12} />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
      {remove.isError && <QueryError label="unmapping account" error={remove.error} />}
      {adding ? (
          <form
            className="mt-2 flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (username.trim() && person) add.mutate();
            }}
          >
            <div className="w-44">
              <TextField
                aria-label="Host username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="host username"
              />
            </div>
            <DirectorySelect source="auth.people" value={person} onChange={setPerson} label="Radd user" emptyLabel="Choose a person…" />
            <Button type="submit" size="sm" disabled={!username.trim() || !person || add.isPending}>
              Map
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            {add.isError && <span className="text-[12px] text-status-danger-ink">{errorMessage(add.error)}</span>}
          </form>
        ) : (
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => setAdding(true)}>
            Map an account…
          </Button>
        )}
    </section>
  );
}

function UnmatchedList({ rows, provider, connectionId }: { rows: VcsUnmatchedAuthor[]; provider: string; connectionId: string }) {
  const refresh = useRefresh();
  const [choice, setChoice] = useState<Record<string, DirectoryChoice | null>>({});
  const [replayed, setReplayed] = useState<Record<string, number>>({});
  const replay = useMutation({
    mutationFn: (vars: { username: string; userId: string }) =>
      api.post<VcsReplayResult>(apiVcsUnmatchedReplayPath(provider, connectionId), {
        external_username: vars.username,
        user_id: vars.userId,
      } satisfies VcsUserLinkSet),
    onSuccess: (result, vars) => {
      setReplayed((prev) => ({ ...prev, [vars.username]: result.replayed }));
      refresh();
    },
  });
  return (
    <section>
      <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">Unmatched accounts</h4>
      {rows.length === 0 ? (
        <p className="text-[12px] text-fg-faint">
          {Object.keys(replayed).length > 0
            ? `Replayed: ${Object.entries(replayed).map(([name, n]) => `${name} (${n})`).join(", ")}.`
            : "Every account that logged time is matched."}
        </p>
      ) : (
        <ul className="divide-y divide-subtle/60 rounded-md border border-status-warning/40">
          {rows.map((row) => (
            <li key={row.external_username} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[12px]">
              <UserCheck size={12} className="text-status-warning-ink" aria-hidden />
              <span className="font-mono text-fg">{row.external_username}</span>
              {row.external_email && <span className="text-fg-muted">{row.external_email}</span>}
              <span className="text-fg-faint">
                {row.pending_entries} {row.pending_entries === 1 ? "entry" : "entries"} ·{" "}
                {row.pending_duration} held
              </span>
              <span className="ml-auto flex items-center gap-2">
                  <DirectorySelect
                    source="auth.people"
                    value={choice[row.external_username] ?? null}
                    onChange={(value) => setChoice((prev) => ({ ...prev, [row.external_username]: value }))}
                    label={`Radd user for ${row.external_username}`}
                    emptyLabel="Choose a person…"
                  />
                  <Button
                    size="sm"
                    disabled={!choice[row.external_username] || replay.isPending}
                    onClick={() =>
                      replay.mutate({ username: row.external_username, userId: choice[row.external_username]!.id })
                    }
                  >
                    Map and log
                  </Button>
                </span>
            </li>
          ))}
        </ul>
      )}
      {replay.isError && <p className="mt-1 text-[12px] text-status-danger-ink">{errorMessage(replay.error)}</p>}
    </section>
  );
}
