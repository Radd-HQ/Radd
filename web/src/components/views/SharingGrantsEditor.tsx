import { useEffect, useState } from "react";
import { resourceGrantsPageQuery, RESOURCE_GRANTS_PAGE_SIZE, type AccessGrantDirectoryRow } from "../../lib/queries/fields";
import { changeSharingGrant, type SharingDraft } from "../../lib/sharing-draft";
import type { ShareLevelValue } from "../../lib/types";
import { useDirectory } from "../../lib/useDirectory";
import { Button } from "../Button";
import { DirectoryPager } from "../DirectoryPager";
import { ErrorText } from "../ErrorText";
import { Select } from "../Select";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";
import { AddSharingGrantDialog, SHARE_LEVEL_OPTIONS } from "./AddSharingGrantDialog";
import { formatDate } from "../../lib/dates";

/**
 * Who a view/dashboard is shared with, edited in place and saved with the
 * containing dialog — nothing here writes on its own.
 *
 * Only explicit changes are submitted; paging never turns unseen rows into
 * deletions. The saved list is a 50-row server window (RADD-1115), so a share
 * added in this dialog has no server row yet: it renders at the TOP of the
 * same list, marked New (RADD-1179) — the old "Unsaved changes" tab parked
 * additions out of sight and read as a staging step that never existed.
 */
export function SharingGrantsEditor({ resourceType, resourceId, draft, onChange }: {
  resourceType: "view" | "dashboard"; resourceId: string; draft: SharingDraft; onChange: (value: SharingDraft) => void;
}) {
  const directory = useDirectory(`${resourceType}:${resourceId}`, RESOURCE_GRANTS_PAGE_SIZE,
    (q, page) => resourceGrantsPageQuery(resourceType, resourceId, q, page));
  const [adding, setAdding] = useState(false);
  const changed = Object.values(draft.changes);
  const pendingTotal = changed.length + draft.additions.length;
  useEffect(() => {
    if (directory.isSuccess && !directory.busy && directory.page > 0 && directory.page * directory.pageSize >= directory.total)
      directory.setPage(Math.max(0, Math.ceil(directory.total / directory.pageSize) - 1));
  }, [directory.isSuccess, directory.busy, directory.page, directory.pageSize, directory.total, directory.setPage]);
  const savedRow = (row: AccessGrantDirectoryRow) => {
    const edited = draft.changes[row.id];
    const removed = edited?.access === null;
    return <li key={row.id} data-sharing-grant={row.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded border border-subtle p-2 text-xs">
      <span className="min-w-0 flex-1 break-words">{row.subject_name ?? `Unavailable ${row.subject_type}`}</span>
      <span className="text-fg-muted">{row.subject_type}{row.effect === "deny" ? " · Deny" : ""}</span>
      {row.expires_at && <span className="text-fg-muted" title={row.expires_at}>{row.expired ? "Expired" : "Expires"} {formatDate(row.expires_at)}</span>}
      {removed ? <span>Will be removed</span> : <Select aria-label={row.effect === "deny" ? "Denied access level" : "Access level"} size="sm"
        value={edited?.access ?? row.access} options={SHARE_LEVEL_OPTIONS}
        onChange={value => onChange(changeSharingGrant(draft, row, value as ShareLevelValue))} />}
      <Button size="sm" variant="ghost" onClick={() => onChange(changeSharingGrant(draft, row, removed ? edited.original.access as ShareLevelValue : null))}>{removed ? "Undo removal" : "Remove share"}</Button>
      {edited && !removed && <Button size="sm" variant="ghost" onClick={() => onChange(changeSharingGrant(draft, row, edited.original.access as ShareLevelValue))}>Undo edit</Button>}
    </li>;
  };
  // A new share obeys the search like any other row — by its name.
  const needle = directory.filter.trim().toLowerCase();
  const newRows = draft.additions
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => !needle || (row.subjectName ?? "").toLowerCase().includes(needle));
  const newRow = ({ row, index }: (typeof newRows)[number]) =>
    <li key={row.draftId ?? `new-${index}`} data-sharing-new className="flex min-w-0 flex-wrap items-center gap-2 rounded border border-accent/40 bg-accent/5 p-2 text-xs">
      <span className="min-w-0 flex-1 break-words">{row.subjectName ?? `New ${row.kind}`}</span>
      <span className="text-fg-muted">{row.kind}</span>
      <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent-text">New</span>
      <Select aria-label="Access level" size="sm" value={row.level} options={SHARE_LEVEL_OPTIONS}
        onChange={level => onChange({ ...draft, additions: draft.additions.map((old, i) => i === index ? { ...old, level: level as ShareLevelValue } : old) })} />
      <Button size="sm" variant="ghost" onClick={() => onChange({ ...draft, additions: draft.additions.filter((_, i) => i !== index) })}>Remove</Button>
    </li>;
  const nothingListed = directory.isSuccess && !directory.rows.length && !newRows.length;
  return <section aria-label="Shared with" className="flex min-w-0 flex-col gap-3">
    <h3 className="text-xs font-semibold text-heading">Shared with</h3>
    <TextField type="search" label="Find people, teams or groups" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
    <div aria-busy={directory.busy}>
      {directory.isPending ? <Spinner label="Loading who this is shared with…" /> : directory.isError ? <div role="alert"><ErrorText error={directory.error} />
        <Button variant="secondary" onClick={() => void directory.refetch()}>Retry</Button></div> :
        <ul className="flex flex-col gap-2">{newRows.map(newRow)}{directory.rows.map(savedRow)}</ul>}
      {nothingListed && <p className="text-xs text-fg-muted">{needle ? "Nobody matches." : "Not shared with anyone yet."}</p>}
    </div>
    {directory.isSuccess && <DirectoryPager {...directory} onPage={directory.setPage} label="shares" />}
    <Button variant="secondary" className="w-fit" onClick={() => setAdding(true)}>Share with someone…</Button>
    <p className="text-xs text-fg-muted" data-sharing-pending={pendingTotal}>
      {pendingTotal > 0 && <span className="text-fg">{pendingTotal === 1 ? "1 unsaved change" : `${pendingTotal} unsaved changes`} · </span>}
      {`Sharing changes are saved with the ${resourceType}. Existing expiry and deny policies are kept.`}
    </p>
    {adding && <AddSharingGrantDialog onClose={() => setAdding(false)} onAdd={share => {
      // Prevent duplicate additions across pages; saved duplicate policy is
      // validated transactionally by the server, with the draft retained.
      if (!draft.additions.some(row => row.kind === share.kind && row.subjectId === share.subjectId && row.level === share.level))
        onChange({ ...draft, additions: [...draft.additions, share] });
      setAdding(false);
    }} />}
  </section>;
}
