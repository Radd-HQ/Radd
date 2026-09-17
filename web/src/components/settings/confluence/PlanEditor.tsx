import { useEffect, useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Button, ButtonVariant } from "../../Button";
import { SelectField } from "../../SelectField";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { confluencePlanQuery, queryKeys } from "../../../lib/queries";
import {
  ConfluenceMacroAction,
  CONFLUENCE_SECTION_LABELS,
  ConfluenceUnresolvedPrincipal,
  type ConfluenceMappingSection,
  type ConfluencePlanMappings,
  type ConfluencePlanOptions,
  type ConfluencePlanProblem,
} from "../../../lib/types";

import { MappingTarget } from "./MappingTarget";
import { QueryError } from "../../QueryError";

const TABS: ConfluenceMappingSection[] = ["spaces", "macros", "users", "groups", "labels", "jira_links"];

/**
 * The mapping step (spec 117).
 *
 * The census is the point: rows carry their real usage COUNT, the used ones are
 * expanded and the unused collapse into a section that defaults to ignored — the
 * spec-100 treatment that turned 337 Jira fields into 14 decisions.
 */
export function PlanEditor({
  planId,
  focus,
  onRan,
}: {
  planId: string;
  focus: { section: ConfluenceMappingSection; key: string; nonce: number } | null;
  onRan: () => void;
}) {
  const client = useQueryClient();
  const plan = useQuery(confluencePlanQuery(planId));
  const [tab, setTab] = useState<ConfluenceMappingSection>("spaces");
  const [draft, setDraft] = useState<ConfluencePlanMappings | null>(null);
  const [options, setOptions] = useState<ConfluencePlanOptions | null>(null);
  const [problems, setProblems] = useState<ConfluencePlanProblem[]>([]);
  const [highlight, setHighlight] = useState("");
  const [filter, setFilter] = useState("");
  const [checked, setChecked] = useState(false);

  const initialized = useRef<string | null>(null);
  useEffect(() => {
    if (plan.data && initialized.current !== planId) {
      initialized.current = planId;
      setDraft(plan.data.mappings);
      setOptions(plan.data.options);
    }
  }, [plan.data, planId]);

  // "Fix in Macros → drawio" lands here: the tab switches and the row lights up.
  useEffect(() => {
    if (focus) {
      setTab(focus.section);
      setHighlight(focus.key);
      setFilter(focus.key);
    }
  }, [focus]);

  useEffect(() => {
    if (focus && draft) document.getElementById("confluence-mappings")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus?.nonce, Boolean(draft)]);

  const save = useMutation({
    mutationFn: () =>
      api.patch(`${ApiPath.confluencePlans}/${planId}`, {
        mappings: draft,
        options,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.confluencePlan(planId) });
    },
  });

  const validate = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<ConfluencePlanProblem[]>(`${ApiPath.confluencePlans}/${planId}/validate`, {});
    },
    onSuccess: (result) => { setProblems(result); setChecked(true); },
  });

  const run = useMutation({
    mutationFn: async (dryRun: boolean) => {
      await save.mutateAsync();
      return api.post(ApiPath.confluenceRuns, { plan_id: planId, dry_run: dryRun });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.confluenceRuns });
      onRan();
    },
  });

  if (plan.isError) return <QueryError label="import plan" error={plan.error}/>;
  if (!draft || !options) {
    return <p className="text-[13px] text-fg-faint">Loading the plan…</p>;
  }

  const rows = draft[tab] as { count: number }[];
  const matching = rows.filter(row => !filter.trim() || Object.values(row as Record<string, unknown>).some(value => typeof value === "string" && value.toLocaleLowerCase().includes(filter.trim().toLocaleLowerCase())));
  const used = matching.filter((row) => row.count > 0);
  const unused = matching.filter((row) => row.count === 0);

  const patchRow = (subset: typeof rows, index: number, changes: Record<string, unknown>) => {
    const list = [...(draft[tab] as unknown[])];
    const realIndex = list.indexOf(subset[index]);
    list[realIndex] = { ...list[realIndex] as object, ...changes };
    setDraft({ ...draft, [tab]: list });
    setProblems([]);
    setChecked(false);
  };
  const busy = save.isPending || validate.isPending || run.isPending;
  return (
    <section className="rounded-xl border border-subtle bg-surface p-4" id="confluence-mappings">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-heading">Mappings</h2>
        <p className="text-[13px] text-fg-muted">
          Everything below was counted in the download, so the decisions that matter
          are the ones at the top.
        </p>
      </header>

      <div className="mb-3 flex flex-wrap gap-1">
        {TABS.map((section) => {
          const count = (draft[section] as { count: number }[]).filter((r) => r.count > 0).length;
          return (
            <button
              key={section}
              type="button"
              onClick={() => { setTab(section); setFilter(""); }}
              aria-pressed={tab === section}
              className={`rounded-lg px-2.5 py-1 text-[13px] ${
                tab === section
                  ? "bg-accent text-white"
                  : "text-fg-secondary hover:bg-elevated"
              }`}
            >
              {CONFLUENCE_SECTION_LABELS[section]}
              {count > 0 && (
                <span className="ml-1.5 text-[11px] opacity-80">{count}</span>
              )}
            </button>
          );
        })}
      </div>

      <label className="mb-3 block text-xs text-fg-muted">Filter mappings
        <input type="search" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Find a source or destination…" className="ml-2 rounded border border-subtle bg-elevated px-3 py-2 text-fg"/>
      </label>
      <MappingRows
        section={tab}
        rows={used}
        highlight={highlight}
        onChange={(index, changes) => patchRow(used, index, changes)}
      />

      {unused.length > 0 && (
        <details open={filter.trim() ? true : undefined} className="mt-3 rounded border border-subtle p-3"><summary>{unused.length} unused entries — expand to configure</summary><MappingRows section={tab} rows={unused} highlight={highlight} onChange={(index, changes) => patchRow(unused, index, changes)}/></details>
      )}

      <OptionsFieldset options={options} onChange={next => { setOptions(next); setProblems([]); setChecked(false); }} />
      {checked && problems.length === 0 && <p role="status" className="mt-3 text-sm text-accent-text">No mapping problems found. Run a dry run to preview the import.</p>}

      {problems.length > 0 && (
        <ul className="mt-3 space-y-1">
          {problems.map((problem, index) => (
            <li
              key={index}
              className="flex items-start gap-2 rounded-lg border border-subtle bg-elevated px-3 py-2 text-[13px]"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-fg-muted" aria-hidden />
              <span className="text-fg-secondary">
                <button
                  type="button"
                  className="font-medium text-accent-text hover:underline"
                  onClick={() => { setTab(problem.section); setHighlight(problem.subject); setFilter(problem.subject); }}
                >
                  {CONFLUENCE_SECTION_LABELS[problem.section]}
                </button>
                {problem.subject ? ` → ${problem.subject}: ` : ": "}
                {problem.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      {(save.isError || validate.isError || run.isError) && <QueryError label="mapping action" error={save.error ?? validate.error ?? run.error}/>}
      <p className="mt-3 text-xs text-fg-muted">Check and dry run save your mappings first. Changing mappings affects the next run; review its report before importing again.</p>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button disabled={busy} variant={ButtonVariant.ghost} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save mappings"}
        </Button>
        <Button disabled={busy} variant={ButtonVariant.ghost} onClick={() => validate.mutate()}>
          {validate.isPending ? "Checking…" : "Check"}
        </Button>
        <Button
          disabled={busy}
          variant={ButtonVariant.secondary}
          onClick={() => run.mutate(true)}
        >
          Dry run
        </Button>
        <Button
          disabled={busy}
          onClick={() => run.mutate(false)}
        >
          Import
        </Button>
      </div>
    </section>
  );
}

function MappingRows({
  section,
  rows,
  highlight,
  onChange,
}: {
  section: ConfluenceMappingSection;
  rows: Record<string, unknown>[];
  highlight: string;
  onChange: (index: number, changes: Record<string, unknown>) => void;
}) {
  if (!rows.length) {
    return <p className="text-[13px] text-fg-faint">Nothing of this kind in the download.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-subtle text-left text-[12px] text-fg-muted">
            <th className="py-1.5 pr-3 font-medium">Name</th>
            <th className="py-1.5 pr-3 font-medium">Used</th>
            <th className="py-1.5 pr-3 font-medium">What happens</th>
            <th className="py-1.5 font-medium">Destination</th>
            <th className="py-1.5 font-medium">Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const name = String(row.name ?? row.key ?? row.username ?? row.project_key ?? "");
            return (
              <tr
                key={name}
                className={`border-b border-subtle last:border-0 ${
                  highlight && Object.values(row).includes(highlight) ? "bg-elevated" : ""
                }`}
              >
                <td className="py-1.5 pr-3 font-mono text-[12px] text-fg">{name}</td>
                <td className="py-1.5 pr-3 text-fg-muted">{String(row.count ?? 0)}</td>
                <td className="py-1.5 pr-3">
                  <ActionSelect
                    section={section}
                    value={String(row.action ?? "")}
                    onChange={(action) => onChange(index, { action })}
                  />
                </td>
                <td className="p-2"><MappingTarget section={section} row={row} onChange={changes => onChange(index, changes)}/></td>
                <td className="py-1.5 text-[12px] text-fg-muted">
                  {String(row.reason ?? row.sample_page ?? "")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const ACTIONS: Record<ConfluenceMappingSection, { value: string; label: string }[]> = {
  spaces: [
    { value: "create", label: "Create a space" },
    { value: "map", label: "Use existing space" },
    { value: "ignore", label: "Skip" },
  ],
  macros: [
    { value: ConfluenceMacroAction.extension, label: "Render as a block" },
    { value: ConfluenceMacroAction.native, label: "Plain markdown" },
    { value: ConfluenceMacroAction.unsupported, label: "Keep as a card" },
    { value: ConfluenceMacroAction.strip, label: "Remove" },
  ],
  users: [
    { value: "map", label: "Match an account" },
    { value: "ignore", label: "Leave unattributed" },
  ],
  groups: [
    { value: "identity", label: "Same group" },
    { value: "map", label: "Choose group or team" },
    { value: "fail", label: "Refuse the page" },
  ],
  labels: [
    { value: "create", label: "Create the label" },
    { value: "ignore", label: "Skip" },
  ],
  jira_links: [
    { value: "resolve", label: "Link to the issue here" },
    { value: "external", label: "Link to Jira" },
    { value: "ignore", label: "Plain text" },
  ],
};

function ActionSelect({
  section,
  value,
  onChange,
}: {
  section: ConfluenceMappingSection;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <SelectField
      label="Action"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="min-w-40"
    >
      {ACTIONS[section].map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </SelectField>
  );
}

/** Count 0 — collapsed and ignored by default, so it cannot crowd the decisions. */
function OptionsFieldset({
  options,
  onChange,
}: {
  options: ConfluencePlanOptions;
  onChange: (options: ConfluencePlanOptions) => void;
}) {
  const set = (changes: Partial<ConfluencePlanOptions>) => onChange({ ...options, ...changes });
  return (
    <fieldset className="mt-4 rounded-lg border border-subtle p-3">
      <legend className="px-1 text-[12px] font-medium text-fg-secondary">Options</legend>
      <div className="flex flex-col gap-2 text-[13px] text-fg-secondary">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.quiet}
            onChange={(e) => set({ quiet: e.target.checked })}
          />
          Import quietly (no notifications, webhooks or automations)
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.import_attachments}
            onChange={(e) => set({ import_attachments: e.target.checked })}
          />
          Bring attachments
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.import_comments}
            onChange={(e) => set({ import_comments: e.target.checked })}
          />
          Bring comments
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.import_restrictions}
            onChange={(e) => set({ import_restrictions: e.target.checked })}
          />
          Bring page restrictions
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.include_history}
            onChange={(e) => set({ include_history: e.target.checked })}
          />
          Bring version history (only if the download captured it)
        </label>
        <SelectField
          label="When a restriction names someone we cannot find"
          value={options.unresolved_principal}
          onChange={(e) =>
            set({ unresolved_principal: e.target.value as ConfluencePlanOptions["unresolved_principal"] })
          }
          hint="Refusing is the safe default: importing a restricted page open exposes it, and nobody notices."
        >
          <option value={ConfluenceUnresolvedPrincipal.fail}>Do not import that page</option>
          <option value={ConfluenceUnresolvedPrincipal.map_to}>Restrict it to a chosen group or team</option>
        </SelectField>
        {options.unresolved_principal === ConfluenceUnresolvedPrincipal.map_to && <MappingTarget section="groups" row={{action:"map",group_id:options.unresolved_group_id,team_id:options.unresolved_team_id}} onChange={changes => set({unresolved_group_id:changes.group_id as string | null,unresolved_team_id:changes.team_id as string | null})}/>}
      </div>
    </fieldset>
  );
}
