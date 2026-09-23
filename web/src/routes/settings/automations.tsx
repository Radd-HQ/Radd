import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, Workflow, X, Zap } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiAutomationPath } from "../../lib/constants";
import { shortDateTime, relativeTime } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { triggerLabel } from "../../lib/meta";
import { automationCatalogQuery, automationsQuery, queryKeys } from "../../lib/queries";
import { NodeKind, Permission, type Rule, type RuleUpdate } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { TableSkeleton } from "../../components/TableSkeleton";
import { RuleEditor } from "../../components/automations/RuleEditor";
import { RunStatusChip } from "../../components/automations/RunsPanel";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";
import { Switch } from "../../components/Switch";

/** Automation rules admin (spec 20) — global, gated on automation.manage. */
export function AutomationsSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.automationManage);
  const rules = useQuery({ ...automationsQuery(), enabled: canManage });
  /** null = list mode; {rule} = editor mode (rule null → creating). */
  const [editing, setEditing] = useState<{ rule: Rule | null } | null>(null);
  const all = rules.data ?? [];
  const search = useListFilter(all, (rule) => [rule.name]);
  const list = search.filtered;

  if (canManage && editing) {
    return (
      <SettingsPage history={{ entities: ["automation_rule"] }}
        title={editing.rule ? "Edit automation rule" : "New automation rule"}
        description="React to any event, or run on a schedule — daily, weekly, monthly or a cron expression. Conditions split issues down different branches, and actions can update them, notify people, or create new issues, which is how recurring maintenance tickets and periodic reviews get raised automatically."
      >
        <RuleEditor rule={editing.rule} onDone={() => setEditing(null)} />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage history={{ entities: ["automation_rule"] }}
      title="Automations"
      description="Rules that react to events or run on a schedule, then change issues, notify people or call out to other systems."
      actions={
        canManage && (
          <Button onClick={() => setEditing({ rule: null })}>
            <Plus size={14} aria-hidden />
            New rule
          </Button>
        )
      }
    >
      {canManage && rules.isPending ? (
        <TableSkeleton rows={4} />
      ) : !canManage ? (
        <EmptyState
          icon={Zap}
          message="You need the automation.manage permission (global or instance admin) to view rules."
        />
      ) : rules.isError ? (
        <QueryError label="automation rules" error={rules.error} />
      ) : all.length === 0 ? (
        <EmptyState
          icon={Zap}
          message="No automation rules yet — create one to react to issue events."
        />
      ) : (
        <>
          {all.length > 8 && (
            <ListSearchInput
              className="mb-3"
              value={search.filter}
              onChange={search.setFilter}
              placeholder="Filter rules by name…"
              total={all.length}
              matched={list.length}
              noun="rules"
            />
          )}
          {list.length === 0 ? (
            <EmptyState icon={Zap} message={`No rules match “${search.filter.trim()}”.`} />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((rule) => (
                <RuleRow
                  key={rule.id}
                  rule={rule}
                  onEdit={() => setEditing({ rule })}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </SettingsPage>
  );
}

function RuleRow({ rule, onEdit }: { rule: Rule; onEdit: () => void }) {
  const queryClient = useQueryClient();
  const catalog = useQuery(automationCatalogQuery); // cached once, staleTime ∞
  const [confirming, setConfirming] = useState(false);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.automations });

  const toggle = useMutation({
    mutationFn: () =>
      api.patch<Rule>(apiAutomationPath(rule.id), { enabled: !rule.enabled } satisfies RuleUpdate),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiAutomationPath(rule.id)),
    onSuccess: invalidate,
  });
  // Spec 116: actions are ACTION nodes of the graph, not a flat list.
  const actionCount = rule.nodes.filter((node) => node.kind === NodeKind.action).length;
  // The soonest upcoming run across every schedule trigger — with several
  // clocks, "next run" is the earliest of them, not whichever sorted first.
  const nextRun = rule.triggers
    .map((trigger) => trigger.next_run_at)
    .filter((stamp): stamp is string => Boolean(stamp))
    .sort()[0];

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <Workflow size={14} className="shrink-0 text-accent-text" aria-hidden />
      <span className="truncate text-[13px] font-medium text-heading">{rule.name}</span>
      {/* Every trigger, not just one: a graph may fire from several, and showing
          the first would misdescribe when this automation actually runs. */}
      {rule.triggers.length === 0 ? (
        <span
          className="rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-faint"
          title="No trigger node — this automation can never run"
        >
          no trigger
        </span>
      ) : (
        rule.triggers.map((trigger) => (
          <span
            key={trigger.node_id}
            className="shrink-0 rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-secondary"
          >
            {triggerLabel(trigger.event_type, catalog.data)}
          </span>
        ))
      )}
      <span className="shrink-0 text-[11px] text-fg-faint">
        {actionCount} action{actionCount === 1 ? "" : "s"}
      </span>
      {nextRun && rule.enabled && (
        <span className="shrink-0 text-[11px] text-fg-muted">next {shortDateTime(nextRun)}</span>
      )}
      {/* The newest recorded run (RADD-1266): the one-glance answer to "is this
          thing actually firing". */}
      {rule.last_run_at && (
        <span className="flex shrink-0 items-center gap-1 text-[11px] text-fg-muted" data-last-run>
          <RunStatusChip status={rule.last_run_status} />
          {relativeTime(rule.last_run_at)}
        </span>
      )}

      <Switch
        className="ml-auto"
        label="Enabled"
        checked={rule.enabled}
        disabled={toggle.isPending}
        onChange={() => toggle.mutate()}
        data-rule-enabled={rule.id}
      />

      {confirming ? (
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="rounded px-1.5 py-0.5 text-xs text-red-400 hover:bg-elevated cursor-pointer disabled:opacity-50"
          >
            {remove.isPending ? "Deleting…" : "Delete"}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            aria-label="Cancel delete"
            className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <X size={13} />
          </button>
        </span>
      ) : (
        <>
          <IconButton
            onClick={onEdit}
            aria-label={`Edit ${rule.name}`}
          >
            <Pencil size={13} />
          </IconButton>
          <IconButton
            danger
            onClick={() => setConfirming(true)}
            aria-label={`Delete ${rule.name}`}
          >
            <Trash2 size={13} />
          </IconButton>
        </>
      )}
      {(toggle.isError || remove.isError) && (
        <span className="text-xs text-red-400">{errorMessage(toggle.error ?? remove.error)}</span>
      )}
    </li>
  );
}
