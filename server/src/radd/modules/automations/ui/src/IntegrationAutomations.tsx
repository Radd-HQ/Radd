import { useEffect, useState } from "react";
import { useAutomationQuery as useQuery } from "./query-lifetime";

import { usePermissions } from "@radd/plugin-sdk";
import { automationsQuery, automationTemplatesQuery, automationCatalogQuery } from "./queries";
import { type AutomationTemplate, type Rule } from "./types";
import { Button } from "@radd/plugin-sdk";
import { Modal } from "@radd/plugin-sdk";
import { QueryError } from "@radd/plugin-sdk";
import { RuleEditor } from "./RuleEditor";

/** Configure an integration's policies where the integration itself is set up. */
export function IntegrationAutomations({ integration, label }: { integration: string; label: string }) {
  const canManage = usePermissions().global("automation.manage");
  const catalog = useQuery({...automationCatalogQuery, enabled: canManage});
  const templates = useQuery({ ...automationTemplatesQuery, enabled: canManage });
  const rules = useQuery({ ...automationsQuery(), enabled: canManage });
  const [editing, setEditing] = useState<{ rule: Rule | null; draft?: AutomationTemplate } | null>(null);
  useEffect(() => {if (!canManage) setEditing(null);}, [canManage]);
  if (!canManage) return null;
  const offered = (templates.data ?? []).filter((template) => template.plugin === integration);
  const events = new Set(catalog.data?.triggers.filter(trigger => trigger.plugin === integration).map(trigger => trigger.event_type));
  const nodeTypes = new Set(catalog.data?.nodes.filter(node => node.plugin === integration).map(node => node.key));
  const matches = (rule: Rule, template: AutomationTemplate) => {
    const actions = template.nodes.filter(node => node.kind === "action").map(node => node.type);
    const triggers = template.nodes.filter(node => node.kind === "trigger").map(node => node.params.event);
    return rule.nodes.some(node => node.kind === "trigger" && triggers.includes(node.params.event))
      && actions.some(type => rule.nodes.some(node => node.kind === "action" && node.type === type));
  };
  const related = (rules.data ?? []).filter(rule => rule.nodes.some(node => nodeTypes.has(node.type)
    || node.kind === "trigger" && events.has(String(node.params.event)))
    || offered.some(template => matches(rule, template)));


  return (
    <section className="my-4 space-y-2" data-integration-automations={integration}>
      <h3 className="text-sm font-semibold text-heading">{label} automations</h3>
      <p className="text-xs text-fg-muted">Templates start disabled. Configure their conditions and actions, preview the result, then enable them. Enabled rules still follow their own conditions.</p>
      {catalog.isError && <QueryError label="automation catalog" error={catalog.error} />}
      {rules.isError ? <QueryError label="automations" error={rules.error} /> : rules.isPending ? <p className="text-xs text-fg-muted">Loading rules…</p> : (
        <ul className="space-y-1">
          {related.map((rule) => <li key={rule.id} className="flex items-center gap-2 text-sm">
            <span className="text-fg-muted">{rule.enabled ? "Enabled" : "Disabled"}</span>
            <button type="button" className="text-accent-text hover:underline" onClick={() => setEditing({ rule })}>{rule.name}</button>
          </li>)}
          {related.length === 0 && <li className="text-xs text-fg-muted">No relevant automation policies have been saved.</li>}
        </ul>
      )}
      {!rules.isPending && !rules.isError && offered.map(template => <p key={template.key} className="text-xs text-fg-muted">{template.name}: {related.filter(rule => rule.enabled && matches(rule, template)).length} enabled rules use this trigger and action (their conditions may differ).</p>)}
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
