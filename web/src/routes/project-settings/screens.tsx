import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import {
  effectiveScreenQuery,
  fieldsQuery,
  issueTypesQuery,
  projectByIdQuery,
} from "../../lib/queries";
import {
  Permission,
  ScreenPlacement,
  type ScreenPlacementValue,
  type EffectiveFieldRow,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { SelectField } from "../../components/SelectField";
import { Spinner } from "../../components/Spinner";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { ErrorText } from "../../components/ErrorText";

const BUILTIN_LABELS: Record<string, string> = {
  assignee: "Assignee",
  reporter: "Reporter",
  team: "Team",
  cycle: "Cycle",
  release: "Release",
  start_date: "Start date",
  target_date: "Target date",
  labels: "Labels",
  sla: "SLA timers",
  time_tracking: "Time tracking",
  points: "Points",
};

const PLACEMENTS: readonly { value: ScreenPlacementValue; label: string }[] = [
  { value: ScreenPlacement.primary, label: "Shown" },
  { value: ScreenPlacement.secondary, label: "Collapsed" },
  { value: ScreenPlacement.hidden, label: "Hidden" },
];

const PROJECT_DEFAULT = ""; // the issue-type <select> sentinel for the project default

/**
 * Screens editor (spec 53): arrange which fields are shown / collapsed / hidden in
 * the issue view, per project and optionally per issue type. "Collapsed" fields sit
 * behind the peek panel's "More fields" toggle. A screen falls back to the project
 * default, then the built-in defaults.
 */
export function ScreensSettingsPage({ projectId }: { projectId: string | undefined }) {
  const perms = usePermissions();
  // RADD-810: project.manage is project-scoped and a project IS in context —
  // resolve against it, so a per-project manager can edit their screens.
  const projectQuery = useQuery(projectByIdQuery(projectId ?? ""));
  const contextProject = projectQuery.data;
  const types = useQuery({ ...issueTypesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const fields = useQuery(fieldsQuery());
  const [typeId, setTypeId] = useState<string>(PROJECT_DEFAULT);

  const fieldNames = new Map((fields.data ?? []).map((f) => [f.key, f.name] as const));
  const labelFor = (field: string): string =>
    field.startsWith("cf:")
      ? (fieldNames.get(field.slice(3)) ?? field.slice(3))
      : (BUILTIN_LABELS[field] ?? field);

  if (projectQuery.isError) return <SettingsPage history={{ entities: ["screen"], projectId }} title="Screens"><QueryError label="project" error={projectQuery.error} /></SettingsPage>;
  if (projectId && projectQuery.isPending) return <SettingsPage history={{ entities: ["screen"], projectId }} title="Screens"><Spinner label="Loading project…" /></SettingsPage>;
  if (!projectId || !contextProject) return <SettingsPage history={{ entities: ["screen"], projectId }} title="Screens"><p className="text-sm text-fg-muted">Project not found.</p></SettingsPage>;

  return (
    <SettingsPage history={{ entities: ["screen"], projectId }}
      title="Screens"
      description="Arrange the issue view per issue type: show a field, collapse it under “More fields”, or hide it. Hiding never deletes a value or changes validation, and state, type and priority always show. A type without its own screen uses the project default."
    >
      <div className="mb-4 max-w-xs">
        <SelectField
          label="Issue type"
          value={typeId}
          onChange={(event) => setTypeId(event.target.value)}
          hint="Configure the project default, or override a specific type."
        >
          <option value={PROJECT_DEFAULT}>Project default (all types)</option>
          {(types.data ?? []).map((type) => (
            <option key={type.id} value={type.id}>
              {type.name}
            </option>
          ))}
        </SelectField>
      </div>

      <ScreenEditor
        key={`${projectId}:${typeId}`}
        projectId={projectId}
        issueTypeId={typeId || null}
        labelFor={labelFor}
        canManage={perms.project(contextProject, Permission.projectManage)}
      />
    </SettingsPage>
  );
}

interface DraftRow {
  field: string;
  placement: ScreenPlacementValue;
  custom: boolean;
}

function ScreenEditor({
  projectId,
  issueTypeId,
  labelFor,
  canManage,
}: {
  projectId: string;
  issueTypeId: string | null;
  labelFor: (field: string) => string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const effective = useQuery(effectiveScreenQuery(projectId, issueTypeId));
  const [draft, setDraft] = useState<DraftRow[] | null>(null);

  // Seed the editor from the resolved layout the first time it loads (or when the
  // scope changes — the parent's `key` remounts this component, resetting `draft`).
  useEffect(() => {
    if (effective.data && draft === null) {
      setDraft(
        effective.data.fields.map((row: EffectiveFieldRow) => ({
          field: row.field,
          placement: row.placement,
          custom: row.custom,
        })),
      );
    }
  }, [effective.data, draft]);

  const save = useMutation({
    mutationFn: (rows: DraftRow[]) =>
      api.put(ApiPath.screens, {
        project_id: projectId,
        issue_type_id: issueTypeId,
        fields: rows.map(({ field, placement }) => ({ field, placement })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["screen-effective"] });
    },
  });

  const reset = useMutation({
    mutationFn: () =>
      api.put(ApiPath.screens, { project_id: projectId, issue_type_id: issueTypeId, fields: [] }),
    onSuccess: () => {
      setDraft(null);
      queryClient.invalidateQueries({ queryKey: ["screen-effective"] });
    },
  });

  if (effective.isPending || draft === null) return <Spinner label="Loading layout…" />;
  if (effective.isError) {
    return <QueryError label="the layout" error={effective.error} />;
  }

  const setPlacement = (index: number, placement: ScreenPlacementValue) =>
    setDraft((rows) => rows!.map((row, i) => (i === index ? { ...row, placement } : row)));
  const move = (index: number, delta: number) =>
    setDraft((rows) => {
      const next = [...rows!];
      const target = index + delta;
      if (target < 0 || target >= next.length) return next;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });

  return (
    <div>
      <ul className="flex flex-col divide-y divide-subtle rounded-lg border border-subtle">
        {draft.map((row, index) => (
          <li key={row.field} className="flex items-center gap-3 px-3 py-2">
            <div className="flex flex-col">
              <button
                type="button"
                disabled={index === 0 || !canManage}
                onClick={() => move(index, -1)}
                aria-label={`Move ${labelFor(row.field)} up`}
                className="text-fg-faint hover:text-fg disabled:opacity-30 disabled:hover:text-fg-faint cursor-pointer disabled:cursor-default"
              >
                <ChevronUp size={13} />
              </button>
              <button
                type="button"
                disabled={index === draft.length - 1 || !canManage}
                onClick={() => move(index, 1)}
                aria-label={`Move ${labelFor(row.field)} down`}
                className="text-fg-faint hover:text-fg disabled:opacity-30 disabled:hover:text-fg-faint cursor-pointer disabled:cursor-default"
              >
                <ChevronDown size={13} />
              </button>
            </div>
            <span className="min-w-0 flex-1 truncate text-[13px] text-heading">
              {labelFor(row.field)}
              {row.custom && (
                <span className="ml-2 rounded bg-elevated px-1 text-[10px] uppercase text-fg-muted">
                  custom
                </span>
              )}
            </span>
            <div className="inline-flex shrink-0 gap-0.5 rounded-md border border-subtle p-0.5">
              {PLACEMENTS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  disabled={!canManage}
                  aria-pressed={row.placement === option.value}
                  onClick={() => setPlacement(index, option.value)}
                  className={
                    "rounded px-2 py-0.5 text-[11px] font-medium cursor-pointer disabled:cursor-default " +
                    (row.placement === option.value
                      ? "bg-elevated text-heading"
                      : "text-fg-muted hover:text-fg")
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>

      {canManage && (
        <div className="mt-4 flex items-center gap-2">
          <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save layout"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            title="Clear this screen — the scope falls back to the project default, then built-in defaults."
          >
            Reset to default
          </Button>
          {save.isSuccess && !save.isPending && (
            <span className="text-xs text-emerald-400">Saved.</span>
          )}
        </div>
      )}
      {(save.isError || reset.isError) && (
        <ErrorText className="mt-2" error={save.error ?? reset.error} />
      )}
    </div>
  );
}
