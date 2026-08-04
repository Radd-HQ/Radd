import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiFieldOptionsPath } from "../../lib/constants";
import { TokenMultiSelect } from "../../components/TokenMultiSelect";
import { usePermissions } from "../../lib/hooks";
import { FIELD_TYPE_LABELS } from "../../lib/meta";
import { fieldsQuery, projectsQuery, queryKeys } from "../../lib/queries";
import { Permission, type FieldDef, type Project } from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { BuiltinFieldsSection } from "../../components/settings/BuiltinFieldsSection";
import { AccessGrantsEditor } from "../../components/settings/AccessGrantsEditor";
import { FieldDefaultEditor } from "../../components/settings/FieldDefaultEditor";
import { FieldScopeEditor } from "../../components/settings/FieldScopeEditor";
import { NewFieldModal } from "../../components/settings/NewFieldModal";
import { RestrictedBadge } from "../../components/settings/RestrictedBadge";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/**
 * Custom-field admin as a two-pane master-detail: the left rail lists the fields,
 * the right pane edits the selected one (scope, default, widget, options, access).
 * Builtin-field access rules follow below.
 */
export function FieldsSettingsPage() {
  const perms = usePermissions();
  // RADD-810: field.manage is project-scoped and this page has no single
  // project — holding it ANYWHERE opens the editors; the server enforces per
  // definition.
  const canManage = perms.anyProject(Permission.fieldManage);
  const fields = useQuery(fieldsQuery());
  const projects = useQuery(projectsQuery());
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = fields.data ?? [];
  const selected = list.find((f) => f.id === selectedId) ?? list[0] ?? null;
  const projectKeys = new Map((projects.data ?? []).map((p) => [p.id, p.key]));

  return (
    <SettingsPage
      title="Fields"
      description="Builtin and custom item fields — scope, defaults, widgets, and access grants."
      info={
        <>
          Custom fields add typed, SLQ-queryable data to items — <strong>global</strong> or scoped
          to any set of projects. Builtin fields (state, assignee, dates…) are always present. Both
          accept grants restricting who can change — or read — a field.
        </>
      }
    >
      {fields.isPending ? (
        <TableSkeleton rows={4} />
      ) : fields.isError ? (
        <QueryError label="fields" error={fields.error} />
      ) : (
        <div className="flex flex-col gap-10">
          <section aria-labelledby="custom-fields-heading">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 id="custom-fields-heading" className="text-sm font-semibold text-heading">
                Custom fields
              </h3>
              {canManage && (
                <Button onClick={() => setCreating(true)}>
                  <Plus size={14} aria-hidden />
                  New field
                </Button>
              )}
            </div>

            {list.length === 0 ? (
              <EmptyState
                icon={SlidersHorizontal}
                message="No custom fields defined yet."
                action={
                  canManage && (
                    <Button variant="ghost" onClick={() => setCreating(true)}>
                      <Plus size={14} aria-hidden />
                      Define the first field
                    </Button>
                  )
                }
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-[minmax(200px,260px)_1fr]">
                <FieldRail
                  fields={list}
                  selectedId={selected?.id ?? null}
                  onSelect={setSelectedId}
                  projectKeys={projectKeys}
                />
                {selected && (
                  <FieldDetail
                    key={selected.id}
                    field={selected}
                    projects={projects.data ?? []}
                    canManage={canManage}
                    onDeleted={() => setSelectedId(null)}
                  />
                )}
              </div>
            )}
          </section>

          <BuiltinFieldsSection canManage={canManage} />
        </div>
      )}

      {creating && <NewFieldModal onClose={() => setCreating(false)} />}
    </SettingsPage>
  );
}

