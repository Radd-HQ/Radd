import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Bot, ScrollText, Server, X } from "lucide-react";
import { ApiError } from "../../lib/api";
import { auditEntityLink, auditSentence, type AuditSearch } from "../../lib/audit";
import { RoutePath } from "../../lib/constants";
import { SEARCH_DEBOUNCE_MS } from "../../lib/constants";
import { formatDateTime } from "../../lib/dates";
import { useDebounced, usePermissions } from "../../lib/hooks";
import { HISTORY_FIELD_LABELS } from "../../lib/meta";
import { auditCatalogQuery, auditQuery } from "../../lib/queries";
import { AuditSource, Permission, type AuditEntry, type AuditSourceValue } from "../../lib/types";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ChangeList } from "../../components/history/ChangeLines";
import { DateField } from "../../components/items/PlanningFields";
import { Pager } from "../../components/Pager";
import { PeopleDirectorySelect } from "../../components/PeopleDirectorySelect";
import { ProjectSelect } from "../../components/projects/ProjectSelect";
import { QueryError } from "../../components/QueryError";
import { Select } from "../../components/Select";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { Table, TBody, Td, THead, Th } from "../../components/Table";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";

const AUDIT_PAGE_SIZE = 50;
/** Change lines shown before a row folds the rest behind "+N more". */
const CHANGES_PREVIEW = 3;

const SOURCE_OPTIONS = [
  { value: "", label: "Anyone" },
  { value: AuditSource.people, label: "People" },
  { value: AuditSource.automations, label: "Automations" },
  { value: AuditSource.system, label: "System" },
];

/**
 * The audit ledger (spec 123): who changed what, from what, to what — every
 * filter in the URL so a view can be shared and a settings page can deep-link
 * the trail for what it shows. An instance admin reads the instance; a
 * project manager reads their project (the server enforces both).
 */
export function AuditSettingsPage() {
  const search = useSearch({ strict: false }) as AuditSearch;
  const navigate = useNavigate();
  const perms = usePermissions();
  const instanceWide = perms.global(Permission.globalManage);

  const setSearch = (patch: Partial<AuditSearch>) => {
    const next: Record<string, unknown> = { ...search, ...patch };
    for (const key of Object.keys(next)) if (!next[key]) delete next[key];
    void navigate({ to: RoutePath.settingsAudit, search: next as AuditSearch, replace: true });
  };

  const [q, setQ] = useState(search.q ?? "");
  const debouncedQ = useDebounced(q, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    if ((search.q ?? "") !== debouncedQ) setSearch({ q: debouncedQ || undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const [page, setPage] = useState(1);
  const filterKey = JSON.stringify(search);
  useEffect(() => setPage(1), [filterKey]);

  const catalog = useQuery(auditCatalogQuery());
  const entityOptions = useMemo(
    () => [
      { value: "", label: "All entities" },
      ...(catalog.data?.entity_types ?? []).map((e) => ({ value: e.key, label: e.label })),
    ],
    [catalog.data],
  );

  // A project manager cannot read the instance-wide view: the page asks for
  // the project first instead of handing them a 403.
  const needsProject = !instanceWide && !search.project;
  const audit = useQuery({
    ...auditQuery({
      projectId: search.project,
      entityType: search.entity,
      entityId: search.entity_id,
      actorId: search.actor,
      changedField: search.field,
      source: search.source ?? "",
      start: search.from ? `${search.from}T00:00:00` : undefined,
      end: search.to ? `${search.to}T23:59:59` : undefined,
      q: search.q,
      includeNoise: search.noise,
      limit: AUDIT_PAGE_SIZE,
      offset: (page - 1) * AUDIT_PAGE_SIZE,
    }),
    enabled: !needsProject,
  });
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
          permission={Permission.projectManage}
        />
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Entity</span>
          <Select
            value={search.entity ?? ""}
            onChange={(value) => setSearch({ entity: value || undefined, entity_id: undefined })}
            options={entityOptions}
            aria-label="Filter by entity type"
            searchable
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-secondary">Who</span>
          <div className="flex items-center gap-1">
            <PeopleDirectorySelect
              kind="person"
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
          <Select
            value={search.source ?? ""}
            onChange={(value) => setSearch({ source: (value || undefined) as AuditSourceValue | undefined })}
            options={SOURCE_OPTIONS}
            aria-label="Filter by source"
          />
        </div>
        <TextField
          label="Changed field"
          list="audit-field-suggestions"
          placeholder="e.g. assignee, permissions"
          value={search.field ?? ""}
          onChange={(event) => setSearch({ field: event.target.value || undefined })}
        />
        <datalist id="audit-field-suggestions">
          {Object.keys(HISTORY_FIELD_LABELS).map((key) => (
            <option key={key} value={key} />
          ))}
        </datalist>
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
          <Button variant="ghost" size="sm" onClick={() => { setQ(""); setSearch(Object.fromEntries(Object.keys(search).map((k) => [k, undefined]))); }}>
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
      {needsProject ? (
        <p className="rounded-md border border-subtle px-4 py-3 text-sm text-fg-muted">
          Choose a project you manage to read its change history. The instance-wide log needs an instance admin.
        </p>
      ) : audit.isPending ? (
        <TableSkeleton rows={6} />
      ) : forbidden ? (
        <p className="rounded-md border border-subtle px-4 py-3 text-sm text-fg-muted">
          You need admin access to view the audit log for this scope.
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
                <Th>What</Th>
                <Th>Changes</Th>
              </tr>
            </THead>
            <TBody>
              {audit.data.map((entry) => (
                <AuditRow key={entry.id} entry={entry} showProject={!search.project} />
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

function AuditRow({ entry, showProject }: { entry: AuditEntry; showProject: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const { who, did, what } = auditSentence(entry);
  const link = auditEntityLink(entry);
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
        {entry.actor ? (
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
          <span className="flex items-center gap-2 text-fg-faint">
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
            <ChangeList changes={visible} />
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
