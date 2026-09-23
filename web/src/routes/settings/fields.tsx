import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, SlidersHorizontal } from "lucide-react";
import { FIELD_TYPE_LABELS } from "../../lib/meta";
import { fieldDirectoryQuery, fieldSettingsSummaryQuery, FIELD_DIRECTORY_PAGE_SIZE } from "../../lib/queries/field-settings";
import { useDirectory } from "../../lib/useDirectory";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { DirectoryPager } from "../../components/DirectoryPager";
import { TableSkeleton } from "../../components/TableSkeleton";
import { QueryError } from "../../components/QueryError";
import { BuiltinFieldsSection } from "../../components/settings/BuiltinFieldsSection";
import { FieldEditor } from "../../components/settings/FieldEditor";
import { NewFieldModal } from "../../components/settings/NewFieldModal";
import { RestrictedBadge } from "../../components/settings/RestrictedBadge";
import { SettingsPage } from "../../components/settings/SettingsPage";

/** The rail reads summaries; only the selected definition loads its full editor. */
export function FieldsSettingsPage() {
  const fields = useDirectory("fields", FIELD_DIRECTORY_PAGE_SIZE, fieldDirectoryQuery);
  const permissions = useQuery(fieldSettingsSummaryQuery());
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { page, total, isSuccess } = fields;
  useEffect(() => { if (!selectedId && fields.rows[0]) setSelectedId(fields.rows[0].id); }, [selectedId, fields.rows]);
  useEffect(() => {
    if (isSuccess && page > 0 && page * FIELD_DIRECTORY_PAGE_SIZE >= total)
      fields.setPage(Math.max(0, Math.ceil(total / FIELD_DIRECTORY_PAGE_SIZE) - 1));
  }, [page, total, isSuccess]);
  // Keep a selected editor mounted across rail searches/pages and live refreshes.
  // An explicit selection may sit outside the current window.
  const selected = selectedId ?? fields.rows[0]?.id;
  return <SettingsPage history={{ entities: ["field"] }} title="Fields" description="Builtin and custom issue fields — scope, defaults, options, and access grants."
    info={<>Custom fields add typed, searchable data to issues. Availability controls which projects use a field; grants control who may read or change it.</>}>
    <div className="flex flex-col gap-10">
      <section aria-labelledby="custom-fields-heading">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 id="custom-fields-heading" className="text-sm font-semibold text-heading">Custom fields</h3>
          {permissions.data?.can_create && <Button onClick={() => setCreating(true)}><Plus size={14} aria-hidden />New field</Button>}
        </div>
        {permissions.isError && <div className="mb-3"><QueryError label="field permissions" error={permissions.error} /><Button variant="secondary" onClick={() => void permissions.refetch()}>Retry field permissions</Button></div>}
        <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(180px,240px)_minmax(0,1fr)]">
          <div className="min-w-0">
            <ListSearchInput value={fields.filter} onChange={fields.setFilter} placeholder="Filter fields…" ariaLabel="Filter fields by name or key" matched={fields.total} noun="fields" />
            <div aria-busy={fields.busy} className="mt-2">
              {fields.isPending ? <TableSkeleton rows={4} /> : fields.isError ? <div><QueryError label="fields" error={fields.error} /><Button variant="secondary" onClick={() => void fields.refetch()}>Retry fields</Button></div>
                : fields.rows.length === 0 ? <EmptyState icon={SlidersHorizontal} message={fields.q ? "No fields match this search." : "No custom fields available."} />
                : <ul aria-label="Custom fields" className="flex max-h-[55dvh] flex-col gap-0.5 overflow-y-auto rounded-lg border border-subtle p-1">{fields.rows.map(field => <li key={field.id}>
                  <button type="button" aria-pressed={field.id === selected} onClick={() => setSelectedId(field.id)} className={`flex w-full min-w-0 cursor-pointer flex-col gap-0.5 rounded-md px-2.5 py-2 text-left ${field.id === selected ? "bg-accent/10 ring-1 ring-accent/40" : "hover:bg-surface/60"}`}>
                    <span className="flex max-w-full items-center gap-2 text-[13px] text-heading"><span className="min-w-0 break-words">{field.name}</span>{field.restricted && <RestrictedBadge />}</span>
                    <span className="text-[11px] text-fg-muted">{FIELD_TYPE_LABELS[field.type]} · {field.project_count ? `${field.project_count} project${field.project_count === 1 ? "" : "s"}` : "Global"}</span>
                  </button>
                </li>)}</ul>}
            </div>
            <DirectoryPager {...fields} onPage={fields.setPage} label="fields" />
          </div>
          {selected && <FieldEditor key={selected} id={selected} allowGlobal={permissions.data?.can_update_global ?? false} onDeleted={() => setSelectedId(null)} />}
        </div>
      </section>
      <BuiltinFieldsSection canManage={permissions.data?.can_manage_builtin ?? false} canManageProjects={permissions.data?.can_manage_builtin_projects ?? false} />
    </div>
    {creating && <NewFieldModal allowGlobal={permissions.data?.can_create_global ?? false} onCreated={setSelectedId} onClose={() => setCreating(false)} />}
  </SettingsPage>;
}
