import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { customFieldErrors, errorMessage } from "../../lib/api";
import { RoutePath } from "../../lib/constants";
import type { CustomFieldValue, CustomFields } from "../../lib/types";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";
import { TextField } from "../TextField";
import { FormAssistPanel } from "./FormAssistPanel";
import { FormDescriptionArea, collectValues } from "./PublicFormFields";

/** The subset of a form both submit pages share (Form and PortalForm each carry it). */
export interface IntakeFormShape {
  name: string;
  description: string | null;
  title_prompt: string;
  description_enabled: boolean;
  description_prompt: string;
  description_required: boolean;
}

/** What the caller's submit resolves with — enough for the success panel. */
export interface IntakeSubmitResult {
  key: string;
  title: string;
}

interface IntakeSubmitShellProps {
  form: IntakeFormShape;
  /** Scopes the KB-deflection assist panels (specs 66/106). */
  projectId: string;
  /** Page chrome above the form header (back link, project chip, notices). */
  header: ReactNode;
  /** "Submitted — created" / "Submitted — your request is tracked as". */
  successMessage: string;
  submitLabel: string;
  resetLabel: string;
  /** The per-page field list — registry-driven on the project page, inlined
   * definitions on the portal. Values state lives here; the renderer reads it. */
  renderFields: (
    values: CustomFields,
    errors: Record<string, string | undefined>,
    setValue: (key: string, value: CustomFieldValue) => void,
  ) => ReactNode;
  /** Extra controls between title and description (the portal's team picker). */
  extraControls?: ReactNode;
  /** Pre-item image staging for the description editor (portal only). */
  onUploadImage?: (file: File) => Promise<string>;
  /** Build the request from the shared payload — the caller adds its own extras
   * (team, staged attachment ids) and names the endpoint. */
  submit: (payload: {
    title: string;
    description: string;
    values: CustomFields;
  }) => Promise<IntakeSubmitResult>;
  /** Clear caller-held extras when "Submit another" resets the shared state. */
  onReset?: () => void;
}

/**
 * The intake submit page, shared (RADD-901): `routes/form-submit.tsx` and
 * `routes/portal-form.tsx` had drifted ~150 identical lines — header layout,
 * title field, description area, assist-panel placement, error split, the
 * success panel. This shell owns that; the two routes keep only what actually
 * differs (auth context, field source, team/attachment extras, wording).
 */
export function IntakeSubmitShell({
  form,
  projectId,
  header,
  successMessage,
  submitLabel,
  resetLabel,
  renderFields,
  extraControls,
  onUploadImage,
  submit,
  onReset,
}: IntakeSubmitShellProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<CustomFields>({});
  const [created, setCreated] = useState<IntakeSubmitResult | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      submit({
        title: title.trim(),
        description: form.description_enabled ? description : "",
        values: collectValues(values),
      }),
    onSuccess: (result) => setCreated(result),
  });

  const fieldErrors = mutation.isError ? customFieldErrors(mutation.error) : {};
  // Non-field-scoped failures (disabled form 409, generic 422) surface at the top.
  const generalError =
    mutation.isError && Object.keys(fieldErrors).length === 0
      ? errorMessage(mutation.error)
      : null;

  const setValue = (key: string, value: CustomFieldValue) =>
    setValues((previous) => ({ ...previous, [key]: value }));

  const descriptionMissing =
    form.description_enabled && form.description_required && !description.trim();

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && !descriptionMissing) mutation.mutate();
  };

  const reset = () => {
    setTitle("");
    setDescription("");
    setValues({});
    setCreated(null);
    mutation.reset();
    onReset?.();
  };

  // @container: the assist panel rides BESIDE the form once the CONTENT area
  // is wide enough — the sidebar collapses, so the viewport width lies.
  return (
    <div className="@container">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-10 @5xl:max-w-none @5xl:flex-row @5xl:items-start @5xl:justify-center">
        <div className="flex w-full max-w-2xl flex-col gap-6">
          {header}

          {created ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-status-success/30 bg-status-success/5 p-5">
              <p className="flex items-center gap-2 text-sm text-status-success-ink">
                <CheckCircle2 size={16} aria-hidden />
                {successMessage}{" "}
                <Link
                  to={RoutePath.issue}
                  params={{ itemKey: created.key }}
                  className="font-mono font-semibold underline hover:text-status-success"
                >
                  {created.key}
                </Link>
              </p>
              <p className="text-[13px] text-fg-secondary">{created.title}</p>
              <Button variant="ghost" onClick={reset}>
                {resetLabel}
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

              {extraControls}

              {form.description_enabled && (
                <FormDescriptionArea
                  onUploadImage={onUploadImage}
                  prompt={form.description_prompt}
                  required={form.description_required}
                  value={description}
                  error={fieldErrors.description}
                  placeholder="Describe the issue — steps, context, what you expected"
                  onChange={setDescription}
                />
              )}

              {renderFields(values, fieldErrors, setValue)}

              {generalError && <ErrorText size="sm" error={generalError} />}

              <div className="flex justify-end">
                <Button type="submit" disabled={!title.trim() || descriptionMissing || mutation.isPending}>
                  {mutation.isPending ? "Submitting…" : submitLabel}
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
