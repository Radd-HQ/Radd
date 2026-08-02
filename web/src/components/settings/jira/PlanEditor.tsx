import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Loader2, Play, Save, Wand2 } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { fieldsQuery, jiraPlanQuery, queryKeys } from "../../../lib/queries";
import {
  RunKind,
  type FieldMappingEntry,
  type JiraPlan,
  type JiraRun,
  type PlanMappings,
  type PlanOptions,
  type PlanValidation,
  type UserMapping,
} from "../../../lib/types";
import { Button } from "../../Button";
import { QueryError } from "../../QueryError";
import { Spinner } from "../../Spinner";
import { FieldsTable } from "./FieldsTable";
import {
  ComponentsTable,
  IssueTypesTable,
  LinkTypesTable,
  PrioritiesTable,
  SprintsTable,
  StatusesTable,
  VersionsTable,
} from "./VocabTables";
import { UsersTable } from "./UsersTable";

type TabKey = keyof PlanMappings;

const TABS: [TabKey, string][] = [
  ["fields", "Fields"],
  ["issue_types", "Issue types"],
  ["statuses", "Statuses"],
  ["priorities", "Priorities"],
  ["link_types", "Link types"],
  ["users", "People"],
  ["sprints", "Sprints"],
  ["versions", "Versions"],
  ["components", "Components"],
];

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
  const plan = useQuery(jiraPlanQuery(planId));
  const fields = useQuery(fieldsQuery());
  const [draft, setDraft] = useState<PlanMappings | null>(null);
  const [options, setOptions] = useState<PlanOptions | null>(null);
  const [tab, setTab] = useState<TabKey>("fields");
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
    setTab(focus.section as TabKey);
    setHighlight(focus.mappingKey);
  }, [focus?.nonce]);

  const save = useMutation({
    mutationFn: () =>
      api.patch<JiraPlan>(`${ApiPath.jiraPlans}/${planId}`, {
        mappings: draft,
        options,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jiraPlan(planId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jiraPlans });
    },
  });

  const validate = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<PlanValidation>(`${ApiPath.jiraPlans}/${planId}/validate`, {});
    },
    onSuccess: setValidation,
  });

  const start = useMutation({
    mutationFn: async (kind: (typeof RunKind)[keyof typeof RunKind]) => {
      await save.mutateAsync();
      return api.post<JiraRun>(ApiPath.jiraRuns, { plan_id: planId, kind });
    },
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jiraRuns });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jiraPlan(planId) });
      onRunStarted(run);
    },
  });

  if (plan.isPending || !draft || !options) return <Spinner label="Loading the plan…" />;
  if (plan.isError) return <QueryError label="import plan" error={plan.error} />;

  /** Patch one row of one mapping table. */
  const patch = <K extends TabKey>(key: K) =>
    (index: number, changes: Partial<PlanMappings[K][number]>) =>
      setDraft((current) => {
        if (!current) return current;
        const rows = [...current[key]] as PlanMappings[K];
        rows[index] = { ...rows[index], ...changes };
        return { ...current, [key]: rows };
      });

  const bulkUsers = (
    apply: (row: UserMapping, index: number) => Partial<UserMapping> | null,
  ) =>
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

  const problemsFor = (section: TabKey) =>
    (validation?.problems ?? []).filter((p) => p.section === section);
  const counted = (key: TabKey) => {
    const rows = draft[key] as { count?: number }[];
    return key === "fields"
      ? (draft.fields as FieldMappingEntry[]).filter((f) => f.band === "in_use").length
      : rows.filter((r) => (r.count ?? 0) > 0).length;
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Tabs, each badged with how many rows actually matter. */}
      <div className="flex flex-wrap gap-1.5">
        {TABS.map(([key, label]) => {
          const problems = problemsFor(key).length;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer " +
                (tab === key
                  ? "bg-accent text-white"
                  : "border border-subtle bg-elevated text-fg-secondary hover:border-strong")
              }
            >
              {label}
              <span className={tab === key ? "text-white/70" : "text-fg-faint"}>
                {counted(key)}
              </span>
              {problems > 0 && (
                <span className="rounded bg-red-500/20 px-1 text-[10px] text-red-300">
                  {problems}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div>
        {tab === "fields" && (
          <FieldsTable
            rows={draft.fields}
            existingKeys={(fields.data ?? []).map((f) => f.key)}
            existingOptions={Object.fromEntries(
              (fields.data ?? []).filter((f) => f.options?.length).map((f) => [f.key, f.options!]),
            )}
            problems={problemsFor("fields")}
            highlight={highlight}
            onChange={patch("fields")}
          />
        )}
        {tab === "issue_types" && (
          <IssueTypesTable rows={draft.issue_types} onChange={patch("issue_types")} />
        )}
        {tab === "statuses" && (
          <StatusesTable rows={draft.statuses} onChange={patch("statuses")} />
        )}
        {tab === "priorities" && (
          <PrioritiesTable rows={draft.priorities} onChange={patch("priorities")} />
        )}
        {tab === "link_types" && (
          <LinkTypesTable rows={draft.link_types} onChange={patch("link_types")} />
        )}
        {tab === "users" && (
          <UsersTable
            rows={draft.users}
            domain={options.placeholder_email_domain}
            onChange={patch("users")}
            onBulk={bulkUsers}
            onDomainChange={(value) =>
              setOptions((current) =>
                current ? { ...current, placeholder_email_domain: value } : current,
              )
            }
          />
        )}
        {tab === "sprints" && <SprintsTable rows={draft.sprints} onChange={patch("sprints")} />}
        {tab === "versions" && (
          <VersionsTable rows={draft.versions} onChange={patch("versions")} />
        )}
        {tab === "components" && (
          <ComponentsTable rows={draft.components} onChange={patch("components")} />
        )}
      </div>

      <ImportOptions options={options} onChange={setOptions} />

      {validation && !validation.ok && (
        <div className="rounded-md border border-red-500/40 bg-red-500/5 p-3">
          <p className="flex items-center gap-1.5 text-[13px] text-red-300">
            <CircleAlert size={14} />
            {validation.problems.length} thing(s) to fix before importing
          </p>
          <ul className="mt-1.5 flex flex-col gap-0.5 text-xs text-fg-secondary">
            {validation.problems.slice(0, 12).map((problem, i) => (
              <li key={i}>
                <span className="text-fg-faint">{problem.section}</span>
                {problem.subject && <span className="text-fg"> · {problem.subject}</span>} —{" "}
                {problem.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {validation?.ok && (
        <p className="flex items-center gap-1.5 text-xs text-emerald-400">
          <CheckCircle2 size={13} /> The plan is ready to import.
        </p>
      )}

      {(save.isError || start.isError || validate.isError) && (
        <p className="text-xs text-red-400">
          {errorMessage(save.error ?? start.error ?? validate.error)}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-subtle pt-3">
        <Button variant="secondary" onClick={() => save.mutate()} disabled={save.isPending}>
          <Save size={13} /> {save.isPending ? "Saving…" : "Save mappings"}
        </Button>
        <Button variant="secondary" onClick={() => validate.mutate()} disabled={validate.isPending}>
          {validate.isPending ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
          Check
        </Button>
        <Button
          variant="secondary"
          onClick={() => start.mutate(RunKind.dry_run)}
          disabled={start.isPending}
          title="Resolve everything and report — writes nothing"
        >
          Dry run
        </Button>
        <Button
          onClick={() => start.mutate(RunKind.import)}
          disabled={start.isPending}
          title="Create the targets and import the issues"
        >
          <Play size={13} /> Import
        </Button>
        <span className="text-xs text-fg-faint">
          A dry run uses the same code as the import, so it cannot disagree with it.
        </span>
      </div>
    </div>
  );
}

function ImportOptions({
  options,
  onChange,
}: {
  options: PlanOptions;
  onChange: (next: PlanOptions) => void;
}) {
  const toggle = (key: keyof PlanOptions, label: string, hint?: string) => (
    <label className="flex items-start gap-2 text-xs text-fg-secondary">
      <input
        type="checkbox"
        className="mt-0.5"
        checked={Boolean(options[key])}
        onChange={(e) => onChange({ ...options, [key]: e.target.checked })}
      />
      <span>
        {label}
        {hint && <span className="block text-fg-faint">{hint}</span>}
      </span>
    </label>
  );
  return (
    <fieldset className="rounded-lg border border-subtle p-3">
      <legend className="px-1 text-xs font-medium text-fg-secondary">How to import</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {toggle(
          "quiet",
          "Import quietly",
          "Nobody is notified and no automation rule fires — imported work is years old.",
        )}
        {toggle("import_comments", "Comments")}
        {toggle("import_worklogs", "Worklogs")}
        {toggle("import_attachments", "Attachments")}
        {toggle("import_history", "Change history")}
      </div>
    </fieldset>
  );
}
