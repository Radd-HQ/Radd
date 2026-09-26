import { useEffect, useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api, Button, ButtonVariant, QueryError } from "@radd/plugin-sdk";
import { MappingRows } from "./MappingRows";
import { PlanOptions } from "./PlanOptions";
import { ConfluencePath, confluenceKeys, planQuery } from "./queries";
import {
  CONFLUENCE_SECTION_LABELS,
  type ConfluenceMappingSection,
  type ConfluencePlanMappings,
  type ConfluencePlanOptions,
  type ConfluencePlanProblem,
} from "./types";

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
  const plan = useQuery(planQuery(planId));
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
      api.patch(`${ConfluencePath.plans}/${planId}`, {
        mappings: draft,
        options,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: confluenceKeys.plan(planId) });
    },
  });

  const validate = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<ConfluencePlanProblem[]>(`${ConfluencePath.plans}/${planId}/validate`, {});
    },
    onSuccess: (result) => { setProblems(result); setChecked(true); },
  });

  const run = useMutation({
    mutationFn: async (dryRun: boolean) => {
      await save.mutateAsync();
      return api.post(ConfluencePath.runs, { plan_id: planId, dry_run: dryRun });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: confluenceKeys.runs });
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

      <PlanOptions options={options} onChange={next => { setOptions(next); setProblems([]); setChecked(false); }} />
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
