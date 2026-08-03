import {
  type CustomFieldValue,
  type CustomFields,
  type FieldDef,
  type PublicFormField,
} from "../../lib/types";
import { CustomFieldControl } from "../items/CustomFieldsForm";
import { LazyRichEditor } from "../editor/LazyRichEditor";

/**
 * Shared rendering for the TRIMMED form payloads (spec 62 public tokened page,
 * spec 73 portal page): field definitions arrive inlined — the visitor may not
 * read the registry — so each is synthesized into a FieldDef for the shared
 * CustomFieldControl, plus the description-area editor every form page mounts.
 */

/** FieldDef synthesized from the inlined public definition, so the shared
 * CustomFieldControl renders the right widget (ids/grants don't apply here). */
export function toFieldDef(field: PublicFormField): FieldDef {
  return {
    id: field.field_key,
    project_ids: [],
    key: field.field_key,
    name: field.label,
    type: field.type,
    required: field.required,
    options: field.options,
    indexed: false,
    ai_visible: true,
    source: "user",
    display: field.display,
    default_value: field.default_value,
    restricted: false,
    created_at: "",
  };
}

/** A submitted value counts as absent when null / empty string / empty list. */
function isSet(value: CustomFieldValue): boolean {
  return value !== null && value !== "" && !(Array.isArray(value) && value.length === 0);
}

/** Send only values the submitter actually set (keeps false/0; drops blanks). */
export function collectValues(values: CustomFields): CustomFields {
  const result: CustomFields = {};
  for (const [key, value] of Object.entries(values)) {
    if (isSet(value)) result[key] = value;
  }
  return result;
}

interface PublicFormFieldListProps {
  fields: PublicFormField[];
  values: CustomFields;
  errors: Record<string, string | undefined>;
  onChange: (key: string, value: CustomFieldValue) => void;
}

/** The exposed fields, one control + help line each (inline 422s per field). */
export function PublicFormFieldList({ fields, values, errors, onChange }: PublicFormFieldListProps) {
  return (
    <>
      {fields.map((field) => (
        <div key={field.field_key} className="flex flex-col gap-1">
          <CustomFieldControl
            field={toFieldDef(field)}
            value={values[field.field_key] ?? null}
            error={errors[field.field_key]}
            onChange={(value) => onChange(field.field_key, value)}
          />
          {field.help && <p className="text-xs text-fg-muted">{field.help}</p>}
        </div>
      ))}
    </>
  );
}

interface FormDescriptionAreaProps {
  prompt: string;
  required: boolean;
  value: string;
  error?: string;
  placeholder: string;
  onChange: (value: string) => void;
  /** The public tokened page has no session — the editor mounts formatting
   * only (no AI gate probes, no @/# lookups). See RichEditor's `anonymous`. */
  anonymous?: boolean;
  /** Upload a pasted/dropped image and return its URL. Omit to disable image
   *  insertion entirely — the anonymous path (RADD-802). */
  onUploadImage?: (file: File) => Promise<string>;
}

/** The ITEM-description editor (distinct from the form's own blurb): the same
 * rich markdown editor as the rest of the app — descriptions land in
 * `ItemCreate.description`, which is markdown everywhere.
 *
 * `onUploadImage` arrives on the AUTHENTICATED portal path (RADD-800): the file
 * goes to the submitter's staging area and is repointed onto the item at
 * submit. Omitted on the anonymous public form, which has no session to upload
 * with — RADD-802 — and the editor then hides its file button and offers a URL
 * field instead, so nothing dead-ends. */
export function FormDescriptionArea({
  prompt,
  required,
  value,
  error,
  placeholder,
  onChange,
  anonymous = false,
  onUploadImage,
}: FormDescriptionAreaProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-fg-secondary">
        {prompt}
        {required && " *"}
      </span>
      <LazyRichEditor
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        anonymous={anonymous}
        onUploadImage={onUploadImage}
        className="[&_.ProseMirror]:min-h-[8rem]"
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
