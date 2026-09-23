import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Link2, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { linkTypesQuery, projectsQuery, queryKeys } from "../../lib/queries";
import {
  InstanceRole,
  LinkDirection,
  type LinkDirectionValue,
  type LinkTypeCreate,
  type LinkTypeDef,
  type Project,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { Modal } from "../../components/Modal";
import { SelectField } from "../../components/SelectField";
import { Spinner } from "../../components/Spinner";
import { TextField } from "../../components/TextField";
import { ScopePicker } from "../../components/settings/ScopePicker";
import { SettingsPage, settingsTableClasses } from "../../components/settings/SettingsPage";
import { ErrorText } from "../../components/ErrorText";

/**
 * Issue link types (spec 91): the relationships items can have. Built-ins
 * (blocks/relates/duplicates) plus any the admin defines — each with its own
 * directional names, direction, and global/project scope, via the shared
 * ScopePicker. Instance-admin only.
 */
export function LinkTypesSettingsPage() {
  const me = useCurrentUser();
  const isAdmin = me?.instance_role === InstanceRole.admin;
  const types = useQuery(linkTypesQuery());
  const projects = useQuery(projectsQuery());
  const [editing, setEditing] = useState<LinkTypeDef | null>(null);
  const [creating, setCreating] = useState(false);
  const projectKeys = new Map((projects.data ?? []).map((p) => [p.id, p.key]));
  const all = types.data ?? [];
  const search = useListFilter(all, (type) => [
    type.name,
    type.key,
    type.outward_name,
    type.inward_name,
  ]);
  const list = search.filtered;

  if (!isAdmin) {
    return (
      <SettingsPage history={{ entities: ["link_type"] }} title="Link types">
        <EmptyState icon={Link2} message="Only instance admins can manage link types." />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage history={{ entities: ["link_type"] }}
      title="Link types"
      description="The relationships issues can have — each with its own directional names and scope."
      info={
        <>
          Link types describe how two issues relate ("blocks", "duplicates", or your own). A{" "}
          <strong>directed</strong> type reads differently each way ("blocks" / "is blocked by"); a{" "}
          <strong>symmetric</strong> one reads the same both ways ("relates to"). Scope a type{" "}
          <strong>global</strong> or to specific projects.
        </>
      }
    >
      <div className="mb-3 flex items-center justify-between">
        <span />
        <Button onClick={() => setCreating(true)}>
          <Plus size={14} aria-hidden />
          New link type
        </Button>
      </div>

      {types.isPending ? (
        <Spinner label="Loading link types…" />
      ) : types.isError ? (
        <ErrorText error={types.error} />
      ) : (
        <>
          {all.length > 8 && (
            <ListSearchInput
              className="mb-3"
              value={search.filter}
              onChange={search.setFilter}
              placeholder="Filter link types…"
              ariaLabel="Filter link types by name"
              total={all.length}
              matched={list.length}
              noun="link types"
            />
          )}
          {search.filtering && list.length === 0 ? (
            <EmptyState
              icon={Link2}
              message={`No link types match “${search.filter.trim()}”.`}
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-subtle">
              <table className={settingsTableClasses.table}>
                <thead>
                  <tr>
                    <th className={settingsTableClasses.head}>Type</th>
                    <th className={settingsTableClasses.head}>Outward</th>
                    <th className={settingsTableClasses.head}>Inward</th>
                    <th className={settingsTableClasses.head}>Direction</th>
                    <th className={settingsTableClasses.head}>Scope</th>
                    <th className={settingsTableClasses.head}>Usages</th>
                    <th className={settingsTableClasses.head} />
                  </tr>
                </thead>
                <tbody>
                  {list.map((type) => (
                    <LinkTypeRow
                      key={type.id}
                      type={type}
                      projectKeys={projectKeys}
                      onEdit={() => setEditing(type)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {(creating || editing) && (
        <LinkTypeModal
          existing={editing}
          projects={projects.data ?? []}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </SettingsPage>
  );
}

function LinkTypeRow({
  type,
  projectKeys,
  onEdit,
}: {
  type: LinkTypeDef;
  projectKeys: Map<string, string>;
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const del = useMutation({
    mutationFn: () => api.delete(`${ApiPath.linkTypes}/${type.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.linkTypes }),
  });
  const cell = settingsTableClasses.cell;
  return (
    <tr className="last:[&>td]:border-b-0">
      <td className={`${cell} whitespace-nowrap`}>
        <span className="text-heading">{type.name}</span>
        {type.system && (
          <span className="ml-2 rounded bg-elevated px-1 text-[10px] uppercase tracking-wide text-fg-muted">
            built-in
          </span>
        )}
        {type.auto_managed && (
          <span className="ml-1 rounded bg-elevated px-1 text-[10px] uppercase tracking-wide text-fg-muted">
            auto
          </span>
        )}
      </td>
      <td className={`${cell} text-fg-secondary`}>{type.outward_name}</td>
      <td className={`${cell} text-fg-secondary`}>
        {type.direction === LinkDirection.symmetric ? (
          <span className="text-fg-faint">—</span>
        ) : (
          type.inward_name
        )}
      </td>
      <td className={cell}>
        <span className="capitalize text-fg-secondary">{type.direction}</span>
      </td>
      <td className={cell}>
        {type.project_ids.length === 0 ? (
          <span className="inline-flex items-center gap-1 text-fg-muted">
            <Globe size={11} /> Global
          </span>
        ) : (
          <span className="flex flex-wrap gap-1">
            {type.project_ids.map((id) => (
              <span key={id} className="rounded bg-elevated px-1 font-mono text-[11px]">
                {projectKeys.get(id) ?? "?"}
              </span>
            ))}
          </span>
        )}
      </td>
      <td className={`${cell} tabular-nums text-fg-secondary`}>{type.usages}</td>
      <td className={`${cell} whitespace-nowrap text-right`}>
        {!type.auto_managed && (
          <button
            type="button"
            onClick={onEdit}
            aria-label={`Edit ${type.name}`}
            className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <Pencil size={13} />
          </button>
        )}
        {!type.system && (
          <button
            type="button"
            onClick={() => {
              if (type.usages > 0) {
                void confirm({
                  title: "Can't delete link type",
                  message: `Can't delete — ${type.usages} link(s) still use "${type.name}".`,
                  confirmLabel: "OK",
                  hideCancel: true,
                });
                return;
              }
              void confirm({
                title: "Delete link type",
                message: `Delete the "${type.name}" link type?`,
                confirmLabel: "Delete",
                danger: true,
              }).then((ok) => {
                if (ok) del.mutate();
              });
            }}
            aria-label={`Delete ${type.name}`}
            className="ml-1 rounded p-1 text-fg-muted hover:bg-elevated hover:text-red-400 cursor-pointer"
          >
            <Trash2 size={13} />
          </button>
        )}
        {confirmDialog}
      </td>
    </tr>
  );
}

const DIRECTIONS = [
  [LinkDirection.directed, "Directed — reads differently each way"],
  [LinkDirection.symmetric, "Symmetric — same both ways"],
] as const;

function LinkTypeModal({
  existing,
  projects,
  onClose,
}: {
  existing: LinkTypeDef | null;
  projects: Project[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const isEdit = existing !== null;
  const [name, setName] = useState(existing?.name ?? "");
  const [key, setKey] = useState(existing?.key ?? "");
  const [outward, setOutward] = useState(existing?.outward_name ?? "");
  const [inward, setInward] = useState(existing?.inward_name ?? "");
  const [direction, setDirection] = useState<LinkDirectionValue>(
    existing?.direction ?? LinkDirection.directed,
  );
  const [projectIds, setProjectIds] = useState<string[]>(existing?.project_ids ?? []);
  const symmetric = direction === LinkDirection.symmetric;

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        outward_name: outward.trim(),
        inward_name: symmetric ? outward.trim() : inward.trim(),
        direction,
        project_ids: projectIds,
      };
      if (isEdit) return api.patch(`${ApiPath.linkTypes}/${existing.id}`, body);
      const create: LinkTypeCreate = { ...body, key: key.trim() };
      return api.post(ApiPath.linkTypes, create);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.linkTypes });
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  // The key is derived from the name on create until the user edits it.
  const suggestKey = (value: string) =>
    value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30);

  return (
    <Modal title={isEdit ? `Edit "${existing.name}"` : "New link type"} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!isEdit && (key === "" || key === suggestKey(name))) setKey(suggestKey(e.target.value));
            }}
            placeholder="Depends"
            maxLength={60}
            required
          />
          <TextField
            label="Key"
            value={key}
            onChange={(e) => setKey(e.target.value.toLowerCase())}
            placeholder="depends"
            hint={isEdit ? "Permanent" : "Stable, lowercase — permanent once created"}
            disabled={isEdit}
            maxLength={30}
            required
          />
        </div>

        <SelectField
          label="Direction"
          value={direction}
          onChange={(e) => setDirection(e.target.value as LinkDirectionValue)}
        >
          {DIRECTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>

        <div className="grid grid-cols-2 gap-3">
          <TextField
            label={symmetric ? "Name (both ways)" : "Outward name"}
            value={outward}
            onChange={(e) => setOutward(e.target.value)}
            placeholder={symmetric ? "relates to" : "blocks"}
            maxLength={60}
            required
          />
          {!symmetric && (
            <TextField
              label="Inward name"
              value={inward}
              onChange={(e) => setInward(e.target.value)}
              placeholder="is blocked by"
              maxLength={60}
              required
            />
          )}
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-fg-secondary">Scope</p>
          <ScopePicker value={projectIds} onChange={setProjectIds} projects={projects} />
          <p className="mt-1.5 text-[11px] text-fg-faint">
            A global type is offered on every project; a scoped one only on those you pick.
          </p>
        </div>

        {save.isError && <ErrorText error={save.error} />}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={
              save.isPending || !name.trim() || !outward.trim() || (!isEdit && !key.trim())
            }
          >
            {save.isPending ? "Saving…" : isEdit ? "Save" : "Create link type"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
