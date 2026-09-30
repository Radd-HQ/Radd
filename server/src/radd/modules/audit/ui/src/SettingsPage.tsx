import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Bot, ScrollText, Server, X } from "lucide-react";
import { ApiError, useCapabilities, formatDateTime, Avatar, Button, EmptyState, ChangeList, DateField, Pager,
  DirectorySelect, QueryError, SelectField, SettingsPage, Table, TBody, Td, THead, Th, TableSkeleton, TextField, Slot, SlotId } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT, type ProjectSelectProps } from "@radd-plugin-ui/projects/picker-contract";
import { auditEntityLink, auditSentence, parseAuditSearch, type AuditSearch } from "./audit";
import { useAudit, useAuditAccess, useAuditCatalog } from "./queries";
import { AuditSource, type AuditEntry, type AuditSourceValue } from "./types";
function ProjectSelect(props: ProjectSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label}>Selection unavailable{props.value ? ` · ${props.value}` : ""}</Button>;
  return <Slot id={PROJECT_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
const AUDIT_PAGE_SIZE = 50;
/** Change lines shown before a row folds the rest behind "+N more". */
const CHANGES_PREVIEW = 3;

const SOURCE_OPTIONS = [
  { value: "", label: "Anyone" },
  { value: AuditSource.people, label: "People" },
  { value: AuditSource.automations, label: "Automations" },
  { value: AuditSource.system, label: "System" },
];

/** The audit ledger (spec 123), every filter in the URL so a view can be shared. An instance admin
 *  reads the instance; a project manager reads their project (the server enforces both). */
export function AuditSettingsPage() {
  const rawSearch = useSearch({ strict: false });
  const search = parseAuditSearch(rawSearch);
  const navigate = useNavigate();
  const access = useAuditAccess(search.project);
  const capabilities = useCapabilities();
  const availablePlugins = useMemo(() => new Set(capabilities?.plugins ?? []), [capabilities?.plugins]);
  const ownerRevision = JSON.stringify([capabilities?.plugins, capabilities?.remotes]);
  const instanceWide = access.data?.instance_wide === true;

  const setSearch = (patch: Partial<AuditSearch>) => {
    const next: Record<string, unknown> = { ...search, ...patch };
    for (const key of Object.keys(next)) if (!next[key]) delete next[key];
    void navigate({ to: "/settings/$", params: { _splat: "audit" }, search: next, replace: true });
  };

  // A draft is attached to its URL value. Back/forward, reset or an external link
  // immediately replaces stale input; only user input schedules a URL update.
  const [draft, setDraft] = useState<{base: string; value: string} | null>(null);
  const urlQ = search.q ?? "";
  useEffect(() => setDraft(null), [urlQ]);
  const q = draft?.base === urlQ ? draft.value : urlQ;
  const setQ = (value: string) => setDraft({base: urlQ, value});
  useEffect(() => {
    if (!draft || draft.base !== urlQ || draft.value === urlQ) return;
    const timer = setTimeout(() => setSearch({q: draft.value || undefined}), 250);
    return () => clearTimeout(timer);
    // setSearch uses the current URL so simultaneous filter edits are preserved.
  }, [draft, urlQ, JSON.stringify(search)]);
  const filterKey = JSON.stringify(search);
  const [pagination, setPagination] = useState({filterKey, page: 1});
  const page = pagination.filterKey === filterKey ? pagination.page : 1;
  if (pagination.filterKey !== filterKey) setPagination({filterKey, page: 1});
  const setPage = (page: number) => setPagination({filterKey, page});
  const catalog = useAuditCatalog(ownerRevision);
  const entityOptions = useMemo(() => {
    const options = [
      { value: "", label: "All entities" },
      ...(catalog.data?.entity_types ?? []).map((entry) => ({value: entry.key, label: entry.label})),
    ];
    // Historical or combined filters remain visible when owners leave the catalog.
    if (search.entity && !options.some(option => option.value === search.entity)) {
      const label = search.entity.split(",").map(key =>
        options.find(option => option.value === key)?.label ?? key.replace(/[._]/g, " "),
      ).join(", ");
      options.push({value: search.entity, label: `${label} (saved filter)`});
    }
    return options;
  }, [catalog.data, search.entity]);

  // A project manager cannot read the instance-wide view: the page asks for
  // the project first instead of handing them a 403.
  const needsProject = !access.isPending && !instanceWide && !search.project;
  const audit = useAudit({
      projectId: search.project,
      entityType: search.entity,
      entityId: search.entity_id,
      actorId: search.actor,
      changedField: search.field,
      source: search.source ?? "",
      start: search.from ? `${search.from}T00:00:00` : undefined,
      end: search.to ? `${search.to}T23:59:59.999999` : undefined,
      q: search.q,
      includeNoise: search.noise,
      limit: AUDIT_PAGE_SIZE,
      offset: (page - 1) * AUDIT_PAGE_SIZE,
    }, ownerRevision, access.data?.allowed === true);
  const forbidden = audit.error instanceof ApiError && audit.error.status === 403;
  const active = Object.entries(search).filter(([, v]) => v).length;

  const filters = (
    <div className="mb-4 flex flex-col gap-3 rounded-lg border border-subtle bg-surface p-3" data-audit-filters>
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-4">
        <ProjectSelect
          value={search.project ?? ""}
          onChange={(id) => setSearch({ project: id || undefined })}
          label="Project"
          emptyLabel={instanceWide ? "Every project" : "Choose a project…"}
          permission={"project.manage"}
        />
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Entity</span>
          <SelectField label=""
            value={search.entity ?? ""}
            onChange={(event) => setSearch({ entity: event.target.value || undefined, entity_id: undefined })}
            ariaLabel="Filter by entity type"
          >{entityOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</SelectField>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Who</span>
          <div className="flex items-center gap-1">
            <DirectorySelect
              source="auth.people"
              value={search.actor ? { id: search.actor, name: "Selected person" } : null}
              onChange={(choice) => setSearch({ actor: choice?.id })}
              label="Filter by person"
              emptyLabel="Anyone"
            />
            {search.actor && (
              <Button variant="ghost" size="sm" aria-label="Clear person" onClick={() => setSearch({ actor: undefined })}>
                <X size={12} aria-hidden />
              </Button>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Source</span>
          <SelectField label=""
            value={search.source ?? ""}
            onChange={(event) => setSearch({ source: (event.target.value || undefined) as AuditSourceValue | undefined })}
            ariaLabel="Filter by source"
          >{SOURCE_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</SelectField>
        </div>
        <TextField
          label="Changed field" list="audit-field-suggestions"
          placeholder="e.g. assignee, permissions"
          value={search.field ?? ""}
          onChange={(event) => setSearch({ field: event.target.value || undefined })}
        />
        <datalist id="audit-field-suggestions"><Slot id={SlotId.entityChangeFields} entityType={search.entity} /></datalist>
        <DateField label="From" value={search.from ?? null} onChange={(v) => setSearch({ from: v ?? undefined })} />
        <DateField label="To" value={search.to ?? null} onChange={(v) => setSearch({ to: v ?? undefined })} />
        <TextField
          label="Search"
          type="search"
          placeholder="Entity, value, event…"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          aria-label="Search the audit trail"
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-xs text-fg-muted">
          <input
            type="checkbox"
            checked={Boolean(search.noise)}
            onChange={(event) => setSearch({ noise: event.target.checked || undefined })}
          />
          Include system noise (notifications, mail delivery, scheduler ticks)
        </label>
        {active > 0 && (
          <Button variant="ghost" size="sm" onClick={() => { setDraft(null); setSearch(Object.fromEntries(Object.keys(search).map((k) => [k, undefined]))); }}>
            Reset filters
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <SettingsPage
      title="Audit log"
      description="Who changed what, from what, to what — every attributable change, newest first."
    >
      {filters}
      {catalog.isError && <QueryError label="audit filter vocabulary" error={catalog.error} />}
      {access.isError ? <QueryError label="audit access" error={access.error} /> : access.isPending ? <TableSkeleton rows={6} /> : needsProject ? (
        <p className="rounded-md border border-subtle px-4 py-3 text-sm text-fg-muted">
          Choose a project you manage to read its change history. The instance-wide log needs an instance admin.
        </p>
      ) : !access.data?.allowed || forbidden ? (
        <p className="rounded-md border border-subtle px-4 py-3 text-sm text-fg-muted">
          You need admin access to view the audit log for this scope.
        </p>
      ) : audit.isPending ? <TableSkeleton rows={6} /> : audit.isError ? (
        <QueryError label="audit log" error={audit.error} />
      ) : audit.data.length === 0 ? (
        <EmptyState><ScrollText size={24} aria-hidden />No activity recorded for this filter.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>When</Th>
                <Th>Who</Th>
                <Th>What</Th>
                <Th>Changes</Th>
              </tr>
            </THead>
            <TBody>
              {audit.data.map((entry) => (
                <AuditRow key={entry.id} entry={entry} showProject={!search.project} availablePlugins={availablePlugins} />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {!audit.isError && access.data?.allowed && audit.data && (page > 1 || audit.data.length === AUDIT_PAGE_SIZE) && (
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

function AuditRow({ entry, showProject, availablePlugins }: { entry: AuditEntry; showProject: boolean; availablePlugins: ReadonlySet<string> }) {
  const [expanded, setExpanded] = useState(false);
  const { who, did, what } = auditSentence(entry);
  const link = auditEntityLink(entry, availablePlugins);
  const changes = entry.changes ?? [];
  const visible = expanded ? changes : changes.slice(0, CHANGES_PREVIEW);
  const hidden = changes.length - visible.length;
  return (
    <tr data-audit-row={entry.id} data-audit-event={entry.event_type}>
      <Td className="whitespace-nowrap align-top text-fg-muted">
        <time dateTime={entry.at} title={formatDateTime(entry.at)}>
          {formatDateTime(entry.at)}
        </time>
      </Td>
      <Td className="whitespace-nowrap align-top">
        {entry.actor && !entry.actor.machine ? (
          <span className="flex items-center gap-2">
            <Avatar user={entry.actor} size="sm" />
            {who}
            {entry.automated && (
              <span title="Applied by an automation acting as this person" className="text-fg-faint">
                <Bot size={13} aria-hidden />
              </span>
            )}
          </span>
        ) : (
          // Actor-less, or a machine account (RADD-1499): a system row, not a person.
          <span className="flex items-center gap-2 text-fg-faint" data-audit-machine-actor={entry.actor?.id}>
            {entry.automated ? <Bot size={13} aria-hidden /> : <Server size={13} aria-hidden />}
            {who}
          </span>
        )}
      </Td>
      <Td className="align-top">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="rounded bg-elevated px-1.5 py-0.5 text-[11px] font-medium text-fg-secondary" data-audit-event-label>
            {did}
          </span>
          {link ? (
            <Link
              to={link.to}
              params={link.params ?? {}}
              search={link.search ?? {}}
              className="text-[13px] font-medium text-accent-text hover:text-accent-text-strong"
              data-audit-entity-link
            >
              {what}
            </Link>
          ) : (
            <span className="text-[13px] font-medium text-heading" data-audit-entity-label>
              {what}
            </span>
          )}
          {showProject && entry.project && (
            <span className="font-mono text-[11px] text-fg-faint" title={entry.project.name}>
              {entry.project.key}
            </span>
          )}
          {entry.silent && (
            <span className="text-[11px] text-fg-faint" title="Written by a bulk import — no notifications or automations ran">
              import
            </span>
          )}
        </div>
      </Td>
      <Td className="align-top">
        {changes.length === 0 ? (
          <span className="text-fg-faint">—</span>
        ) : (
          <div data-audit-changes>
            <ChangeList entityType={entry.entity_type} changes={visible} />
            {hidden > 0 && (
              <button
                type="button"
                onClick={() => setExpanded(true)}
                className="mt-0.5 text-[12px] text-accent-text hover:text-accent-text-strong cursor-pointer"
              >
                +{hidden} more
              </button>
            )}
          </div>
        )}
      </Td>
    </tr>
  );
}
