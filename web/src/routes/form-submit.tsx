import { useState, type FormEvent } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, TriangleAlert } from "lucide-react";
import { api, customFieldErrors, errorMessage } from "../lib/api";
import { RoutePath, apiFormSubmitPath } from "../lib/constants";
import { useProjectByKey } from "../lib/hooks";
import { fieldsQuery, formQuery } from "../lib/queries";
import {
  type CustomFieldValue,
  type CustomFields,
  type FieldDef,
  type Form,
  type FormField,
  type Item,
  type FormSubmit as FormSubmitBody,
} from "../lib/types";
import { CustomFieldControl } from "../components/items/CustomFieldsForm";
import { FormAssistPanel } from "../components/forms/FormAssistPanel";
import { FormDescriptionArea } from "../components/forms/PublicFormFields";
import { Button } from "../components/Button";
import { Spinner } from "../components/Spinner";
import { TextField } from "../components/TextField";

/**
 * Public-shaped intake form submit page (spec 20) — route
 * `/p/$projectKey/forms/$formId`. Renders the form (`GET /forms/{id}`) as a title
 * input plus one control per exposed field (by registry type, honouring
 * label/help/required overrides), submits (`POST /forms/{id}/submit`), and shows
 * the created item's key with a link to its issue page. Field 422s render inline.
 */
export function FormSubmitPage() {
  const { projectKey = "", formId = "" } = useParams({ strict: false });
  const { project } = useProjectByKey(projectKey);
  const form = useQuery(formQuery(formId));
  const registry = useQuery(fieldsQuery());

  if (project === undefined || form.isPending) {
    return <Spinner label="Loading form…" />;
  }
  if (!project) {
    return <CenteredNotice message={`Project ${projectKey} not found.`} />;
  }
  if (form.isError) {
    return <CenteredNotice message={`Could not load this form: ${errorMessage(form.error)}`} />;
  }

  return (
    <SubmitForm
      form={form.data}
      projectKey={projectKey}
      registry={registry.data ?? []}
      projectId={project.id}
    />
  );
}

/** Registry field for a key, preferring a project-scoped definition over global. */
function fieldFor(registry: FieldDef[], projectId: string, key: string): FieldDef | undefined {
  const matches = registry.filter((field) => field.key === key);
  return matches.find((field) => field.project_ids.includes(projectId)) ?? matches[0];
}

/** A submitted value counts as absent when null / empty string / empty list. */
function isSet(value: CustomFieldValue): boolean {
  return value !== null && value !== "" && !(Array.isArray(value) && value.length === 0);
}

interface SubmitFormProps {
  form: Form;
  projectKey: string;
  projectId: string;
  registry: FieldDef[];
}

