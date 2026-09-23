import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../../lib/api";
import { apiFieldOptionsPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { queryKeys } from "../../lib/queries";
import { FieldType, type FieldDef } from "../../lib/types";
import { TokenMultiSelect } from "../TokenMultiSelect";
import { Button, ButtonVariant } from "../Button";
import { Modal } from "../Modal";
import { FieldOptionChoices } from "./FieldOptionChoices";
import { fieldOptionsQuery, FIELD_DIRECTORY_PAGE_SIZE, type ManagedField } from "../../lib/queries/field-settings";
import { useDirectory } from "../../lib/useDirectory";
import { DirectoryPager } from "../DirectoryPager";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { ErrorText } from "../ErrorText";

/** Option payloads and mounted rows use bounded server search windows. */
export function FieldOptionsSection({ field, canManage }: { field: ManagedField; canManage: boolean }) {
  const queryClient = useQueryClient();
  const directory = useDirectory(field.id, FIELD_DIRECTORY_PAGE_SIZE, (q, page) => fieldOptionsQuery(field.id, q, page));
  useEffect(() => {
    if (directory.isSuccess && !directory.busy && directory.page > 0 && directory.page * directory.pageSize >= directory.total) {
      directory.setPage(Math.max(0, Math.ceil(directory.total / directory.pageSize) - 1));
    }
  }, [directory.isSuccess, directory.busy, directory.page, directory.pageSize, directory.total, directory.setPage]);
  const [staged, setStaged] = useState<string[]>([]);
  const [removing, setRemoving] = useState<string | null>(null);

  const add = useMutation({
    mutationFn: () =>
      api.post<FieldDef>(`${apiFieldOptionsPath(field.id)}?include_options=false`, { values: staged }),
    onSuccess: () => setStaged([]),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.fields }),
  });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-fg-muted">
          {field.option_count} option{field.option_count === 1 ? "" : "s"}
        </span>
        {(
          <input
            value={directory.filter}
            onChange={(event) => directory.setFilter(event.target.value)}
            placeholder="Filter options…"
            aria-label="Filter options"
            className="h-8 min-w-0 w-44 max-w-full rounded-md border border-strong bg-surface px-2 text-xs text-fg placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
        )}
      </div>
      {directory.isPending ? <Spinner label="Loading options…" /> : directory.isError ? <div><QueryError label="field options" error={directory.error} /><Button variant="secondary" onClick={() => void directory.refetch()}>Retry options</Button></div> : directory.rows.length > 0 ? (
        <div aria-label="Field options" aria-busy={directory.busy} className="flex max-h-40 flex-wrap content-start gap-1 overflow-y-auto rounded-md border border-subtle bg-surface/40 p-2">
          {directory.rows.map((option) => (
            <span
              key={option}
              className="flex min-w-0 items-center gap-1 rounded border border-strong bg-elevated/60 py-0.5 pl-1.5 pr-1 text-[11px] text-fg"
            >
              <span className="min-w-0 break-words [overflow-wrap:anywhere]">{option || "(empty value)"}</span>
              {canManage && field.option_count > 1 && (
                <button
                  type="button"
                  onClick={() => setRemoving(option)}
                  aria-label={`Remove option ${option}`}
                  title={`Remove "${option}"`}
                  className="flex size-8 shrink-0 items-center justify-center rounded text-fg-faint hover:bg-strong hover:text-fg cursor-pointer"
                >
                  <X size={10} aria-hidden />
                </button>
              )}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-fg-faint">
          {field.option_count === 0 ? "No options yet — add some below." : "No options match the filter."}
        </p>
      )}
      <DirectoryPager {...directory} onPage={directory.setPage} label="field options" />
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
          {add.isError && <ErrorText error={add.error} />}
          <p className="text-[11px] text-fg-faint">
            Adding an option is always safe. Removing one asks where its issues should go
            first. Renaming is not offered — every saved view, automation and form that
            names the old value would keep compiling and match nothing.
          </p>
        </>
      )}
      {removing !== null && (
        <RemoveOptionDialog
          field={field}
          value={removing}
          onClose={() => setRemoving(null)}
        />
      )}
    </div>
  );
}

/**
 * "Remove this option — and then what?" (RADD-949).
 *
 * The question is asked with its own number in it (a dry-run count), because
 * accepting a migration whose size you cannot see is not consent. What the
 * dialog offers is decided by the FIELD, matching `service.remove_option`
 * exactly: a multi_select needs no substitute, a required single-select must
 * name one, an optional one may clear.
 */
function RemoveOptionDialog({
  field,
  value,
  onClose,
}: {
  field: FieldDef;
  value: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const multi = field.type === FieldType.multi_select;
  const [replaceWith, setReplaceWith] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);

  const usage = useQuery({
    queryKey: [...queryKeys.fields, field.id, "usage", value] as const,
    queryFn: ({ signal }) =>
      api.get<{ items: number }>(
        `${apiFieldOptionsPath(field.id)}/usage?value=${encodeURIComponent(value)}`, { signal },
      ),
  });

  const remove = useMutation({
    mutationFn: () =>
      api.post<FieldDef>(`${apiFieldOptionsPath(field.id)}/remove?include_options=false`, {
        value,
        replace_with: multi ? null : replaceWith,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.fields });
      await invalidateEntities(queryClient, Entity.item);
      onClose();
    },
  });

  const count = usage.data?.items;
  return (
    <Modal title={`Remove "${value}"`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-fg-secondary">
          {usage.isError ? "The usage count could not be loaded. Retry before removing this option." : count === undefined
            ? "Counting the issues that use it…"
            : count === 0
              ? "No issues use this option. A saved default using it will also be updated."
              : multi
                ? `${count} issue${count === 1 ? "" : "s"} list this option. It will be removed from each of them; the rest of their selections stay.`
                : `${count} issue${count === 1 ? "" : "s"} hold this option. Choose where they go.`}
        </p>

        {!multi && (field.required || count !== 0) && <div className="space-y-2">
          <p className="text-xs text-fg-secondary">Move those issues to</p>
          <Button variant="secondary" className="h-auto min-h-9 max-w-full" aria-haspopup="dialog" onClick={() => setChoosing(true)}>
            <span className="min-w-0 break-words [overflow-wrap:anywhere]">{replaceWith ?? (field.required ? "Choose replacement option" : "Leave empty")}</span>
          </Button>
          {!field.required && replaceWith !== null && <Button variant="ghost" onClick={() => setReplaceWith(null)}>Leave empty</Button>}
          {field.required && <p className="text-xs text-fg-muted">A required field needs a replacement, including for its saved default.</p>}
        </div>}
        {choosing && <FieldOptionChoices fieldId={field.id} exclude={value} onClose={() => setChoosing(false)}
          onSelect={option => { setReplaceWith(option); setChoosing(false); }} />}

        {usage.isError && <div><ErrorText error={usage.error} /><Button variant="ghost" onClick={() => void usage.refetch()}>Retry usage count</Button></div>}
        {remove.isError && <ErrorText error={remove.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={ButtonVariant.danger}
            onClick={() => remove.mutate()}
            disabled={remove.isPending || !usage.isSuccess || (!multi && field.required && replaceWith === null)}
          >
            {remove.isPending ? "Removing…" : "Remove option"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

