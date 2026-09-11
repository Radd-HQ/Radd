import type { DirectoryOption } from "../../../lib/queries/options";
import { subscriptionOptionsQuery } from "../../../lib/queries/notifications";
import { useDirectory } from "../../../lib/useDirectory";
import type { RuleScopeValue } from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { TextField } from "../../TextField";
import { DirectoryPager } from "../../DirectoryPager";
import { QueryError } from "../../QueryError";
import { Spinner } from "../../Spinner";
import { SCOPE_LABELS } from "./matrix";

export function SubscriptionTargetPicker({ scope, onSelect, onClose }: {
  scope: RuleScopeValue; onSelect: (row: DirectoryOption) => void; onClose: () => void;
}) {
  const directory = useDirectory(scope, 50, (q, page) => subscriptionOptionsQuery(scope, q, page));
  return <Modal title={`Subscribe to a ${SCOPE_LABELS[scope].toLowerCase()}`} onClose={onClose}>
    <TextField type="search" label="Find subscription targets" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
    <p className="mt-2 text-xs text-fg-muted">Existing subscriptions are excluded.</p>
    <div aria-busy={directory.busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {directory.isPending ? <Spinner label="Loading targets…" /> : directory.isError ? <div className="space-y-2">
        <QueryError label="subscription targets" error={directory.error} /><Button variant="secondary" onClick={() => void directory.refetch()}>Retry targets</Button>
      </div> : directory.rows.length === 0 ? <p className="py-3 text-sm text-fg-muted">No matching subscription targets.</p>
        : <ul>{directory.rows.map(row => <li key={row.value}><Button variant="ghost" className="w-full justify-start" onClick={() => onSelect(row)}>
          {row.hint && <span className="max-w-[40%] shrink-0 truncate font-mono text-xs">{row.hint}</span>}<span className="truncate">{row.label}</span>
        </Button></li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="subscription targets" />
  </Modal>;
}
