/**
 * The `ai.generate` node's form (spec 120).
 *
 * `SchemaFields` is the fallback for a contributed node with no component of its
 * own, and it is deliberately small — string, enum, number, boolean, and one
 * nested shape. This node's central param is an ARRAY OF OBJECTS whose shape
 * varies per row (an enum field has choices, a text field does not), which is
 * exactly the "anything richer is a sign the plugin should ship its own
 * component" case that docstring names. Meeting it with a generated form would
 * put a JSON textarea where the whole feature is.
 *
 * The rows are also where the node's OUTPUTS come from, so this form is what
 * decides which tokens the picker below offers — which is why the name field
 * validates as it is typed rather than at save: a name that cannot be a token
 * silently produces no output at all.
 */
import { Plus, Trash2 } from "lucide-react";
import { OUTPUT_NAME_RE, generateFields, type GenerateField } from "../../lib/automation-outputs";
import { Button, ButtonVariant } from "../Button";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { OptionsEditor } from "../settings/OptionsEditor";
import { SchemaFields } from "./SchemaFields";

/** Reserved: the node always produces `text`, so a field of that name would
 * collide with it and be dropped by the server. */
const ALWAYS_PRODUCED = "text";
const MAX_FIELDS = 8;

interface GenerateFieldsProps {
  params: Record<string, unknown>;
  /** The node's own JSON Schema, for the prompt + include controls — those ARE
   * shapes `SchemaFields` renders well, and duplicating them here would be two
   * copies of "which parts of the issue does the model see". */
  schema: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
}

export function GenerateFields({ params, schema, onChange }: GenerateFieldsProps) {
  const fields = generateFields(params);
  const setFields = (next: GenerateField[]) => onChange({ ...params, fields: next });
  const patch = (index: number, changes: Partial<GenerateField>) =>
    setFields(fields.map((field, at) => (at === index ? { ...field, ...changes } : field)));

  return (
    <div className="flex flex-col gap-3">
      {/* Prompt + "what the model sees" come from the schema — the generic form
          renders both correctly, and a second copy here would drift. `fields` is
          hidden from it and rendered below. */}
      <SchemaFields
        schema={withoutFields(schema)}
        params={params}
        onChange={(next) => onChange({ ...next, fields: params.fields ?? [] })}
      />

      <div className="flex flex-col gap-2" data-generate-fields>
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
            Values to produce
          </span>
          <span className="text-[11px] text-fg-faint">
            {fields.length}/{MAX_FIELDS}
          </span>
        </div>
        <p className="text-xs text-fg-secondary">
          Each becomes a token below. A field with a list of allowed values is enforced by the
          model's own decoding, so it cannot answer with anything else.
        </p>

        {fields.map((field, index) => (
          <FieldRow
            key={index}
            field={field}
            index={index}
            error={fieldNameError(field.name, fields, index)}
            onPatch={(changes) => patch(index, changes)}
            onRemove={() => setFields(fields.filter((_, at) => at !== index))}
          />
        ))}

        <div>
          <Button
            type="button"
            variant={ButtonVariant.ghost}
            size="sm"
            disabled={fields.length >= MAX_FIELDS}
            onClick={() =>
              setFields([...fields, { name: "", kind: "text", choices: [], description: "" }])
            }
          >
            <Plus size={12} aria-hidden /> Add a value
          </Button>
        </div>
      </div>
    </div>
  );
}

function FieldRow({
  field,
  index,
  error,
  onPatch,
  onRemove,
}: {
  field: GenerateField;
  index: number;
  error: string;
  onPatch: (changes: Partial<GenerateField>) => void;
  onRemove: () => void;
}) {
  return (
    <div
      className="flex flex-col gap-2 rounded-[8px] border border-subtle bg-base/40 p-2"
      data-generate-field={index}
    >
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <TextField
            label="Name"
            value={field.name}
            placeholder="priority"
            error={error || undefined}
            onChange={(event) => onPatch({ name: event.target.value })}
          />
        </div>
        <div className="w-[110px] shrink-0">
          <SelectField
            label="Kind"
            value={field.kind}
            onChange={(event) =>
              onPatch({
                kind: event.target.value,
                // Dropping the choices when the kind goes back to text would
                // lose work someone typed; they are simply not sent.
                choices: field.choices ?? [],
              })
            }
          >
            <option value="text">Text</option>
            <option value="enum">One of…</option>
          </SelectField>
        </div>
        <Button
          type="button"
          variant={ButtonVariant.dangerGhost}
          size="sm"
          aria-label={`Remove value ${index + 1}`}
          onClick={onRemove}
        >
          <Trash2 size={12} aria-hidden />
        </Button>
      </div>
      {field.kind === "enum" && (
        // The same one-row token editor a field definition's options use — a
        // closed set of strings someone types is the same control wherever it
        // appears (RADD-1073 reuses it rather than growing a second).
        <OptionsEditor
          label="Allowed values"
          value={field.choices ?? []}
          onChange={(choices) => onPatch({ choices })}
          hint="The model can only answer with one of these."
        />
      )}
    </div>
  );
}

/** Why this field name cannot be used, or "". The same rule the kernel applies
 * to a node name — both halves of `{{node.field}}` are one identifier. */
function fieldNameError(name: string, fields: GenerateField[], index: number): string {
  const trimmed = name.trim();
  if (!trimmed) return "";
  if (!OUTPUT_NAME_RE.test(trimmed)) {
    return "Lowercase letters, digits and underscores, starting with a letter.";
  }
  if (trimmed === ALWAYS_PRODUCED) return "This node always produces {{….text}}.";
  return fields.some((field, at) => at !== index && field.name.trim() === trimmed)
    ? "Already used by another value."
    : "";
}

/** The node's schema with `fields` removed, so the generic form renders
 * everything it renders well and leaves the array to the rows above. */
function withoutFields(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = { ...((schema.properties ?? {}) as Record<string, unknown>) };
  delete properties.fields;
  return { ...schema, properties };
}
