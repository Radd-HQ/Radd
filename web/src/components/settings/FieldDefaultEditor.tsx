import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import type { CustomFieldValue, FieldDef } from "../../lib/types";
import { CustomFieldControl } from "../items/CustomFieldsForm";
import { Button } from "../Button";

/**
 * Inline editor for a field's default_value (spec 50 follow-up). Reuses the same
 * type-aware `CustomFieldControl` that items render, seeded from `field.default_value`,
 * and PATCHes `/fields/{id}` on save. New items get this value when the create payload
 * leaves the field blank. Lives in the field's expanded settings panel.
 */
export function FieldDefaultEditor({ field, canManage }: { field: FieldDef; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<CustomFieldValue>(field.default_value ?? null);

  const save = useMutation({
    mutationFn: (default_value: CustomFieldValue) =>
      api.patch(`${ApiPath.fields}/${field.id}`, { default_value }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.fields }),
  });

  const norm = (value: CustomFieldValue) => JSON.stringify(value ?? null);
  const dirty = norm(draft) !== norm(field.default_value);
  const hasDefault = field.default_value !== null && field.default_value !== undefined;
  // Relabel the shared control ("Default value", never required) without mutating the def.
  const control: FieldDef = { ...field, name: "Default value", required: false };

  return (
    <div>
      <fieldset disabled={!canManage} className="border-0 p-0 disabled:opacity-60">
        <CustomFieldControl field={control} value={draft} onChange={setDraft} />
      </fieldset>
      <p className="mt-1 text-[11px] text-fg-faint">
        Seeded onto new items when this field is left blank on create.
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
      {save.isError && <p className="mt-1 text-[11px] text-red-400">{errorMessage(save.error)}</p>}
    </div>
  );
}
