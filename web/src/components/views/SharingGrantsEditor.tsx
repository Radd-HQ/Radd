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

/** Only explicit changes are submitted; paging never turns unseen rows into deletions. */
export function SharingGrantsEditor({ resourceType, resourceId, draft, onChange }: {
  resourceType: "view" | "dashboard"; resourceId: string; draft: SharingDraft; onChange: (value: SharingDraft) => void;
}) {
  const directory = useDirectory(`${resourceType}:${resourceId}`, RESOURCE_GRANTS_PAGE_SIZE,
    (q, page) => resourceGrantsPageQuery(resourceType, resourceId, q, page));
  const [adding, setAdding] = useState(false);
  const [pendingOnly, setPendingOnly] = useState(false);
  const [pendingPage, setPendingPage] = useState(0);
  const changed = Object.values(draft.changes);
  const pendingTotal = changed.length + draft.additions.length;
  useEffect(() => {
    if (directory.isSuccess && !directory.busy && directory.page > 0 && directory.page * directory.pageSize >= directory.total)
      directory.setPage(Math.max(0, Math.ceil(directory.total / directory.pageSize) - 1));
  }, [directory.isSuccess, directory.busy, directory.page, directory.pageSize, directory.total, directory.setPage]);
  useEffect(() => { setPendingPage(page => Math.min(page, Math.max(0, Math.ceil(pendingTotal / RESOURCE_GRANTS_PAGE_SIZE) - 1))); }, [pendingTotal]);
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
  const pending = [...changed.map(change => ({ saved: change.original, index: -1 })),
    ...draft.additions.map((_, index) => ({ saved: null, index }))];
  return <section aria-label="Sharing recipients" className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-wrap gap-2">
      <Button variant={pendingOnly ? "ghost" : "secondary"} onClick={() => setPendingOnly(false)}>Saved recipients</Button>
      <Button variant={pendingOnly ? "secondary" : "ghost"} onClick={() => setPendingOnly(true)}>Pending edits ({pendingTotal})</Button>
    </div>
    {pendingOnly ? <>
      <ul className="flex flex-col gap-2">{pending.slice(pendingPage * RESOURCE_GRANTS_PAGE_SIZE, (pendingPage + 1) * RESOURCE_GRANTS_PAGE_SIZE).map(entry => {
        if (entry.saved) return savedRow(entry.saved);
        const row = draft.additions[entry.index];
        return <li key={row.draftId ?? `new-${entry.index}`} className="flex min-w-0 flex-wrap items-center gap-2 rounded border border-subtle p-2 text-xs">
          <span className="min-w-0 flex-1 break-words">{row.subjectName ?? `New ${row.kind}`}</span><span>New recipient</span>
          <Select aria-label="Access level" size="sm" value={row.level} options={SHARE_LEVEL_OPTIONS}
            onChange={level => onChange({ ...draft, additions: draft.additions.map((old, index) => index === entry.index ? { ...old, level: level as ShareLevelValue } : old) })} />
          <Button size="sm" variant="ghost" onClick={() => onChange({ ...draft, additions: draft.additions.filter((_, index) => index !== entry.index) })}>Remove from draft</Button>
        </li>;
      })}</ul>
      {!pendingTotal && <p className="text-xs text-fg-muted">No recipient changes in this draft.</p>}
      <DirectoryPager page={pendingPage} pageSize={RESOURCE_GRANTS_PAGE_SIZE} total={pendingTotal} busy={false} onPage={setPendingPage} label="pending edits" />
    </> : <>
      <TextField type="search" label="Find sharing recipients" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
      <div aria-busy={directory.busy}>
        {directory.isPending ? <Spinner label="Loading sharing recipients…" /> : directory.isError ? <div role="alert"><ErrorText error={directory.error} />
          <Button variant="secondary" onClick={() => void directory.refetch()}>Retry sharing recipients</Button></div> :
          <ul className="flex flex-col gap-2">{directory.rows.map(savedRow)}</ul>}
        {directory.isSuccess && !directory.rows.length && <p className="text-xs text-fg-muted">No matching recipients.</p>}
      </div>
      {directory.isSuccess && <DirectoryPager {...directory} onPage={directory.setPage} label="sharing recipients" />}
    </>}
    <Button variant="secondary" className="w-fit" onClick={() => setAdding(true)}>Add sharing recipient</Button>
    <p className="text-xs text-fg-muted">Recipient changes stay in this draft until you save. Existing expiry and deny policies are retained.</p>
    {adding && <AddSharingGrantDialog onClose={() => setAdding(false)} onAdd={share => {
      // Prevent duplicate additions across pages; saved duplicate policy is
      // validated transactionally by the server, with the draft retained.
      if (!draft.additions.some(row => row.kind === share.kind && row.subjectId === share.subjectId && row.level === share.level))
        onChange({ ...draft, additions: [...draft.additions, share] });
      setAdding(false); setPendingOnly(true);
    }} />}
  </section>;
}
