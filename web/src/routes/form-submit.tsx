import { useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, TriangleAlert } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import { apiFormSubmitPath } from "../lib/constants";
import { useProjectByKey } from "../lib/hooks";
import { fieldsQuery, formQuery } from "../lib/queries";
import {
  type CustomFieldValue,
  type FieldDef,
  type Form,
  type FormField,
  type Item,
  type FormSubmit as FormSubmitBody,
} from "../lib/types";
import { CustomFieldControl } from "../components/items/CustomFieldsForm";
import { IntakeSubmitShell } from "../components/forms/IntakeSubmitShell";
import { Spinner } from "../components/Spinner";

/**
 * Public-shaped intake form submit page (spec 20) — route
 * `/p/$projectKey/forms/$formId`. The submit-page body (title, description,
 * assist panels, errors, success) is the shared IntakeSubmitShell (RADD-901);
 * this route contributes what is specific to it: the intake header with the
 * disabled-form warning, and REGISTRY-driven field controls (`GET /fields`,
 * honouring label/help/required overrides). Field 422s render inline.
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

interface SubmitFormProps {
  form: Form;
  projectKey: string;
  projectId: string;
  registry: FieldDef[];
}

function SubmitForm({ form, projectKey, projectId, registry }: SubmitFormProps) {
  return (
    <IntakeSubmitShell
      form={form}
      projectId={projectId}
      successMessage="Submitted — created"
      submitLabel="Submit"
      resetLabel="Submit another"
      header={
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
            <p className="flex items-center gap-1.5 text-xs text-status-warning-ink">
              <TriangleAlert size={13} aria-hidden />
              This form is disabled — submissions will be rejected.
            </p>
          )}
        </header>
      }
      renderFields={(values, errors, setValue) =>
        form.fields.map((formField) => (
          <FormFieldControl
            key={formField.field_key}
            formField={formField}
            definition={fieldFor(registry, projectId, formField.field_key)}
            value={values[formField.field_key] ?? null}
            error={errors[formField.field_key]}
            onChange={(value) => setValue(formField.field_key, value)}
          />
        ))
      }
      submit={(payload) =>
        api.post<Item>(apiFormSubmitPath(form.id), payload satisfies FormSubmitBody)
      }
      // Spec 119 — off the form's OWN render payload, like the portal's. It is
      // the only answer that knows the TYPE this form will submit: the form's
      // `type_name` default, or the project's default type when it names none,
      // both resolved server-side (`forms.service.effective_type_id`). Asking
      // the items context endpoint from here meant passing no type at all, so a
      // type-targeted binding stayed invisible until the 422.
      validation={form.validation ?? undefined}
      labelForField={(key) =>
        key.startsWith("cf.")
          ? fieldFor(registry, projectId, key.slice(3))?.name ?? key.slice(3)
          : undefined
      }
    />
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
      <p className="text-xs text-status-warning-ink">
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

function CenteredNotice({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <p className="text-sm text-fg-secondary">{message}</p>
    </div>
  );
}
