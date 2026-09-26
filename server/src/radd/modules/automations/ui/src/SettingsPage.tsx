import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAutomationQuery as useQuery } from "./query-lifetime";
import { useAutomationMutation as useMutation } from "./mutation-lifetime";

import { Pencil, Plus, Trash2, Workflow, X, Zap } from "lucide-react";
import { api, errorMessage } from "@radd/plugin-sdk";
import { apiAutomationPath } from "./constants";
import { shortDateTime, relativeTime } from "@radd/plugin-sdk";
import { usePermissions } from "@radd/plugin-sdk";
import { useListFilter } from "@radd/plugin-sdk";
import { triggerLabel } from "./meta";
import { automationCatalogQuery, automationsQuery, automationTemplatesQuery, invalidateAutomations } from "./queries";
import { NodeKind, type AutomationTemplate, type Rule, type RuleUpdate } from "./types";
import { Button, ButtonVariant } from "@radd/plugin-sdk";
import { Modal } from "@radd/plugin-sdk";
import { EmptyState } from "@radd/plugin-sdk";
import { ListSearchInput } from "@radd/plugin-sdk";
import { TableSkeleton } from "@radd/plugin-sdk";
import { RuleEditor } from "./RuleEditor";
import { RunStatusChip } from "./RunsPanel";
import { SettingsPage } from "@radd/plugin-sdk";
import { QueryError } from "@radd/plugin-sdk";
import { IconButton } from "@radd/plugin-sdk";
import { Switch } from "@radd/plugin-sdk";

/** Automation rules admin (spec 20) — global, gated on automation.manage. */
export function AutomationsSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global("automation.manage");
  const rules = useQuery({ ...automationsQuery(), enabled: canManage });
  /** null = list mode; {rule} = editor mode (rule null → creating). */
  const [editing, setEditing] = useState<{ rule: Rule | null; draft?: AutomationTemplate } | null>(null);
  const [choosing, setChoosing] = useState(false);
  useEffect(() => {if (!canManage) {setEditing(null); setChoosing(false);}}, [canManage]);
  const all = rules.data ?? [];
  const search = useListFilter(all, (rule) => [rule.name]);
  const list = search.filtered;

  if (canManage && editing) {
    return (
      <SettingsPage history={{ entities: ["automation_rule"] }}
        title={editing.rule ? "Edit automation rule" : "New automation rule"}
        description="React to any event, or run on a schedule — daily, weekly, monthly or a cron expression. Conditions split issues down different branches, and actions can update them, notify people, or create new issues, which is how recurring maintenance tickets and periodic reviews get raised automatically."
      >
        <RuleEditor rule={editing.rule} draft={editing.draft ?? null} onDone={() => setEditing(null)} />
      </SettingsPage>
    );
  }

  const picker = choosing && (
    <TemplatePicker
      onClose={() => setChoosing(false)}
      onPick={(template) => {
        setChoosing(false);
        setEditing({ rule: null, draft: template });
      }}
    />
  );

  return (
    <>
    {picker}
    <SettingsPage history={{ entities: ["automation_rule"] }}
      title="Automations"
      description="Rules that react to events or run on a schedule, then change issues, notify people or call out to other systems."
      actions={
        canManage && (
          <div className="flex items-center gap-2">
            <Button variant={ButtonVariant.ghost} onClick={() => setChoosing(true)} data-from-template>
              From template…
            </Button>
            <Button onClick={() => setEditing({ rule: null })}>
              <Plus size={14} aria-hidden />
              New rule
            </Button>
          </div>
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
    </>
  );
}

function RuleRow({ rule, onEdit }: { rule: Rule; onEdit: () => void }) {
  const queryClient = useQueryClient();
  const catalog = useQuery(automationCatalogQuery); // cached once, staleTime ∞
  const [confirming, setConfirming] = useState(false);
  const invalidate = () =>
    invalidateAutomations(queryClient);

  const toggle = useMutation({
    mutationFn: (_: void, signal) =>
      api.patch<Rule>(apiAutomationPath(rule.id), { enabled: !rule.enabled } satisfies RuleUpdate, {signal}),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (_: void, signal) => api.delete<void>(apiAutomationPath(rule.id), {signal}),
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
            className="rounded px-1.5 py-0.5 text-xs text-status-danger-ink hover:bg-elevated cursor-pointer disabled:opacity-50"
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
        <span className="text-xs text-status-danger-ink">{errorMessage(toggle.error ?? remove.error)}</span>
      )}
    </li>
  );
}


/** "From template…" (RADD-1316): whole automations the loaded plugins offer —
 * the behaviours Radd no longer runs unasked. Picking one opens an unsaved,
 * DISABLED draft; nothing exists until it is saved. */
function TemplatePicker({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (template: AutomationTemplate) => void;
}) {
  const templates = useQuery(automationTemplatesQuery);
  const groups = new Map<string, AutomationTemplate[]>();
  for (const template of templates.data ?? []) {
    groups.set(template.group, [...(groups.get(template.group) ?? []), template]);
  }
  return (
    <Modal title="Start from a template" onClose={onClose} wide>
      <p className="mb-3 text-[13px] text-fg-secondary">
        Opens as a draft, switched off. Adjust it, then save and enable it — nothing runs until you do.
      </p>
      {templates.isPending ? (
        <TableSkeleton rows={3} />
      ) : templates.isError ? (
        <QueryError label="templates" error={templates.error} />
      ) : groups.size === 0 ? (
        <EmptyState icon={Workflow} message="No templates are offered on this instance." />
      ) : (
        <div className="flex flex-col gap-4">
          {[...groups.entries()].map(([group, entries]) => (
            <section key={group} className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-fg-muted">{group}</span>
              {entries.map((template) => (
                <button
                  key={template.key}
                  type="button"
                  data-template={template.key}
                  onClick={() => onPick(template)}
                  className="flex flex-col items-start gap-0.5 rounded-[8px] border border-subtle bg-surface px-3 py-2 text-left hover:border-strong hover:bg-elevated cursor-pointer"
                >
                  <span className="text-[13px] font-medium text-heading">{template.name}</span>
                  <span className="text-xs text-fg-secondary">{template.description}</span>
                </button>
              ))}
            </section>
          ))}
        </div>
      )}
    </Modal>
  );
}
