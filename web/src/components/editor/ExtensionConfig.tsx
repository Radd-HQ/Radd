import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal } from "../Modal";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { SelectField } from "../SelectField";
import { pageExtensionsQuery } from "../../lib/queries";
import {
  ExtensionCard,
  lookupPageExtension,
  parseExtensionParams,
} from "../../lib/page-extensions";
import {
  FieldKind,
  fieldsOf,
  initialValues,
  mergeParams,
  unknownKeys,
  type SchemaField,
} from "./extension-schema";
import { ErrorText } from "../ErrorText";

/**
 * Configure one `radd:<name>` block, with a form GENERATED from its schema
 * (RADD-746 / RADD-747).
 *
 * That it is generated is the whole point. A plugin that contributes a
 * `PageExtensionSpec` gets a proper editing experience with no UI code of its
 * own, which is the difference between an extension mechanism people use and
 * one only we can use.
 *
 * The raw-JSON view stays, and is not a debug affordance: an extension whose
 * plugin has been DISABLED has no schema on the wire any more, and a page that
 * still contains its block must remain editable rather than becoming read-only
 * because the form could not be built.
 */
export function ExtensionConfig({
  name,
  body,
  onClose,
  onSave,
}: {
  name: string;
  /** The fence's payload, verbatim. */
  body: string;
  onClose: () => void;
  onSave: (body: string) => void;
}) {
  const { data: specs, isLoading } = useQuery(pageExtensionsQuery);
  const spec = specs?.find((entry) => entry.name === name);
  const fields = useMemo(() => fieldsOf(spec), [spec]);
  const extension = lookupPageExtension(name);

  const parsedOriginal = parseExtensionParams(body);
  const originalParams = parsedOriginal.ok ? parsedOriginal.params : {};

  // The form cannot represent a body it could not parse, and overwriting a typo
  // with defaults would destroy what the author was in the middle of writing.
  // A schema that has not ARRIVED yet is not the same as one that does not
  // exist: the spec list is a query, so deciding this on the first render and
  // freezing it in `useState` left every dialog stuck in the JSON editor.
  const canForm = parsedOriginal.ok && fields.length > 0;
  const [rawOverride, setRawOverride] = useState<boolean | null>(null);
  const raw = rawOverride ?? !canForm;
  const [draft, setDraft] = useState(body);
  const [values, setValues] = useState<Record<string, unknown>>({});
  // Seed once the schema is actually known, for the same reason.
  const [seededFor, setSeededFor] = useState<string | null>(null);
  if (fields.length > 0 && seededFor !== spec?.name) {
    setValues(initialValues(fields, originalParams));
    setSeededFor(spec?.name ?? null);
  }

  const carried = useMemo(() => unknownKeys(originalParams, fields), [originalParams, fields]);

  // What the block WOULD be, for both the preview and the save.
  const nextBody = useMemo(() => {
    if (raw) return draft;
    const merged = mergeParams(originalParams, fields, values);
    return Object.keys(merged).length ? JSON.stringify(merged, null, 2) : "";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw, draft, values, fields]);

  const parsed = parseExtensionParams(nextBody);

  return (
    <Modal title={`Configure radd:${name}`} onClose={onClose} wide>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-3">
          {isLoading ? (
            // Not the JSON editor: showing raw parameters while the schema is
            // still in flight teaches people the form does not exist.
            <p className="text-[13px] text-fg-faint">Loading this extension's options…</p>
          ) : raw ? (
            <>
              <label className="text-xs font-medium text-fg-secondary">Parameters (JSON)</label>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                spellCheck={false}
                rows={10}
                aria-label="Parameters as JSON"
                className="w-full rounded-md border border-subtle bg-surface px-2.5 py-2 font-mono text-[12px] text-heading focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none"
              />
              {!parsed.ok && <ErrorText error={parsed.error} />}
              {!canForm && (
                <p className="text-xs text-fg-muted">
                  {!parsedOriginal.ok
                    ? "These parameters are not valid JSON, so the form cannot be built from them."
                    : `Nothing describes radd:${name} on this instance — the plugin providing it may be disabled.`}
                </p>
              )}
            </>
          ) : (
            fields.map((field) => (
              <Field
                key={field.key}
                field={field}
                value={values[field.key]}
                onChange={(next) => setValues((current) => ({ ...current, [field.key]: next }))}
              />
            ))
          )}

          {carried.length > 0 && !raw && (
            <p className="text-xs text-fg-muted">
              Kept as written: <span className="font-mono">{carried.join(", ")}</span> — not
              described by this extension's schema, so it is carried through untouched.
            </p>
          )}

          {canForm && !isLoading && (
            <button
              type="button"
              onClick={() => {
                // Switching INTO raw hands over what the form currently means, so
                // the two views never disagree about the block.
                if (!raw) setDraft(nextBody);
                setRawOverride(!raw);
              }}
              className="self-start text-[11px] text-fg-muted hover:text-fg hover:underline cursor-pointer"
            >
              {raw ? "Edit as a form" : "Edit as JSON"}
            </button>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-fg-secondary">Preview</p>
          <div className="rounded-md border border-subtle bg-base p-2">
            {!extension ? (
              <p className="text-[13px] text-fg-faint">Nothing is registered for radd:{name}.</p>
            ) : parsed.ok ? (
              extension.render(parsed.params)
            ) : (
              <ExtensionCard>
                <p className="text-[13px] text-fg-faint">Fix the parameters to see a preview.</p>
              </ExtensionCard>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={!parsed.ok} onClick={() => onSave(nextBody)}>
          Save
        </Button>
      </div>
    </Modal>
  );
}

/** One schema property, as the control its type calls for. */
function Field({
  field,
  value,
  onChange,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  const label = field.required ? `${field.label} *` : field.label;

  if (field.kind === FieldKind.enum) {
    return (
      <SelectField
        label={label}
        hint={field.description}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
      >
        {!field.required && <option value="">—</option>}
        {field.options?.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </SelectField>
    );
  }

  if (field.kind === FieldKind.boolean) {
    return (
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => onChange(event.target.checked)}
          className="mt-0.5 accent-[var(--accent-fill)]"
        />
        <span className="flex flex-col">
          <span className="text-xs font-medium text-fg-secondary">{label}</span>
          {field.description && (
            <span className="text-xs text-fg-muted">{field.description}</span>
          )}
        </span>
      </label>
    );
  }

  if (field.kind === FieldKind.markdown) {
    return (
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-fg-secondary">{label}</label>
        <textarea
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
          rows={5}
          aria-label={field.label}
          className="w-full rounded-md border border-subtle bg-surface px-2.5 py-2 text-[13px] text-heading focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none"
        />
        {field.description && <p className="text-xs text-fg-muted">{field.description}</p>}
      </div>
    );
  }

  if (field.kind === FieldKind.integer) {
    return (
      <TextField
        label={label}
        hint={field.description}
        type="number"
        min={field.minimum}
        max={field.maximum}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(event) =>
          // "" must stay undefined, not become NaN or 0: an empty optional
          // number is absent, and `Number("")` is 0, which would write a value
          // the author never chose.
          onChange(event.target.value === "" ? undefined : Number(event.target.value))
        }
      />
    );
  }

  return (
    <TextField
      label={label}
      hint={field.description}
      value={String(value ?? "")}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
