import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useAttachmentUploader } from "../lib/useAttachmentUploader";
import { ArrowLeft, ClipboardList } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import { RoutePath, apiPortalFormSubmitPath, attachmentUrl } from "../lib/constants";
import { portalFormQuery, portalStagingAreaQuery } from "../lib/queries";
import { AttachmentParentType } from "../lib/types";
import {
  type FormSubmit as FormSubmitBody,
  type PortalForm,
  type PublicSubmitResult,
} from "../lib/types";
import { PublicFormFieldList } from "../components/forms/PublicFormFields";
import { IntakeSubmitShell } from "../components/forms/IntakeSubmitShell";
import { SelectField } from "../components/SelectField";
import { Spinner } from "../components/Spinner";

/**
 * Portal submit page (spec 73) — route `/portal/forms/$formId`, authed. The
 * submit-page body is the shared IntakeSubmitShell (RADD-901); this route
 * contributes the portal specifics: the back link + project chip header,
 * INLINED field definitions (the visitor may not read the registry), the
 * share-with-a-team picker (RADD-798), and pre-item image staging (RADD-800).
 * Submits run server-side as the SYSTEM actor with the visitor as reporter —
 * the share is the grant, no item.create needed. Ineligible forms are a
 * plain 404.
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

  return (
    <IntakeSubmitShell
      form={form}
      projectId={form.project.id}
      successMessage="Submitted — your request is tracked as"
      submitLabel="Submit request"
      resetLabel="Submit another request"
      header={
        <>
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
        </>
      }
      extraControls={
        form.teams.length > 0 ? (
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
        ) : undefined
      }
      onUploadImage={staging.data ? onUploadImage : undefined}
      renderFields={(values, errors, setValue) => (
        <PublicFormFieldList
          fields={form.fields}
          values={values}
          errors={errors}
          onChange={setValue}
        />
      )}
      submit={(payload) => {
        const body: FormSubmitBody = {
          ...payload,
          // RADD-798 — share it with one of MY teams. The server re-checks the
          // membership; this picker only ever offers teams the person is in.
          team_id: teamId || null,
          attachment_ids: attachmentIds,
        };
        return api.post<PublicSubmitResult>(apiPortalFormSubmitPath(form.id), body);
      }}
      onReset={() => {
        setTeamId("");
        setAttachmentIds([]);
      }}
    />
  );
}
