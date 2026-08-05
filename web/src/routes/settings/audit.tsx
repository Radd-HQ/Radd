import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { ApiError } from "../../lib/api";
import { HISTORY_FIELD_LABELS, initials } from "../../lib/meta";
import { auditQuery } from "../../lib/queries";
import { SEARCH_DEBOUNCE_MS } from "../../lib/constants";
import { useDebounced } from "../../lib/hooks";
import type { AuditEntry, HistoryChange } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { Pager } from "../../components/Pager";
import { Select } from "../../components/Select";
import { Table, TBody, Td, THead, Th } from "../../components/Table";
import { TableSkeleton } from "../../components/TableSkeleton";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/** Entity filter options (wire entity_type -> label). "" = all. */
const ENTITY_OPTIONS: readonly (readonly [string, string])[] = [
  ["", "All activity"],
  ["item", "Items"],
  ["comment", "Comments"],
  ["worklog", "Worklogs"],
  ["web_link", "Related links"],
  ["vcs_link", "Version control"],
  ["state", "States"],
  ["field", "Fields"],
  ["role", "Roles"],
  ["user", "Users & members"],
  ["cycle", "Cycles"],
  ["release", "Releases"],
  ["view", "Saved views"],
  ["automation", "Automations"],
  ["form", "Intake forms"],
];

const AUDIT_PAGE_SIZE = 50;

/**
 * Admin audit log — every attributable change across the server, read from
 * the append-only event stream (`GET /audit`). Requires admin; a 403
 * degrades to an access notice.
 */
export function AuditSettingsPage() {
  const [entityType, setEntityType] = useState("");
  return <AuditTable entityType={entityType} onEntityType={setEntityType} />;
}

function AuditTable({
  entityType,
  onEntityType,
}: {
  entityType: string;
  onEntityType: (value: string) => void;
}) {
  // RADD-884: server q (event type or payload text) + real paging — the page
  // used to hardcode the first 200 rows of an unbounded trail.
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q, SEARCH_DEBOUNCE_MS);
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [debouncedQ, entityType]);
  const audit = useQuery(
    auditQuery({
      entityType,
      q: debouncedQ,
      limit: AUDIT_PAGE_SIZE,
      offset: (page - 1) * AUDIT_PAGE_SIZE,
    }),
  );
  const forbidden = audit.error instanceof ApiError && audit.error.status === 403;

  const filter = (
    <div className="flex items-center gap-2">
      <input
        type="search"
        value={q}
        onChange={(event) => setQ(event.target.value)}
        placeholder="Search type or payload…"
        aria-label="Search the audit trail"
        className="h-8 w-56 rounded-md border border-subtle bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
      />
      <Select
        value={entityType}
        onChange={onEntityType}
        aria-label="Filter by entity"
        options={ENTITY_OPTIONS.map(([value, label]) => ({ value, label }))}
      />
    </div>
  );

  return (
    <SettingsPage
      title="Audit log"
      description="Every attributable change, newest first — from the append-only event log. Admin only."
      actions={filter}
    >
      {audit.isPending ? (
        <TableSkeleton rows={6} />
      ) : forbidden ? (
        <p className="rounded-md border border-subtle px-4 py-3 text-sm text-fg-muted">
          You need admin access to view the audit log.
        </p>
      ) : audit.isError ? (
        <QueryError label="audit log" error={audit.error} />
      ) : audit.data.length === 0 ? (
        <EmptyState icon={ScrollText} message="No activity recorded for this filter." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>When</Th>
                <Th>Who</Th>
                <Th>Action</Th>
                <Th>Entity</Th>
                <Th>Details</Th>
              </tr>
            </THead>
            <TBody>
              {audit.data.map((entry) => (
                <AuditRow key={entry.id} entry={entry} />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {audit.data && (page > 1 || audit.data.length === AUDIT_PAGE_SIZE) && (
        <div className="mt-3 flex justify-end">
          <Pager
            page={page}
            // The trail is unbounded and uncounted: a short page ends it.
            pageCount={audit.data.length < AUDIT_PAGE_SIZE ? page : null}
            onPage={setPage}
          />
        </div>
      )}
    </SettingsPage>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  return (
    <tr>
      <Td className="whitespace-nowrap text-fg-muted">
        <time dateTime={entry.at} title={new Date(entry.at).toLocaleString()}>
          {new Date(entry.at).toLocaleString()}
        </time>
      </Td>
      <Td className="whitespace-nowrap">
        {entry.actor ? (
          <span className="flex items-center gap-2">
            <span className="flex size-5 items-center justify-center rounded-full bg-strong text-[9px] font-semibold text-fg">
              {initials(entry.actor.name)}
            </span>
            {entry.actor.name}
          </span>
        ) : (
          <span className="text-fg-faint">System</span>
        )}
      </Td>
      <Td className="whitespace-nowrap">
        <span className="font-mono text-[12px] text-fg-secondary">{entry.event_type}</span>
      </Td>
      <Td className="whitespace-nowrap text-fg-muted">{entry.entity_type}</Td>
      <Td className="text-fg-muted">{summarize(entry.changes)}</Td>
    </tr>
  );
}

/** Compact one-line summary of an item event's field changes. */
function summarize(changes: HistoryChange[] | null | undefined): string {
  if (!changes || changes.length === 0) return "—";
  return changes
    .map((change) =>
      change.field === "custom_field"
        ? change.name ?? "field"
        : HISTORY_FIELD_LABELS[change.field] ?? change.field,
    )
    .join(", ");
}
