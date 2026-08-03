import { useState, type FormEvent } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useAttachmentUploader } from "../lib/useAttachmentUploader";
import { ArrowLeft, CheckCircle2, ClipboardList } from "lucide-react";
import { api, customFieldErrors, errorMessage } from "../lib/api";
import { RoutePath, apiPortalFormSubmitPath, attachmentUrl } from "../lib/constants";
import { portalFormQuery, portalStagingAreaQuery } from "../lib/queries";
import { AttachmentParentType } from "../lib/types";
import {
  type CustomFields,
  type FormSubmit as FormSubmitBody,
  type PortalForm,
  type PublicSubmitResult,
} from "../lib/types";
import {
  FormDescriptionArea,
  PublicFormFieldList,
  collectValues,
} from "../components/forms/PublicFormFields";
import { FormAssistPanel } from "../components/forms/FormAssistPanel";
import { Button } from "../components/Button";
import { SelectField } from "../components/SelectField";
import { Spinner } from "../components/Spinner";
import { TextField } from "../components/TextField";

/**
 * Portal submit page (spec 73) — route `/portal/forms/$formId`, authed. The
 * PUBLIC form page's title/description/fields layout (definitions arrive
 * inlined — the visitor may not read the registry) PLUS the submit-time
 * assist panel (specs 66/106 — the authenticated deflect + similar endpoints
 * work here). Submits run server-side as the SYSTEM actor with the visitor as
 * reporter — the share is the grant, no item.create needed. Ineligible forms
 * are a plain 404.
 */
export function PortalFormPage() {
  const { formId = "" } = useParams({ strict: false });
  const form = useQuery(portalFormQuery(formId));

  if (form.isPending || form.isError) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-10">
        <BackToPortal />
        {form.isPending ? (
          <Spinner label="Loading form…" />
        ) : (
          <p className="text-sm text-fg-secondary">
            This form isn't available: {errorMessage(form.error)}
          </p>
        )}
      </div>
    );
  }
  return <PortalSubmitForm form={form.data} />;
}

function BackToPortal() {
  return (
    <Link
      to={RoutePath.portal}
      className="inline-flex items-center gap-1.5 text-xs text-fg-secondary hover:text-heading"
    >
      <ArrowLeft size={13} aria-hidden />
      Back to portal
    </Link>
  );
}

function PortalSubmitForm({ form }: { form: PortalForm }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<CustomFields>({});
  const [teamId, setTeamId] = useState("");
  // RADD-800 — files uploaded BEFORE the item exists land on this person's
  // staging area; the submission then names the ones it is claiming, so a
  // second tab's uploads are not dragged in.
  const staging = useQuery(portalStagingAreaQuery);
  const [attachmentIds, setAttachmentIds] = useState<string[]>([]);
  const uploadToStaging = useAttachmentUploader({
    entityType: AttachmentParentType.formSubmission,
    entityId: staging.data?.entity_id ?? "",
  });
  const onUploadImage = async (file: File) => {
    const [attachment] = await uploadToStaging([file]);
    setAttachmentIds((ids) => [...ids, attachment.id]);
    return attachmentUrl(attachment.id);
  };
  const [created, setCreated] = useState<PublicSubmitResult | null>(null);

  const submit = useMutation({
    mutationFn: () => {
      const body: FormSubmitBody = {
        title: title.trim(),
        description: form.description_enabled ? description : "",
        values: collectValues(values),
        // RADD-798 — share it with one of MY teams. The server re-checks the
        // membership; this picker only ever offers teams the person is in.
        team_id: teamId || null,
        attachment_ids: attachmentIds,
      };
      return api.post<PublicSubmitResult>(apiPortalFormSubmitPath(form.id), body);
    },
    onSuccess: (result) => setCreated(result),
  });

  const fieldErrors = submit.isError ? customFieldErrors(submit.error) : {};
  const generalError =
    submit.isError && Object.keys(fieldErrors).length === 0 ? errorMessage(submit.error) : null;

  const descriptionMissing =
    form.description_enabled && form.description_required && !description.trim();

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && !descriptionMissing) submit.mutate();
  };

  const reset = () => {
    setTitle("");
    setDescription("");
    setValues({});
    setTeamId("");
    setAttachmentIds([]);
    setCreated(null);
    submit.reset();
  };

  // @container: the assist panel rides BESIDE the form once the CONTENT area
  // is wide enough — the sidebar collapses, so the viewport width lies.
  return (
    <div className="@container">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-10 @5xl:max-w-none @5xl:flex-row @5xl:items-start @5xl:justify-center">
        <div className="flex w-full max-w-2xl flex-col gap-6">
          <BackToPortal />
          <header className="flex flex-col gap-2 border-b border-subtle pb-4">
            <div className="flex items-center gap-2 text-accent-text">
              <ClipboardList size={18} aria-hidden />
              <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg-secondary">
                {form.project.key}
              </span>
              <span className="text-[11px] font-medium uppercase tracking-wide">
                {form.project.name}
              </span>
            </div>
            <h1 className="text-xl font-semibold text-heading">{form.name}</h1>
            {form.description && <p className="text-sm text-fg-secondary">{form.description}</p>}
          </header>

          {created ? (
            <div className="flex flex-col items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5">
              <p className="flex items-center gap-2 text-sm text-emerald-300">
                <CheckCircle2 size={16} aria-hidden />
                Submitted — your request is tracked as{" "}
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
                Submit another request
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
                  containers; the aside takes over once it fits beside.
                  If the visitor can't read the project's KB it stays empty. */}
              <div className="@5xl:hidden">
                <FormAssistPanel
                  title={title}
                  description={form.description_enabled ? description : ""}
                  projectId={form.project.id}
                />
              </div>

              {form.teams.length > 0 && (
                <SelectField
                  label="Share with a team"
                  value={teamId}
                  onChange={(e) => setTeamId(e.target.value)}
                  hint="Everyone in that team can see this request and follow it. Leave blank to keep it to yourself."
                >
                  <option value="">Just me</option>
                  {form.teams.map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
                </SelectField>
              )}
              {form.description_enabled && (
                <FormDescriptionArea
                  onUploadImage={staging.data ? onUploadImage : undefined}
                  prompt={form.description_prompt}
                  required={form.description_required}
                  value={description}
                  error={fieldErrors.description}
                  placeholder="Describe the issue — steps, context, what you expected"
                  onChange={setDescription}
                />
              )}

              <PublicFormFieldList
                fields={form.fields}
                values={values}
                errors={fieldErrors}
                onChange={(key, value) =>
                  setValues((previous) => ({ ...previous, [key]: value }))
                }
              />

              {generalError && <p className="text-sm text-red-400">{generalError}</p>}

              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={!title.trim() || descriptionMissing || submit.isPending}
                >
                  {submit.isPending ? "Submitting…" : "Submit request"}
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
              projectId={form.project.id}
            />
          </div>
        )}
      </div>
    </div>
  );
}
