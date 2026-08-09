import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight } from "lucide-react";
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

  useEffect(() => {
    if (plan.data) {
      setDraft(plan.data.mappings);
      setOptions(plan.data.options);
    }
  }, [plan.data]);

  // "Fix in Macros → drawio" lands here: the tab switches and the row lights up.
  useEffect(() => {
    if (focus) {
      setTab(focus.section);
      setHighlight(focus.key);
    }
  }, [focus]);

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
    mutationFn: () => api.post<ConfluencePlanProblem[]>(`${ApiPath.confluencePlans}/${planId}/validate`, {}),
    onSuccess: setProblems,
  });

  const run = useMutation({
    mutationFn: (dryRun: boolean) =>
      api.post(ApiPath.confluenceRuns, { plan_id: planId, dry_run: dryRun }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.confluenceRuns });
      onRan();
    },
  });

  if (!draft || !options) {
    return <p className="text-[13px] text-fg-faint">Loading the plan…</p>;
  }

  const rows = draft[tab] as { count: number }[];
  const used = rows.filter((row) => row.count > 0);
  const unused = rows.filter((row) => row.count === 0);

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
              onClick={() => setTab(section)}
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

      <MappingRows
        section={tab}
        rows={used}
        highlight={highlight}
        onChange={(index, changes) => {
          const next = { ...draft };
          const list = [...(next[tab] as unknown[])];
          const target = used[index];
          const realIndex = (next[tab] as unknown[]).indexOf(target);
          list[realIndex] = { ...(target as object), ...changes };
          (next[tab] as unknown[]) = list;
          setDraft(next);
        }}
      />

      {unused.length > 0 && (
        <UnusedSection section={tab} rows={unused} />
      )}

      <OptionsFieldset options={options} onChange={setOptions} />

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
                  onClick={() => setTab(problem.section)}
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

      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button variant={ButtonVariant.ghost} onClick={() => save.mutate()}>
          Save
        </Button>
        <Button variant={ButtonVariant.ghost} onClick={() => validate.mutate()}>
          Check
        </Button>
        <Button
          variant={ButtonVariant.secondary}
          onClick={async () => {
            await save.mutateAsync();
            run.mutate(true);
          }}
        >
          Dry run
        </Button>
        <Button
          onClick={async () => {
            await save.mutateAsync();
            run.mutate(false);
          }}
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
                  highlight && name === highlight ? "bg-elevated" : ""
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
      label=""
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
function UnusedSection({
  section,
  rows,
}: {
  section: ConfluenceMappingSection;
  rows: Record<string, unknown>[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 rounded-lg border border-subtle">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[13px] text-fg-secondary hover:bg-elevated"
      >
        <ChevronRight
          className={`size-4 text-fg-muted transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden
        />
        {rows.length} unused in {CONFLUENCE_SECTION_LABELS[section].toLowerCase()} — ignored
      </button>
      {open && (
        <ul className="border-t border-subtle px-3 py-2 text-[12px] text-fg-muted">
          {rows.map((row, index) => (
            <li key={index} className="py-0.5 font-mono">
              {String(row.name ?? row.key ?? row.username ?? row.project_key ?? "")}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
          <option value={ConfluenceUnresolvedPrincipal.map_to}>Restrict it to a chosen group</option>
        </SelectField>
      </div>
    </fieldset>
  );
}
