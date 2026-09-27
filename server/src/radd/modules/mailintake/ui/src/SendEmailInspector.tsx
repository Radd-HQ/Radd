/** The Send email node's form: this plugin's automation action (RADD-1387), so its form and its
 *  recipient rule live here, not in Automations. */
import { useEffect } from "react";
import { OptionTextField, TextArea, TextField, usePermissions, type AutomationNodeInspectorProps } from "@radd/plugin-sdk";
import { CheckboxField } from "./shared";
import { isRecipientRole, withRecipientArity } from "./send-email";
import { EmailRecipient } from "./types";

/** The auth plugin's people option resource: an address can be searched for, or typed. */
const PEOPLE_OPTIONS = "users";

const TEMPLATE_HINT = "Templates: {{item.key}}, {{items.keys}}, {{actor.name}}, {{event_type}}, {{payload.<path>}}";

export function SendEmailInspector({ params, onChange }: AutomationNodeInspectorProps) {
  const canBrowsePeople = usePermissions().global("user.manage");
  const text = (key: string) => (typeof params[key] === "string" ? (params[key] as string) : "");
  const set = (patch: Record<string, unknown>) => onChange(withRecipientArity({ ...params, ...patch }));
  const role = isRecipientRole(params.to);

  // A role reached at set arity — a freshly placed node, or the Run control switched — is corrected
  // at once, so the draft never holds a pairing the server would refuse on save.
  useEffect(() => {
    const corrected = withRecipientArity(params);
    if (corrected !== params) onChange(corrected);
  }, [params, onChange]);

  return (
    <div className="flex flex-col gap-2.5" data-send-email-inspector>
      <OptionTextField
        resource={PEOPLE_OPTIONS}
        canBrowse={canBrowsePeople}
        label="To"
        value={text("to")}
        suggestions={Object.values(EmailRecipient)}
        placeholder="reporter / assignee / contact / someone@example.com"
        hint="A role, a literal email address, or a template token."
        onChange={(to) => set({ to })}
      />
      {role && (
        <p data-send-email-per-item className="text-xs text-fg-muted">
          “{text("to").trim().toLowerCase()}” is a property of one issue, so this sends once per issue. Name an
          address to send a single digest instead.
        </p>
      )}
      <TextField
        label="Subject"
        value={text("subject")}
        placeholder="[{{item.key}}] {{item.title}}"
        hint={TEMPLATE_HINT}
        onChange={(event) => set({ subject: event.target.value })}
      />
      <TextArea
        label="Body"
        rows={3}
        value={text("body")}
        placeholder="{{actor.name}} updated {{item.key}}…"
        onChange={(event) => set({ body: event.target.value })}
      />
      {/* RADD-1318: on the ticket's email thread, so the requester's reply lands back on the issue. */}
      <CheckboxField
        label="Send on the issue's email thread"
        help="Replies come back to the issue, and the message reads as from the desk. Keep [{{item.key}}] in the subject."
        checked={Boolean(params.thread)}
        onChange={(thread) => set({ thread })}
      />
    </div>
  );
}
