import { useMemo, useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ExternalLink } from "lucide-react";
import { api } from "../../lib/api";
import { fieldInScope } from "../../lib/field-scope";
import { ApiPath, RoutePath, apiFormPath } from "../../lib/constants";
import { fieldsQuery, queryKeys } from "../../lib/queries";
import {
  type FieldDef,
  type Form,
  type FormCreate,
  type FormDefaults,
  type FormField,
  type FormUpdate,
  type Project,
} from "../../lib/types";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { FormDefaultsEditor, emptyDefaults } from "./FormDefaultsEditor";
import { FormFieldsPicker } from "./FormFieldsPicker";
import { FormSharing } from "./FormSharing";
import { ErrorText } from "../ErrorText";

interface FormEditorProps {
  project: Project;
  /** The form to edit, or null to create a new one. */
  form: Form | null;
  onDone: () => void;
}

/** Registry fields available to a project's forms: global + project-scoped. */
function inProjectScope(fields: FieldDef[], projectId: string): FieldDef[] {
  return fields.filter((field) => fieldInScope(field, projectId));
}

/** Form editor (spec 20): name/description/title prompt, exposed fields, defaults. */
export function FormEditor({ project, form, onDone }: FormEditorProps) {
  const queryClient = useQueryClient();
  const registry = useQuery(fieldsQuery());
  const available = useMemo(
    () => inProjectScope(registry.data ?? [], project.id),
    [registry.data, project.id],
  );

  const [persistedId, setPersistedId] = useState<string | null>(form?.id ?? null);
  const [name, setName] = useState(form?.name ?? "");
  const [description, setDescription] = useState(form?.description ?? "");
  const [titlePrompt, setTitlePrompt] = useState(form?.title_prompt ?? "Summary");
  const [descEnabled, setDescEnabled] = useState(form?.description_enabled ?? true);
  const [descPrompt, setDescPrompt] = useState(form?.description_prompt ?? "Description");
  const [descRequired, setDescRequired] = useState(form?.description_required ?? false);
  // RADD-798 — offer the submitter a picker of THEIR teams. Off by default:
  // turning it on decides who else can open the requests filed here.
  const [teamPicker, setTeamPicker] = useState(form?.team_picker_enabled ?? false);
  const [enabled, setEnabled] = useState(form?.enabled ?? true);
  const [fields, setFields] = useState<FormField[]>(form?.fields ?? []);
  const [defaults, setDefaults] = useState<FormDefaults>(form?.defaults ?? emptyDefaults);

  const canSave =
    name.trim() !== "" && titlePrompt.trim() !== "" && (!descEnabled || descPrompt.trim() !== "");

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        description,
        enabled,
        fields,
        defaults,
        title_prompt: titlePrompt.trim(),
        description_enabled: descEnabled,
        description_prompt: descPrompt.trim() || "Description",
        description_required: descRequired,
        team_picker_enabled: teamPicker,
      };
      return persistedId
        ? api.patch<Form>(apiFormPath(persistedId), payload satisfies FormUpdate)
        : api.post<Form>(ApiPath.forms, {
            ...payload,
            project_id: project.id,
          } satisfies FormCreate);
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.forms(project.id) });
      setPersistedId(saved.id);
    },
  });


  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onDone}
          className="inline-flex items-center gap-1.5 text-xs text-fg-secondary hover:text-heading cursor-pointer"
        >
          <ArrowLeft size={13} aria-hidden />
          Back to forms
        </button>
        {persistedId && (
          <Link
            to={RoutePath.formSubmit}
            params={{ projectKey: project.key, formId: persistedId }}
            className="inline-flex items-center gap-1.5 text-xs text-accent-text hover:text-accent-text"
          >
            <ExternalLink size={13} aria-hidden />
            Open submit page
          </Link>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Form name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Bug report"
          maxLength={200}
          required
        />
        <TextField
          label="Title prompt"
          value={titlePrompt}
          onChange={(event) => setTitlePrompt(event.target.value)}
          placeholder="Summary"
          maxLength={200}
          hint="Label for the submission's title input"
          required
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="form-desc" className="text-xs font-medium text-fg-secondary">
          Description (optional)
        </label>
        <textarea
          id="form-desc"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={2}
          placeholder="Shown at the top of the intake form"
          className="rounded-md border border-strong bg-surface px-2.5 py-1.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3">
        <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={descEnabled}
            onChange={(event) => setDescEnabled(event.target.checked)}
            className="size-4 accent-accent"
          />
          Description area — submitters can write the issue description
        </label>
        {descEnabled && (
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <TextField
                label="Description prompt"
                value={descPrompt}
                onChange={(event) => setDescPrompt(event.target.value)}
                placeholder="Description"
                maxLength={200}
                hint="Label for the submission's description area"
                required
              />
            </div>
            <label className="flex w-fit cursor-pointer items-center gap-2 pb-1 text-[13px] text-fg">
              <input
                type="checkbox"
                checked={descRequired}
                onChange={(event) => setDescRequired(event.target.checked)}
                className="size-4 accent-accent"
              />
              Required
            </label>
          </div>
        )}

        {/* RADD-798 — independent of the description area, so it sits outside
            that conditional: a form with no description can still be shared. */}
        <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={teamPicker}
            onChange={(event) => setTeamPicker(event.target.checked)}
            className="size-4 accent-accent"
          />
          Let submitters share the request with one of their teams
        </label>
        <p className="-mt-2 text-[11px] text-fg-faint">
          The picker offers only teams the submitter belongs to, and everyone in the chosen
          team can then open and follow the request.
        </p>
      </div>

      <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
          className="size-4 accent-accent"
        />
        Enabled (disabled forms reject submissions)
      </label>

      {/* RADD-828: the anonymous public link is GONE — email ingest provisions
          a requester account instead, so every submission passes through the
          permission model. Portal sharing below is the signed-in counterpart. */}
      {persistedId && (
        <FormSharing
          formId={persistedId}
          projectId={project.id}
          shares={form?.shares ?? []}
        />
      )}

      <FormFieldsPicker available={available} value={fields} onChange={setFields} />

      <FormDefaultsEditor
        projectId={project.id}
        value={defaults}
        onChange={setDefaults}
      />

      {save.isError && <ErrorText error={save.error} />}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={!canSave || save.isPending}>
          {save.isPending ? "Saving…" : persistedId ? "Save changes" : "Create form"}
        </Button>
        {save.isSuccess && !save.isPending && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <Check size={13} aria-hidden />
            Saved
          </span>
        )}
      </div>
    </form>
  );
}

