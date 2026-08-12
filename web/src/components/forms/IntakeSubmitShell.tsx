import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import {
  customFieldErrors,
  errorMessage,
  findingsByField,
  validationFindings,
  validationMode,
} from "../../lib/api";
import { RoutePath } from "../../lib/constants";
import { IntakeCommit, ValidationMode } from "../../lib/types";
import type {
  CustomFieldValue,
  CustomFields,
  Finding,
  IntakeCommitValue,
  ValidationModeValue,
} from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { ErrorText } from "../ErrorText";
import { TextField } from "../TextField";
import { FindingsPanel } from "../items/FindingsPanel";
import { FormAssistPanel } from "./FormAssistPanel";
import { FormDescriptionArea, collectValues } from "./PublicFormFields";

/** How a finding names a custom field (spec 119) — mirrors the server. */
const CUSTOM_FIELD_PREFIX = "cf.";

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
   * (team, staged attachment ids) and names the endpoint.
   *
   * `commit` rides along rather than being a second submit function: the two
   * presses ("submit" and "submit anyway") are the same request with one field
   * different, and two callbacks would let a page implement one of them and not
   * the other. */
  submit: (payload: {
    title: string;
    description: string;
    values: CustomFields;
    commit: IntakeCommitValue;
  }) => Promise<IntakeSubmitResult>;
  /** Whether intake validation governs this form (spec 119), and how hard. Both
   * pages read it off what they already fetched — the project page from the
   * items context endpoint, the portal from the form's own render payload,
   * which is authorized by the SHARE rather than by an item atom. */
  validation?: { governed: boolean; mode: ValidationModeValue | null };
  /** A finding's field key as a person would name it (the page knows its own
   * controls). Optional — an unlabelled finding still reads fine. */
  labelForField?: (field: string) => string | undefined;
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
  validation,
  labelForField,
  onReset,
}: IntakeSubmitShellProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<CustomFields>({});
  const [created, setCreated] = useState<IntakeSubmitResult | null>(null);
  // WHAT THE CHECKS SAID last time (spec 119) — findings and the mode they were
  // decided under, in one piece of state.
  //
  // A submit path answers with an item OR with the spec-119 422, and that body
  // carries the mode as well as the findings. Reading the mode off the render
  // payload while reading the list off the response renders one answer's
  // findings under another answer's rules — and the payload was fetched before
  // anything was submitted, so a binding added since is not in it.
  const [verdict, setVerdict] = useState<{
    findings: Finding[];
    mode: ValidationModeValue | null;
  }>({ findings: [], mode: null });
  const findings = verdict.findings;
  const governed = validation?.governed ?? false;
  const mode = verdict.mode ?? validation?.mode ?? ValidationMode.advisory;

  const mutation = useMutation({
    mutationFn: (commit: IntakeCommitValue) =>
      submit({
        title: title.trim(),
        description: form.description_enabled ? description : "",
        values: collectValues(values),
        commit,
      }),
    onSuccess: (result) => {
      setVerdict({ findings: [], mode: null });
      setCreated(result);
    },
    // Only an answer ABOUT the draft touches the list. A 409 refusing "submit
    // anyway" under a required binding carries no findings of its own, and
    // blanking on it made the panel disappear at the moment it was being argued
    // with — the same for a 503 while the checks are down, or a field-registry
    // 422 about one value.
    onError: (error) => {
      const refused = validationFindings(error);
      const answered = validationMode(error);
      if (refused.length > 0 || answered) {
        setVerdict((previous) => ({
          findings: refused.length > 0 ? refused : previous.findings,
          mode: answered ?? previous.mode,
        }));
      }
    },
  });

  const fieldErrors = mutation.isError ? customFieldErrors(mutation.error) : {};
  const findingErrors = findingsByField(findings);
  // Findings addressed at a control join the registry's per-field errors — the
  // field renderers already take a `Record<key, message>` and need no second
  // concept. `cf.<key>` is stripped, because a form keys by the bare key.
  const controlErrors: Record<string, string | undefined> = { ...fieldErrors };
  for (const [key, message] of Object.entries(findingErrors)) {
    const bare = key.startsWith(CUSTOM_FIELD_PREFIX)
      ? key.slice(CUSTOM_FIELD_PREFIX.length)
      : key;
    controlErrors[bare] ??= message;
  }
  // Non-field-scoped failures (disabled form 409, "submit anyway" refused under
  // a required binding, the checks unavailable) surface at the top — but never a
  // findings 422, which the panel below says better.
  //
  // Judged on THIS error's shape, not on whether findings are on screen: a 409
  // arrives while the panel is full, and testing the list meant the one press
  // that could be refused for a reason of its own said nothing at all.
  const generalError =
    mutation.isError &&
    Object.keys(fieldErrors).length === 0 &&
    validationFindings(mutation.error).length === 0
      ? errorMessage(mutation.error)
      : null;

  const setValue = (key: string, value: CustomFieldValue) =>
    setValues((previous) => ({ ...previous, [key]: value }));

  const descriptionMissing =
    form.description_enabled && form.description_required && !description.trim();

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && !descriptionMissing) mutation.mutate(IntakeCommit.pass);
  };

  const reset = () => {
    setTitle("");
    setDescription("");
    setValues({});
    setCreated(null);
    setVerdict({ findings: [], mode: null });
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
                error={controlErrors.title}
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
                  error={controlErrors.description}
                  placeholder="Describe the issue — steps, context, what you expected"
                  onChange={setDescription}
                />
              )}

              {renderFields(values, controlErrors, setValue)}

              {/* Every finding, including ones already against a control: one
                  may be attached to a field further up the page. */}
              <FindingsPanel findings={findings} mode={mode} labelFor={labelForField} />

              {generalError && <ErrorText size="sm" error={generalError} />}

              <div className="flex justify-end gap-2">
                {/* Advisory only — the server answers 409 to a `commit: always`
                    under a required binding, and an affordance that is refused
                    on press is worse than one that is absent. */}
                {findings.length > 0 && mode === ValidationMode.advisory && (
                  <Button
                    variant={ButtonVariant.secondary}
                    onClick={() => mutation.mutate(IntakeCommit.always)}
                    disabled={!title.trim() || descriptionMissing || mutation.isPending}
                  >
                    Submit anyway
                  </Button>
                )}
                <Button type="submit" disabled={!title.trim() || descriptionMissing || mutation.isPending}>
                  {mutation.isPending
                    ? governed
                      ? "Checking…"
                      : "Submitting…"
                    : submitLabel}
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