/** The left rail: one selectable row per field, with a scope hint. */
function FieldRail({
  fields,
  selectedId,
  onSelect,
  projectKeys,
}: {
  fields: FieldDef[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  projectKeys: Map<string, string>;
}) {
  return (
    <ul className="flex flex-col gap-0.5 rounded-lg border border-subtle p-1">
      {fields.map((field) => {
        const active = field.id === selectedId;
        const scope =
          field.project_ids.length === 0
            ? "Global"
            : field.project_ids.map((id) => projectKeys.get(id) ?? "?").join(", ");
        return (
          <li key={field.id}>
            <button
              type="button"
              onClick={() => onSelect(field.id)}
              className={
                "flex w-full flex-col gap-0.5 rounded-md px-2.5 py-2 text-left cursor-pointer " +
                (active ? "bg-accent/10 ring-1 ring-accent/40" : "hover:bg-surface/60")
              }
            >
              <div className="flex items-center gap-2">
                <span className={"text-[13px] " + (active ? "text-heading" : "text-fg")}>
                  {field.name}
                </span>
                {field.restricted && <RestrictedBadge />}
              </div>
              <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
                <span>{FIELD_TYPE_LABELS[field.type]}</span>
                <span className="text-fg-faint">·</span>
                <span className="truncate">{scope}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** The right pane: everything editable about one field. */
function FieldDetail({
  field,
  projects,
  canManage,
  onDeleted,
}: {
  field: FieldDef;
  projects: Project[];
  canManage: boolean;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const del = useMutation({
    mutationFn: () => api.delete(`${ApiPath.fields}/${field.id}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.fields });
      onDeleted();
    },
  });

  return (
    <div className="rounded-lg border border-subtle">
      <div className="flex items-start justify-between gap-3 border-b border-subtle/60 px-4 py-3">
        <div>
          <h4 className="text-sm font-semibold text-heading">{field.name}</h4>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-fg-muted">
            <span className="rounded bg-elevated px-1 font-mono">{field.key}</span>
            <span>{FIELD_TYPE_LABELS[field.type]}</span>
            {field.required && <span className="text-amber-400">required</span>}
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() =>
              void confirm({
                title: "Delete field",
                message: `Delete the "${field.name}" field? Its values stay on items but stop rendering.`,
                confirmLabel: "Delete",
                danger: true,
              }).then((ok) => {
                if (ok) del.mutate();
              })
            }
            title="Delete field"
            className="rounded-md border border-subtle p-1.5 text-fg-muted hover:border-red-500/40 hover:text-red-400 cursor-pointer"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      <dl className="flex flex-col divide-y divide-subtle/60">
        <Row label="Scope">
          <FieldScopeEditor field={field} projects={projects} canManage={canManage} />
        </Row>

        {(field.type === "select" || field.type === "multi_select") && (
          <Row label="Options">
            <FieldOptionsSection field={field} canManage={canManage} />
          </Row>
        )}

        <Row label="Default">
          <FieldDefaultEditor field={field} canManage={canManage} />
        </Row>


        <Row label="Access" full>
          <AccessGrantsEditor resourceType="field" resourceId={field.id} />
        </Row>
      </dl>
      {del.isError && (
        <p className="px-4 py-2 text-[11px] text-red-400">{errorMessage(del.error)}</p>
      )}
      {confirmDialog}
    </div>
  );
}

/** A labelled row in the detail pane. `full` drops the two-column layout for wide editors. */
function Row({
  label,
  children,
  full = false,
}: {
  label: string;
  children: React.ReactNode;
  full?: boolean;
}) {
  if (full) {
    return (
      <div className="px-4 py-3">
        <p className="mb-2 text-xs font-medium text-fg-secondary">{label}</p>
        {children}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-[100px_1fr] items-start gap-3 px-4 py-3">
      <dt className="pt-1 text-xs font-medium text-fg-secondary">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * A select field's option catalog (spec 107 cleanup): count + filter + a
 * CAPPED scrolling list instead of an unbounded pill wall, and an ADD control
 * over the spec-100 additive-only seam. There is deliberately no remove or
 * rename — items already store those values and would silently go invalid.
 */
function FieldOptionsSection({ field, canManage }: { field: FieldDef; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [staged, setStaged] = useState<string[]>([]);

  const add = useMutation({
    mutationFn: () =>
      api.post<FieldDef>(apiFieldOptionsPath(field.id), { values: staged }),
    onSuccess: () => setStaged([]),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.fields }),
  });

  const options = field.options ?? [];
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? options.filter((option) => option.toLowerCase().includes(needle))
    : options;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-fg-muted">
          {options.length} option{options.length === 1 ? "" : "s"}
        </span>
        {options.length > 12 && (
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter options…"
            aria-label="Filter options"
            className="h-7 w-44 rounded-md border border-strong bg-surface px-2 text-xs text-fg placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
        )}
      </div>
      {visible.length > 0 ? (
        <div className="flex max-h-40 flex-wrap content-start gap-1 overflow-y-auto rounded-md border border-subtle bg-surface/40 p-2">
          {visible.map((option) => (
            <span
              key={option}
              className="rounded border border-strong bg-elevated/60 px-1.5 py-0.5 text-[11px] text-fg"
            >
              {option}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-fg-faint">
          {options.length === 0 ? "No options yet — add some below." : "No options match the filter."}
        </p>
      )}
      {canManage && (
        <>
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <TokenMultiSelect
                value={staged}
                onChange={setStaged}
                options={[]}
                allowCreate
                placeholder="Add options — type and press Enter…"
                ariaLabel="Options to add"
              />
            </div>
            <Button
              size="sm"
              onClick={() => add.mutate()}
              disabled={staged.length === 0 || add.isPending}
            >
              {add.isPending ? "Adding…" : staged.length > 1 ? `Add ${staged.length}` : "Add"}
            </Button>
          </div>
          {add.isError && <p className="text-xs text-red-400">{errorMessage(add.error)}</p>}
          <p className="text-[11px] text-fg-faint">
            Adding options is always safe. Existing options can&apos;t be removed or renamed —
            items already store their values.
          </p>
        </>
      )}
    </div>
  );
}

