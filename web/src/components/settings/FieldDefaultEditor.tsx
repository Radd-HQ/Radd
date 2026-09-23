import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import { FieldType, type CustomFieldValue, type FieldDef } from "../../lib/types";
import { CustomFieldControl } from "../items/CustomFieldsForm";
import { Button } from "../Button";
import { FieldDefaultSelection } from "./FieldOptionChoices";
import { ErrorText } from "../ErrorText";

/**
 * Inline editor for a field's default_value (spec 50 follow-up). Reuses the same
 * type-aware `CustomFieldControl` that items render, seeded from `field.default_value`,
 * and PATCHes `/fields/{id}` on save. New items get this value when the create payload
 * leaves the field blank. Lives in the field's expanded settings panel.
 */
export function FieldDefaultEditor({ field, canManage }: { field: FieldDef; canManage: boolean }) {
  const queryClient = useQueryClient();
  const saved = field.default_value ?? null;
  const [state, setState] = useState({ base: saved, draft: saved });
  const norm = (value: CustomFieldValue) => JSON.stringify(value ?? null);
  // Adopt migrated/remote defaults only while clean; keep unfinished local edits.
  if (norm(state.base) !== norm(saved)) setState({ base: saved, draft: norm(state.draft) === norm(state.base) ? saved : state.draft });
  const draft = state.draft;
  const setDraft = (value: CustomFieldValue) => setState(current => ({ ...current, draft: value }));

  const save = useMutation({
    mutationFn: (default_value: CustomFieldValue) =>
      api.patch(`${ApiPath.fields}/${field.id}?include_options=false`, { default_value }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.fields }),
  });

  const dirty = norm(draft) !== norm(field.default_value);
  const hasDefault = field.default_value !== null && field.default_value !== undefined;
  // Relabel the shared control ("Default value", never required) without mutating the def.
  const control: FieldDef = { ...field, name: "Default value", required: false };

  return (
    <div>
      <fieldset disabled={!canManage} className="border-0 p-0 disabled:opacity-60">
        {field.type === FieldType.select || field.type === FieldType.multi_select ? <FieldDefaultSelection fieldId={field.id}
          value={Array.isArray(draft) ? draft.filter((value): value is string => typeof value === "string") : typeof draft === "string" ? [draft] : []}
          multiple={field.type === FieldType.multi_select} onChange={values => setDraft(field.type === FieldType.multi_select ? values.length ? values : null : values[0] ?? null)} />
          : <CustomFieldControl field={control} value={draft} onChange={setDraft} />}
      </fieldset>
      <p className="mt-1 text-[11px] text-fg-faint">
        Seeded onto new issues when this field is left blank on create.
      </p>
      {canManage && (
        <div className="mt-2 flex items-center gap-2">
          <Button
            className="h-7 px-2.5 text-xs"
            onClick={() => save.mutate(draft)}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save default"}
          </Button>
          {hasDefault && (
            <Button
              variant="ghost"
              className="h-7 px-2.5 text-xs"
              onClick={() => {
                setDraft(null);
                save.mutate(null);
              }}
              disabled={save.isPending}
            >
              Clear
            </Button>
          )}
        </div>
      )}
      {save.isError && <ErrorText className="mt-1" error={save.error} />}
    </div>
  );
}
