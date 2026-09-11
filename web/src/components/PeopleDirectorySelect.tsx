import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { peopleChoicesQuery, PEOPLE_CHOICES_PAGE_SIZE, type PeopleChoice } from "../lib/queries/users";
import { useDebounced } from "../lib/hooks";
import { SEARCH_DEBOUNCE_MS } from "../lib/constants";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { ListSearchInput } from "./ListSearchInput";
import { DirectoryPager } from "./DirectoryPager";
import { QueryError } from "./QueryError";
import { Spinner } from "./Spinner";

/** Person/team filters search the directory without downloading every account.
 * The selected label survives searches and page changes in the picker. */
export function PeopleDirectorySelect({ kind, value, onChange, label, emptyLabel, candidateTeamId, candidatePurpose, disabled = false }: {
  kind: "person" | "team"; value: PeopleChoice | null; candidateTeamId?: string; candidatePurpose?: "member" | "manager" | "owner"; disabled?: boolean;
  onChange: (value: PeopleChoice | null) => void; label: string; emptyLabel: string;
}) {
  const [open, setOpen] = useState(false);
  return <>
    <Button variant="secondary" size="sm" aria-label={label} aria-haspopup="dialog"
      disabled={disabled} className="max-w-full" onClick={() => setOpen(true)}>
      <span className="truncate">{value?.name ?? emptyLabel}</span><ChevronDown size={12} aria-hidden />
    </Button>
    {open && <PeopleChoices kind={kind} candidateTeamId={candidateTeamId} candidatePurpose={candidatePurpose} label={label} emptyLabel={emptyLabel}
      onSelect={choice => { onChange(choice); setOpen(false); }} onClose={() => setOpen(false)} />}
  </>;
}

function PeopleChoices({ kind, label, emptyLabel, onSelect, onClose, candidateTeamId, candidatePurpose }: {
  kind: "person" | "team"; label: string; emptyLabel: string; candidateTeamId?: string; candidatePurpose?: "member" | "manager" | "owner";
  onSelect: (value: PeopleChoice | null) => void; onClose: () => void;
}) {
  const [filter, setFilter] = useState("");
  const q = useDebounced(filter.trim(), SEARCH_DEBOUNCE_MS);
  const [position, setPosition] = useState({ q, page: 0 });
  if (position.q !== q) setPosition({ q, page: 0 });
  const page = position.q === q ? position.page : 0;
  const query = useQuery(peopleChoicesQuery(kind, q, page, candidateTeamId, candidatePurpose));
  const busy = query.isFetching || q !== filter.trim();
  const total = query.data?.total ?? 0;
  return <Modal title={label} onClose={onClose}>
    <ListSearchInput value={filter} onChange={setFilter} placeholder={`Search ${kind === "person" ? "people" : "teams"}…`}
      total={total} matched={total} noun={kind === "person" ? "people" : "teams"} />
    <Button className="mt-2" variant="ghost" onClick={() => onSelect(null)}>{candidateTeamId ? "Clear selection" : emptyLabel}</Button>
    <div aria-busy={busy} className="mt-2 max-h-[45dvh] overflow-y-auto">
      {query.isError ? <div className="space-y-2"><QueryError label={kind === "person" ? "people" : "teams"} error={query.error} /><Button variant="secondary" onClick={() => void query.refetch()}>Retry choices</Button></div>
        : query.isPending ? <Spinner label="Loading choices…" />
        : !query.data.rows.length ? <p className="py-4 text-sm text-fg-muted">No matches.</p>
        : <ul>{query.data.rows.map(row => <li key={row.id}>
          <Button variant="ghost" className="w-full justify-start" onClick={() => onSelect(row)}>{row.name}</Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager page={page} pageSize={PEOPLE_CHOICES_PAGE_SIZE} total={total} busy={busy}
      onPage={next => setPosition({ q, page: next })} label={kind === "person" ? "people" : "teams"} />
  </Modal>;
}
