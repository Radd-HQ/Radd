import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Save, Wand2 } from "lucide-react";
import { api, Button, ErrorText, QueryError, Spinner, useContributedQuery } from "@radd/plugin-sdk";
import type { FieldDef } from "@radd-plugin-ui/fields/types";
import {
  JiraPath,
  jiraKeys,
  planQuery,
  targetIssueTypesQuery,
  targetProjectQuery,
  targetStatesQuery,
  targetTeamsQuery,
} from "./api";
import { ComponentsTable, LinkTypesTable, SprintsTable, VersionsTable } from "./CatalogTables";
import { FieldsTable } from "./FieldsTable";
import { ImportOptions, PlanTabs, ValidationSummary } from "./PlanParts";
import {
  FieldBand,
  type FieldMappingEntry,
  type JiraPlan,
  type PlanMappings,
  type PlanOptions,
  type PlanSection,
  type PlanValidation,
  type UserMapping,
} from "./plan-types";
import { RunKind, type JiraRun, type RunKindValue } from "./types";
import { UsersTable } from "./UsersTable";
import { IssueTypesTable, PrioritiesTable, StatusesTable } from "./VocabTables";

/**
 * The mapping step (spec 100): one tab per inbound vocabulary, every row a
 * decision, everything unused collapsed and already ignored.
 *
 * Then the three deliberate actions the old wizard had no equivalent for —
 * PROVISION real targets you can look at, DRY RUN against them, and only then
 * import.
 */
