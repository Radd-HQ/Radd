import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Button, TextField, tokens } from "@radd/plugin-sdk";

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 250;
const Kind = { user: "user", team: "team" } as const;
type KindValue = typeof Kind[keyof typeof Kind];
interface Choice { id: string; name: string; active?: boolean; has_access?: boolean | null }
interface TeamOption { value: string; label: string }

/** Mount only while adding; one lookahead row determines whether another page exists. */
export function ParticipantChoices({ projectId, userIds, teamIds, onLeaveIds, busy, onAdd }: {
  projectId: string; userIds: Set<string>; teamIds: Set<string>; onLeaveIds: Set<string>; busy: boolean;
  onAdd: (subject: { user_id?: string; team_id?: string }) => void;
}) {
  const [kind, setKind] = useState<KindValue>(Kind.user);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState({ q: "", page: 0 });
  useEffect(() => {
    if (search.trim() === query.q) return;
    const timer = setTimeout(() => setQuery({ q: search.trim(), page: 0 }), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search, query.q]);
  const choices = useQuery({
    queryKey: ["radd-remote", "participant-choices", projectId, kind, query.q, query.page],
    meta: { entities: ["member", "team", "group", "role", "project"] },
    queryFn: async ({ signal }): Promise<Choice[]> => {
      const params = { q: query.q, limit: String(PAGE_SIZE + 1), offset: String(query.page * PAGE_SIZE) };
      if (kind === Kind.user) return api.get<Choice[]>("/users/directory", { signal, query: { ...params, project_id: projectId } });
      const rows = await api.get<TeamOption[]>("/teams/directory/options", { signal, query: params });
      return rows.map(row => ({ id: row.value, name: row.label }));
    },
  });
  useEffect(() => {
    if (query.page > 0 && choices.isSuccess && choices.data.length === 0) {
      setQuery(current => ({ ...current, page: Math.max(0, current.page - 1) }));
    }
  }, [query.page, choices.isSuccess, choices.data]);
  const held = kind === Kind.user ? userIds : teamIds;
  const waiting = choices.isFetching || search.trim() !== query.q;
  return <div style={{ marginTop: 8 }}>
    <div style={{ display: "flex", gap: 6 }}>
      {Object.values(Kind).map(value => <Button key={value} small variant="ghost" aria-pressed={kind === value}
        onClick={() => { setKind(value); setQuery(current => ({ ...current, page: 0 })); }}>Add {value}</Button>)}
    </div>
    <TextField type="search" label={kind === Kind.user ? "Find participant users" : "Find participant teams"} value={search} onChange={event => setSearch(event.target.value)} />
    {choices.isError ? <div role="alert" style={{ color: tokens.danger }}>
      <p>Could not load participant choices.</p><Button small variant="ghost" onClick={() => void choices.refetch()}>Retry participant choices</Button>
    </div> : choices.isPending ? <p role="status">Loading participant choices…</p> : <>
      <ul aria-label="Participant choices" aria-busy={waiting} style={{ maxHeight: 240, overflowY: "auto", listStyle: "none", margin: 0, padding: 0 }}>
        {choices.data.slice(0, PAGE_SIZE).map(row => <li key={row.id}>
          <Button small variant="ghost" disabled={busy || waiting || held.has(row.id) || row.active === false}
            onClick={() => onAdd(kind === Kind.user ? { user_id: row.id } : { team_id: row.id })}
            style={{ width: "100%", textAlign: "start", height: "auto", whiteSpace: "normal", overflowWrap: "anywhere" }}>
            <span>{row.name}{kind === Kind.user && onLeaveIds.has(row.id) ? " (away)" : ""}
              {held.has(row.id) ? " — already added" : row.active === false ? " — inactive" : ""}
              {row.has_access === false && <span style={{ display: "block", fontSize: 11 }}>No project access — adding grants it</span>}</span>
          </Button>
        </li>)}
      </ul>
      {!choices.data.length && <p>No matching participants on this page.</p>}
      <nav aria-label="Participant choices pagination" style={{ display: "flex", justifyContent: "space-between", gap: 6, flexWrap: "wrap" }}>
        <Button small variant="ghost" disabled={waiting || query.page === 0} onClick={() => setQuery(current => ({ ...current, page: current.page - 1 }))}>Previous participants</Button>
        <span>Page {query.page + 1}</span>
        <Button small variant="ghost" disabled={waiting || choices.data.length <= PAGE_SIZE} onClick={() => setQuery(current => ({ ...current, page: current.page + 1 }))}>Next participants</Button>
      </nav>
    </>}
  </div>;
}
