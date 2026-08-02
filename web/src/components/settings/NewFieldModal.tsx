import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, FIELD_KEY_HINT, FIELD_KEY_PATTERN } from "../../lib/constants";
import { FIELD_TYPE_LABELS, FIELD_TYPE_ORDER, fieldTypeHasOptions } from "../../lib/meta";
import { projectsQuery, queryKeys } from "../../lib/queries";
import {
  FieldType,
  type CustomFieldValue,
  type FieldDef,
  type FieldDefCreate,
  type FieldTypeValue,
} from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { CustomFieldControl } from "../items/CustomFieldsForm";
import { OptionsEditor } from "./OptionsEditor";
import { ScopePicker } from "./ScopePicker";

interface NewFieldModalProps {
  onClose: () => void;
}

/** Create a field definition. Definitions are create-only — no edit follows. */
export function NewFieldModal({ onClose }: NewFieldModalProps) {
  const queryClient = useQueryClient();
  const { data: projects } = useQuery(projectsQuery());

  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<FieldTypeValue>(FieldType.text);
  const [required, setRequired] = useState(false);
  const [options, setOptions] = useState<string[]>([]);
  const [defaultValue, setDefaultValue] = useState<CustomFieldValue>(null);
  // Empty = global; otherwise the projects the field is scoped to.
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [keyError, setKeyError] = useState<string>();
  const [optionsError, setOptionsError] = useState<string>();

  // A default valid for one type is invalid for the next — reset it when the type changes.
  const changeType = (next: FieldTypeValue) => {
    setType(next);
    setDefaultValue(null);
  };

  const createField = useMutation({
    mutationFn: (body: FieldDefCreate) => api.post<FieldDef>(ApiPath.fields, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.fields });
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmedKey = key.trim();
    const withOptions = fieldTypeHasOptions(type);
    setKeyError(undefined);
    setOptionsError(undefined);
    if (!FIELD_KEY_PATTERN.test(trimmedKey)) {
      setKeyError(`Invalid key: ${FIELD_KEY_HINT}.`);
      return;
    }
    if (withOptions && options.length === 0) {
      setOptionsError("Add at least one option.");
      return;
    }
    createField.mutate({
      project_ids: projectIds,
      key: trimmedKey,
      name: name.trim(),
      type,
      required,
      options: withOptions ? options : null,
      default_value: defaultValue,
    });
  };

  // A throwaway definition so the shared item control renders the right widget for the
  // chosen type/options; only type/options/name/required/display are read from it.
  const draftDefaultField: FieldDef = {
    id: "",
    project_ids: projectIds,
    key: key.trim(),
    name: "Default value (optional)",
    type,
    required: false,
    options: fieldTypeHasOptions(type) ? options : null,
    indexed: false,
    ai_visible: true,
    source: "user",
    display: null,
    default_value: null,
    restricted: false,
    created_at: "",
  };

  return (
    <Modal title="New field" onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Key"
            value={key}
            onChange={(event) => setKey(event.target.value.toLowerCase())}
            placeholder="department"
            hint={FIELD_KEY_HINT}
            error={keyError}
            maxLength={50}
            required
          />
          <TextField
            label="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Department"
            maxLength={200}
            required
          />
          <SelectField
            label="Type"
            value={type}
            onChange={(event) => changeType(event.target.value as FieldTypeValue)}
          >
            {FIELD_TYPE_ORDER.map((value) => (
              <option key={value} value={value}>
                {FIELD_TYPE_LABELS[value]}
              </option>
            ))}
          </SelectField>
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-fg-secondary">Scope</p>
          <ScopePicker value={projectIds} onChange={setProjectIds} projects={projects ?? []} />
          <p className="mt-1.5 text-[11px] text-fg-faint">
            A global field applies everywhere; a scoped field applies only to the projects you
            pick. You can widen a field's scope later.
          </p>
        </div>

        <p className="text-xs text-fg-muted">
          New fields start open to everyone with item access — restrict them per role/team from
          the Permissions column after creating.
        </p>

        {fieldTypeHasOptions(type) && (
          <OptionsEditor
            label="Options"
            value={options}
            onChange={setOptions}
            hint="Allowed values for this select"
            error={optionsError}
          />
        )}

        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={required}
            onChange={(event) => setRequired(event.target.checked)}
            className="size-3.5 accent-accent"
          />
          Required on every item
        </label>

        {(!fieldTypeHasOptions(type) || options.length > 0) && (
          <div>
            <CustomFieldControl
              field={draftDefaultField}
              value={defaultValue}
              onChange={setDefaultValue}
            />
            <p className="mt-1 text-[11px] text-fg-faint">
              Seeded onto new items when this field is left blank on create.
            </p>
          </div>
        )}

        {createField.isError && (
          <p className="text-xs text-red-400">{errorMessage(createField.error)}</p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={createField.isPending || !key || !name}>
            {createField.isPending ? "Creating…" : "Create field"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