export function PlanEditor({
  planId,
  onRunStarted,
  focus,
}: {
  planId: string;
  onRunStarted: (run: JiraRun) => void;
  /** Open this tab (and highlight this row) — set when a run problem points here. */
  focus?: { section: string; mappingKey: string; nonce: number } | null;
}) {
  const queryClient = useQueryClient();
  const plan = useQuery(planQuery(planId));
  // The fields plugin owns its catalog and contributes it as a query source.
  const fields = useContributedQuery<FieldDef[]>("fields.catalog");
  const targetKey = plan.data?.radd_project_key ?? "";
  const targetProject = useQuery({ ...targetProjectQuery(targetKey), enabled: Boolean(targetKey) && !plan.data?.radd_project_id });
  const projectId = plan.data?.radd_project_id ?? targetProject.data?.id ?? "";
  const states = useQuery(targetStatesQuery(projectId));
  const types = useQuery(targetIssueTypesQuery(projectId));
  const teams = useQuery(targetTeamsQuery());
  const existingKeys = useMemo(() => (fields.data ?? []).map(f => f.key), [fields.data]);
  const fieldLabels = useMemo(() => Object.fromEntries((fields.data ?? []).map(f => [f.key, `${f.name} (${f.key})`])), [fields.data]);
  const existingOptions = useMemo(() => Object.fromEntries((fields.data ?? []).map(f => [f.key, f.options ?? []])), [fields.data]);
  const nativeOptions = useMemo(() => ({ team: (teams.data ?? []).map(t => t.name) }), [teams.data]);
  const [draft, setDraft] = useState<PlanMappings | null>(null);
  const [options, setOptions] = useState<PlanOptions | null>(null);
  const [tab, setTab] = useState<PlanSection>("fields");
  const [highlight, setHighlight] = useState("");
  const [validation, setValidation] = useState<PlanValidation | null>(null);

  // Seed the editor once the plan lands, and again if a different plan opens.
  useEffect(() => {
    if (plan.data) {
      setDraft(plan.data.mappings);
      setOptions(plan.data.options);
      setValidation(null);
    }
  }, [plan.data?.id, plan.data?.provisioned_at]);

  // A problem's "Fix in …" jumps here. The nonce lets the same target be
  // re-selected after the user has navigated away from it.
  useEffect(() => {
    if (!focus?.section) return;
    setTab(focus.section as PlanSection);
    setHighlight(focus.mappingKey);
  }, [focus?.nonce]);

  useEffect(() => { setValidation(null); }, [draft, options]);
  useEffect(() => {
    if (focus && draft) document.getElementById("jira-mappings")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus?.nonce, Boolean(draft)]);

  const save = useMutation({
    mutationFn: () => api.patch<JiraPlan>(`${JiraPath.plans}/${planId}`, { mappings: draft, options }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: jiraKeys.plan(planId) });
      void queryClient.invalidateQueries({ queryKey: jiraKeys.plans });
    },
  });

  const validate = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<PlanValidation>(`${JiraPath.plans}/${planId}/validate`, {});
    },
    onSuccess: setValidation,
  });

  const start = useMutation({
    mutationFn: async (kind: RunKindValue) => {
      await save.mutateAsync();
      return api.post<JiraRun>(JiraPath.runs, { plan_id: planId, kind });
    },
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: jiraKeys.runs });
      void queryClient.invalidateQueries({ queryKey: jiraKeys.plan(planId) });
      onRunStarted(run);
    },
  });

  /** Patch one row of one mapping table. */
  const patch = useCallback(<K extends PlanSection>(key: K, index: number, changes: Partial<PlanMappings[K][number]>) =>
      setDraft((current) => {
        if (!current) return current;
        const rows = [...current[key]] as PlanMappings[K];
        rows[index] = { ...rows[index], ...changes };
        return { ...current, [key]: rows };
      }), []);

  const patchFields = useCallback((index: number, changes: Partial<FieldMappingEntry>) => patch("fields", index, changes), [patch]);

  if (plan.isError) return <QueryError label="import plan" error={plan.error} />;
  if (plan.isPending || !draft || !options) return <Spinner label="Loading the plan…" />;
  const busy = save.isPending || validate.isPending || start.isPending;

  const bulkUsers = (apply: (row: UserMapping, index: number) => Partial<UserMapping> | null) =>
    setDraft((current) =>
      current
        ? {
            ...current,
            users: current.users.map((row, index) => {
              const changes = apply(row, index);
              return changes ? { ...row, ...changes } : row;
            }),
          }
        : current,
    );

  const problemsFor = (section: PlanSection) =>
    (validation?.problems ?? []).filter((p) => p.section === section);
  const counted = (key: PlanSection) =>
    key === "fields"
      ? draft.fields.filter((f) => f.band === FieldBand.in_use).length
      : (draft[key] as { count?: number }[]).filter((r) => (r.count ?? 0) > 0).length;

  return (
    <div className="flex flex-col gap-4">
      <PlanTabs active={tab} onSelect={setTab} counted={counted} problems={(key) => problemsFor(key).length} />

      <div>
        {tab === "fields" && (
          <FieldsTable
            rows={draft.fields}
            existingKeys={existingKeys}
            fieldLabels={fieldLabels}
            nativeOptions={nativeOptions}
            existingOptions={existingOptions}
            problems={problemsFor("fields")}
            highlight={highlight}
            onChange={patchFields}
          />
        )}
        {tab === "issue_types" && (
          <IssueTypesTable types={types.data ?? []} rows={draft.issue_types} onChange={(index, changes) => patch("issue_types", index, changes)} />
        )}
        {tab === "statuses" && (
          <StatusesTable states={states.data ?? []} rows={draft.statuses} onChange={(index, changes) => patch("statuses", index, changes)} />
        )}
        {tab === "priorities" && (
          <PrioritiesTable rows={draft.priorities} onChange={(index, changes) => patch("priorities", index, changes)} />
        )}
        {tab === "link_types" && (
          <LinkTypesTable rows={draft.link_types} onChange={(index, changes) => patch("link_types", index, changes)} />
        )}
        {tab === "users" && (
          <UsersTable
            rows={draft.users}
            domain={options.placeholder_email_domain}
            onChange={(index, changes) => patch("users", index, changes)}
            onBulk={bulkUsers}
            onDomainChange={(value) =>
              setOptions((current) => (current ? { ...current, placeholder_email_domain: value } : current))
            }
          />
        )}
        {tab === "sprints" && <SprintsTable rows={draft.sprints} onChange={(index, changes) => patch("sprints", index, changes)} />}
        {tab === "versions" && (
          <VersionsTable rows={draft.versions} onChange={(index, changes) => patch("versions", index, changes)} />
        )}
        {tab === "components" && (
          <ComponentsTable rows={draft.components} onChange={(index, changes) => patch("components", index, changes)} />
        )}
      </div>

      <ImportOptions options={options} onChange={setOptions} />
      <ValidationSummary validation={validation} />

      {(save.isError || start.isError || validate.isError) && (
        <ErrorText error={save.error ?? start.error ?? validate.error} />
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-subtle pt-3">
        <Button variant="secondary" onClick={() => save.mutate()} disabled={busy}>
          <Save size={13} /> {save.isPending ? "Saving…" : "Save mappings"}
        </Button>
        <Button variant="secondary" onClick={() => validate.mutate()} disabled={busy}>
          {validate.isPending ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
          Check
        </Button>
        <Button
          variant="secondary"
          onClick={() => start.mutate(RunKind.dry_run)}
          disabled={busy}
          title="Resolve everything and report — writes nothing"
        >
          Dry run
        </Button>
        <Button
          onClick={() => start.mutate(RunKind.import)}
          disabled={busy}
          title="Create the targets and import the issues"
        >
          <Play size={13} /> Import
        </Button>
        <span className="text-xs text-fg-faint">
          Check and dry run save your mappings first. Review the report before importing; destination data may change between runs.
        </span>
      </div>
    </div>
  );
}