function SubmitForm({ form, projectKey, projectId, registry }: SubmitFormProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<CustomFields>({});
  const [created, setCreated] = useState<Item | null>(null);

  const submit = useMutation({
    mutationFn: () => {
      const body: FormSubmitBody = {
        title: title.trim(),
        description: form.description_enabled ? description : "",
        values: collectValues(values),
      };
      return api.post<Item>(apiFormSubmitPath(form.id), body);
    },
    onSuccess: (item) => setCreated(item),
  });

  const fieldErrors = submit.isError ? customFieldErrors(submit.error) : {};
  // Non-field-scoped failures (disabled form 409, generic 422) surface at the top.
  const generalError =
    submit.isError && Object.keys(fieldErrors).length === 0 ? errorMessage(submit.error) : null;

  const setValue = (key: string, value: CustomFieldValue) =>
    setValues((previous) => ({ ...previous, [key]: value }));

  const descriptionMissing = form.description_enabled && form.description_required && !description.trim();

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && !descriptionMissing) submit.mutate();
  };

  const reset = () => {
    setTitle("");
    setDescription("");
    setValues({});
    setCreated(null);
    submit.reset();
  };

  // @container: the assist panel rides BESIDE the form once the CONTENT area
  // is wide enough — the sidebar collapses, so the viewport width lies.
  return (
    <div className="@container">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-10 @5xl:max-w-none @5xl:flex-row @5xl:items-start @5xl:justify-center">
        <div className="flex w-full max-w-2xl flex-col gap-6">
          <header className="flex flex-col gap-2 border-b border-subtle pb-4">
            <div className="flex items-center gap-2 text-accent-text">
              <ClipboardList size={18} aria-hidden />
              <span className="text-[11px] font-medium uppercase tracking-wide">
                {projectKey} intake form
              </span>
            </div>
            <h1 className="text-xl font-semibold text-heading">{form.name}</h1>
            {form.description && <p className="text-sm text-fg-secondary">{form.description}</p>}
            {!form.enabled && (
              <p className="flex items-center gap-1.5 text-xs text-amber-400">
                <TriangleAlert size={13} aria-hidden />
                This form is disabled — submissions will be rejected.
              </p>
            )}
          </header>

          {created ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5">
              <p className="flex items-center gap-2 text-sm text-emerald-300">
                <CheckCircle2 size={16} aria-hidden />
                Submitted — created{" "}
                <Link
                  to={RoutePath.issue}
                  params={{ itemKey: created.key }}
                  className="font-mono font-semibold text-emerald-200 underline hover:text-emerald-100"
                >
                  {created.key}
                </Link>
              </p>
              <p className="text-[13px] text-fg-secondary">{created.title}</p>
              <Button variant="ghost" onClick={reset}>
                Submit another
              </Button>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="flex flex-col gap-5">
              <TextField
                label={`${form.title_prompt} *`}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Short summary"
                maxLength={500}
                required
                error={fieldErrors.title}
              />

              {/* Submit-time assist (specs 66/106) — inline on narrow
                  containers; the aside takes over once it fits beside. */}
              <div className="@5xl:hidden">
                <FormAssistPanel
                  title={title}
                  description={form.description_enabled ? description : ""}
                  projectId={projectId}
                />
              </div>

              {form.description_enabled && (
                <FormDescriptionArea
                  prompt={form.description_prompt}
                  required={form.description_required}
                  value={description}
                  error={fieldErrors.description}
                  placeholder="Describe the issue — steps, context, what you expected"
                  onChange={setDescription}
                />
              )}

              {form.fields.map((formField) => (
                <FormFieldControl
                  key={formField.field_key}
                  formField={formField}
                  definition={fieldFor(registry, projectId, formField.field_key)}
                  value={values[formField.field_key] ?? null}
                  error={fieldErrors[formField.field_key]}
                  onChange={(value) => setValue(formField.field_key, value)}
                />
              ))}

              {generalError && <p className="text-sm text-red-400">{generalError}</p>}

              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={!title.trim() || descriptionMissing || submit.isPending}
                >
                  {submit.isPending ? "Submitting…" : "Submit"}
                </Button>
              </div>
            </form>
          )}
        </div>

        {!created && (
          <div className="hidden w-80 shrink-0 self-start @5xl:sticky @5xl:top-6 @5xl:block">
            <FormAssistPanel
              title={title}
              description={form.description_enabled ? description : ""}
              projectId={projectId}
            />
          </div>
        )}
      </div>
    </div>
  );
}

interface FormFieldControlProps {
  formField: FormField;
  definition: FieldDef | undefined;
  value: CustomFieldValue;
  error?: string;
  onChange: (value: CustomFieldValue) => void;
}

/** One form field: the registry control (by type) + the form's help text. */
function FormFieldControl({
  formField,
  definition,
  value,
  error,
  onChange,
}: FormFieldControlProps) {
  if (!definition) {
    return (
      <p className="text-xs text-amber-400">
        Field <span className="font-mono">{formField.field_key}</span> is no longer in the registry.
      </p>
    );
  }
  // Synthesize a FieldDef carrying the form's label/required overrides, so the
  // shared CustomFieldControl renders the correct control + required marker.
  const effective: FieldDef = {
    ...definition,
    name: formField.label_override || definition.name,
    required: formField.required,
  };
  return (
    <div className="flex flex-col gap-1">
      <CustomFieldControl field={effective} value={value} error={error} onChange={onChange} />
      {formField.help && <p className="text-xs text-fg-muted">{formField.help}</p>}
    </div>
  );
}

/** Send only values the submitter actually set (keeps false/0; drops blanks). */
function collectValues(values: CustomFields): CustomFields {
  const result: CustomFields = {};
  for (const [key, value] of Object.entries(values)) {
    if (isSet(value)) result[key] = value;
  }
  return result;
}

function CenteredNotice({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <p className="text-sm text-fg-secondary">{message}</p>
    </div>
  );
}
