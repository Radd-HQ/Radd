import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePermissions } from "../../lib/hooks";
import { automationsQuery, automationTemplatesQuery } from "../../lib/queries";
import { Permission, type AutomationTemplate, type Rule } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { RuleEditor } from "../automations/RuleEditor";

/** Configure an integration's policies where the integration itself is set up. */
export function IntegrationAutomations({ group }: { group: string }) {
  const canManage = usePermissions().global(Permission.automationManage);
  const templates = useQuery({ ...automationTemplatesQuery, enabled: canManage });
  const rules = useQuery({ ...automationsQuery(), enabled: canManage });
  const [editing, setEditing] = useState<{ rule: Rule | null; draft?: AutomationTemplate } | null>(null);
  if (!canManage) return null;
  const offered = (templates.data ?? []).filter((template) => template.group === group);
  const events = new Set(offered.flatMap((template) => template.nodes.filter((node) => node.kind === "trigger").map((node) => node.params.event)));
  const matches = (rule: Rule, template: AutomationTemplate) => {
    const actions = template.nodes.filter(node => node.kind === "action").map(node => node.type);
    const triggers = template.nodes.filter(node => node.kind === "trigger").map(node => node.params.event);
    return rule.nodes.some(node => node.kind === "trigger" && triggers.includes(node.params.event))
      && actions.some(type => rule.nodes.some(node => node.kind === "action" && node.type === type));
  };
  const related = (rules.data ?? []).filter(rule => group === "Email"
    ? offered.some(template => matches(rule, template))
    : rule.nodes.some(node => node.kind === "trigger" && (events.has(node.params.event) || String(node.params.event).startsWith(`${group.toLowerCase()}.`))));

  return (
    <section className="my-4 space-y-2" data-integration-automations={group}>
      <h3 className="text-sm font-semibold text-heading">{group} automations</h3>
      <p className="text-xs text-fg-muted">Templates start disabled. Configure their conditions and actions, preview the result, then enable them. Enabled rules still follow their own conditions.</p>
      {rules.isError ? <QueryError label="automations" error={rules.error} /> : rules.isPending ? <p className="text-xs text-fg-muted">Loading rules…</p> : (
        <ul className="space-y-1">
          {related.map((rule) => <li key={rule.id} className="flex items-center gap-2 text-sm">
            <span className="text-fg-muted">{rule.enabled ? "Enabled" : "Disabled"}</span>
            <button type="button" className="text-accent-text hover:underline" onClick={() => setEditing({ rule })}>{rule.name}</button>
          </li>)}
          {related.length === 0 && <li className="text-xs text-fg-muted">No relevant automation policies have been saved.</li>}
        </ul>
      )}
      {!rules.isPending && !rules.isError && offered.map(template => <p key={template.key} className="text-xs text-fg-muted">{template.name}: {related.filter(rule => rule.enabled && matches(rule, template)).length} enabled matching rules (their conditions still apply).</p>)}
      {templates.isError ? <QueryError label="templates" error={templates.error} /> : <div className="flex flex-wrap gap-2">
        {offered.map((template) => <Button key={template.key} title={template.description} onClick={() => setEditing({ rule: null, draft: template })}>{template.name}</Button>)}
      </div>}
      {editing && <Modal title={editing.rule ? "Edit automation" : "Configure automation"} wide onClose={() => setEditing(null)}>
        {editing.draft && <p className="mb-3 text-sm text-fg-muted">{editing.draft.description}</p>}
        <RuleEditor rule={editing.rule} draft={editing.draft} onDone={() => setEditing(null)} />
      </Modal>}
    </section>
  );
}
