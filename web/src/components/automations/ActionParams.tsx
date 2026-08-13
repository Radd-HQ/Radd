import { useId, useState, type ReactNode } from "react";
import { Braces } from "lucide-react";
import { AUTOMATION_CLEAR_VALUE } from "../../lib/constants";
import { COMMENT_VISIBILITY_LABELS, PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import {
  ActionType,
  CommentVisibility,
  EmailRecipient,
  type CustomFieldValue,
  type RuleAction,
} from "../../lib/types";
import { CustomFieldControl } from "../items/CustomFieldsForm";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import type { PickerData } from "./ActionsBuilder";

interface ActionParamsProps {
  action: RuleAction;
  pickers: PickerData;
  listId: string;
  onParams: (params: Record<string, CustomFieldValue>) => void;
}

/** Clearable pickers (assignee/team/cycle) share this option. */
const CLEAR_OPTION = <option value={AUTOMATION_CLEAR_VALUE}>— Clear (unset) —</option>;

/** Does this stored value carry a `{{token}}`? Mirrors the server's grammar. */
const hasToken = (value: unknown) => /\{\{\s*[a-zA-Z0-9_.]+\s*\}\}/.test(String(value ?? ""));

/**
 * A value param in two modes: PICKED, or a `{{token}}` (spec 120).
 *
 * The picker stays the default and stays a picker. Degrading every dropdown into
 * a text field so that a token could be typed into it would cost everyone the
 * affordance to buy a minority the flexibility — and would lose the vocabulary,
 * which is the part that stops a typo becoming a skip at 3am. So the token mode
 * is opt-in, per param, and the control announces which mode it is in.
 *
 * A stored value that already contains a token opens in token mode without being
 * asked, because the alternative is a select showing blank beside a value it
 * cannot represent.
 */
function TokenizableField({
  label,
  value,
  hint,
  placeholder,
  onChange,
  children,
}: {
  label: string;
  value: string;
  hint?: string;
  placeholder?: string;
  onChange: (value: string) => void;
  /** The picked-value control, rendered when not in token mode. */
  children: ReactNode;
}) {
  const [wanted, setWanted] = useState(false);
  const tokenMode = wanted || hasToken(value);
  return (
    <div className="flex flex-col gap-1" data-tokenizable={label}>
      <div className="flex items-start gap-1.5">
        <div className="min-w-0 flex-1">
          {tokenMode ? (
            <TextField
              label={label}
              value={value}
              placeholder={placeholder ?? "{{triage.answer}}"}
              hint={hint ?? "A token from a node above this one, resolved when the automation runs."}
              onChange={(event) => onChange(event.target.value)}
            />
          ) : (
            children
          )}
        </div>
        <button
          type="button"
          aria-pressed={tokenMode}
          aria-label={`Use a token for ${label}`}
          title={tokenMode ? `Pick a ${label.toLowerCase()} instead` : "Use a token instead"}
          onClick={() => {
            // The switch CLEARS whichever value the other mode cannot hold, in
            // both directions. Leaving token mode with a token stored would show
            // a select displaying its first option while holding
            // `{{triage.priority}}`; ENTERING it with a picked value stored
            // leaves "normal" sitting in the box for the token to be typed after
            // — which is exactly what a click on the picker below then produces.
            onChange("");
            setWanted(!tokenMode);
          }}
          className={
            "mt-[22px] inline-flex size-7 shrink-0 items-center justify-center rounded-[6px] border cursor-pointer " +
            (tokenMode
              ? "border-emphasis bg-accent/15 text-accent-text-strong"
              : "border-subtle text-fg-muted hover:text-heading")
          }
        >
          <Braces size={13} aria-hidden />
        </button>
      </div>
    </div>
  );
}

/** Type-specific param inputs for one action row (spec 20). */
export function ActionParams({ action, pickers, listId, onParams }: ActionParamsProps) {
  const p = action.params;
  const set = (patch: Record<string, CustomFieldValue>) => onParams({ ...p, ...patch });
  const str = (value: CustomFieldValue) => (typeof value === "string" ? value : "");

  switch (action.type) {
    case ActionType.setState:
      return (
        <TextField
          label="State name"
          value={str(p.state)}
          list={`${listId}-states`}
          placeholder="In Progress"
          // Already a free-text field, so a token needs no mode switch — the
          // hint is the whole affordance (spec 120).
          hint="A state name, or a {{token}} from a node above this one."
          onChange={(event) => set({ state: event.target.value })}
        />
      );
    case ActionType.setPriority:
      return (
        <TokenizableField
          label="Priority"
          value={str(p.priority)}
          onChange={(priority) => set({ priority })}
        >
          <SelectField
            label="Priority"
            value={str(p.priority)}
            onChange={(event) => set({ priority: event.target.value })}
          >
            {PRIORITY_ORDER.map((value) => (
              <option key={value} value={value}>
                {PRIORITY_META[value].label}
              </option>
            ))}
          </SelectField>
        </TokenizableField>
      );
    case ActionType.setAssignee:
      return (
        <TokenizableField
          label="Assignee"
          value={str(p.assignee)}
          placeholder="{{triage.owner}}"
          onChange={(assignee) => set({ assignee })}
        >
          <SelectField
            label="Assignee"
            value={str(p.assignee)}
            onChange={(event) => set({ assignee: event.target.value })}
          >
            <option value="">Select…</option>
            {CLEAR_OPTION}
            {pickers.userEmails.map((user) => (
              <option key={user.email} value={user.email}>
                {user.name} ({user.email})
              </option>
            ))}
          </SelectField>
        </TokenizableField>
      );
    case ActionType.setTeam:
      return (
        <TokenizableField
          label="Team"
          value={str(p.team)}
          placeholder="{{triage.team}}"
          onChange={(team) => set({ team })}
        >
          <SelectField
            label="Team"
            value={str(p.team)}
            onChange={(event) => set({ team: event.target.value })}
          >
            <option value="">Select…</option>
            {CLEAR_OPTION}
            {pickers.teamNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </SelectField>
        </TokenizableField>
      );
    case ActionType.assignRoundRobin:
      // No clear option and no arity control: this always runs per item (the
      // server fixes it), and "assign to nobody, round-robin" is not a thing.
      return (
        <SelectField
          label="Round-robin across team"
          value={str(p.team)}
          hint="Each item goes to the next member in turn, skipping anyone inactive or away."
          onChange={(event) => set({ team: event.target.value })}
        >
          <option value="">Select…</option>
          {pickers.teamNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </SelectField>
      );
    case ActionType.addLabel:
    case ActionType.removeLabel:
      return (
        <TextField
          label="Label"
          value={str(p.label)}
          list={`${listId}-labels`}
          placeholder="needs-triage"
          onChange={(event) => set({ label: event.target.value })}
        />
      );
    case ActionType.setCycle:
      return (
        <TokenizableField
          label="Cycle"
          value={str(p.cycle)}
          placeholder="{{triage.cycle}}"
          onChange={(cycle) => set({ cycle })}
        >
          <SelectField
            label="Cycle"
            value={str(p.cycle)}
            onChange={(event) => set({ cycle: event.target.value })}
          >
            <option value="">Select…</option>
            {CLEAR_OPTION}
            {pickers.cycleNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </SelectField>
        </TokenizableField>
      );
    case ActionType.setRelease:
      return (
        <TextField
          label="Release version"
          value={str(p.release)}
          list={`${listId}-releases`}
          placeholder="1.2.0"
          hint={`Type "${AUTOMATION_CLEAR_VALUE}" to clear`}
          onChange={(event) => set({ release: event.target.value })}
        />
      );
    case ActionType.setCustomField:
      return <CustomFieldParams pickers={pickers} params={p} set={set} />;
    case ActionType.addComment:
      return <CommentParams params={p} set={set} str={str} />;
    case ActionType.createItem:
      return (
        <div className="flex flex-col gap-2.5">
          <SelectField
            label="In project"
            value={str(p.project)}
            onChange={(event) => set({ project: event.target.value })}
          >
            <option value="">Select…</option>
            {pickers.projectKeys.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Title"
            value={str(p.title)}
            placeholder="Retro for {{payload.name}}"
            hint={TEMPLATE_HINT}
            onChange={(event) => set({ title: event.target.value })}
          />
          <TextField
            label="Description (optional)"
            value={str(p.description)}
            placeholder="Created by automation from {{event_type}}"
            onChange={(event) => set({ description: event.target.value })}
          />
        </div>
      );
    case ActionType.sendWebhook:
      return (
        <div className="flex flex-col gap-2.5">
          <TextField
            label="URL"
            value={str(p.url)}
            placeholder="https://example.com/hooks/radd"
            hint="POSTs the event JSON (rule, event_type, actor, item, payload)"
            onChange={(event) => set({ url: event.target.value })}
          />
          <TextField
            label="Secret (optional)"
            value={str(p.secret)}
            placeholder="HMAC-SHA256 → X-Radd-Signature header"
            onChange={(event) => set({ secret: event.target.value })}
          />
        </div>
      );
    case ActionType.postChat:
      return (
        <div className="flex flex-col gap-2.5">
          <TextField
            label="Incoming-webhook URL"
            value={str(p.webhook_url)}
            placeholder="https://chat.googleapis.com/v1/spaces/…"
            hint={'POSTs {"text": message} — Google Chat / Slack style'}
            onChange={(event) => set({ webhook_url: event.target.value })}
          />
          <TextField
            label="Message"
            value={str(p.message)}
            placeholder="{{actor.name}} moved {{item.key}} to {{payload.state.name}}"
            hint={TEMPLATE_HINT}
            onChange={(event) => set({ message: event.target.value })}
          />
        </div>
      );
    case ActionType.notifyUser:
      return (
        <div className="flex flex-col gap-2.5">
          <SelectField
            label="User"
            value={str(p.user)}
            onChange={(event) => set({ user: event.target.value })}
            hint="A role notifies whoever holds it on each item, so the automation is written once for the whole project."
          >
            <option value="">Select…</option>
            {/* Roles (RADD-918). The param took a literal address only, so
                "notify the assignee" had to name a person and stopped being
                true the moment the issue was reassigned. */}
            <optgroup label="By role on the item">
              <option value="assignee">Its assignee</option>
              <option value="reporter">Its reporter</option>
            </optgroup>
            <optgroup label="A specific person">
              {pickers.userEmails.map((user) => (
                <option key={user.email} value={user.email}>
                  {user.name} ({user.email})
                </option>
              ))}
            </optgroup>
          </SelectField>
          <TextField
            label="Message"
            value={str(p.message)}
            placeholder="{{item.key}} needs your attention"
            hint={TEMPLATE_HINT}
            onChange={(event) => set({ message: event.target.value })}
          />
        </div>
      );
    case ActionType.sendEmail:
      return <SendEmailParams pickers={pickers} params={p} set={set} str={str} />;
    default:
      return null;
  }
}

/** Shared hint for template-capable text params (spec 58b). The full list is in
 * the collapsible token reference below the params; this names the ones people
 * reach for, including the set-shaped `{{items.keys}}` an action running once
 * over many items needs. */
const TEMPLATE_HINT =
  "Templates: {{item.key}}, {{items.keys}}, {{actor.name}}, {{event_type}}, {{payload.<path>}}";

interface ParamsControlProps {
  pickers: PickerData;
  params: Record<string, CustomFieldValue>;
  set: (patch: Record<string, CustomFieldValue>) => void;
}

/** set_custom_field: pick a registry field key, then edit the value by its type. */
function CustomFieldParams({ pickers, params, set }: ParamsControlProps) {
  const key = typeof params.key === "string" ? params.key : "";
  const field = pickers.fields.find((definition) => definition.key === key);
  return (
    <div className="flex flex-col gap-2.5">
      <SelectField
        label="Field"
        value={key}
        onChange={(event) => set({ key: event.target.value, value: null })}
      >
        <option value="">Select…</option>
        {pickers.fields.map((definition) => (
          <option key={definition.id} value={definition.key}>
            {definition.name}
          </option>
        ))}
      </SelectField>
      {field && (
        <CustomFieldControl
          field={{ ...field, name: "Value", required: false }}
          value={params.value ?? null}
          onChange={(value) => set({ value })}
        />
      )}
    </div>
  );
}

interface CommentControlProps {
  params: Record<string, CustomFieldValue>;
  set: (patch: Record<string, CustomFieldValue>) => void;
  str: (value: CustomFieldValue) => string;
}

/** send_email (spec 66): recipient (role or literal address) + templated
 * subject/body. The recipient is a select-or-input — a datalist offering the
 * roles and every active user's address over a free-text field. */
function SendEmailParams({
  pickers,
  params,
  set,
  str,
}: ParamsControlProps & Pick<CommentControlProps, "str">) {
  const recipientsId = useId();
  return (
    <div className="flex flex-col gap-2.5">
      <datalist id={recipientsId}>
        {Object.values(EmailRecipient).map((role) => (
          <option key={role} value={role} />
        ))}
        {pickers.userEmails.map((user) => (
          <option key={user.email} value={user.email} />
        ))}
      </datalist>
      <TextField
        label="To"
        value={str(params.to)}
        list={recipientsId}
        placeholder="reporter / assignee / contact / someone@example.com"
        hint="A role (contact = the external requester) or a literal address. A role belongs to ONE issue, so choosing one makes this run per item."
        onChange={(event) => set({ to: event.target.value })}
      />
      <TextField
        label="Subject"
        value={str(params.subject)}
        placeholder="[{{item.key}}] {{item.title}}"
        hint={TEMPLATE_HINT}
        onChange={(event) => set({ subject: event.target.value })}
      />
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-fg-secondary">Body</label>
        <textarea
          value={str(params.body)}
          onChange={(event) => set({ body: event.target.value })}
          rows={2}
          placeholder="{{actor.name}} updated {{item.key}}…"
          className="rounded-md border border-strong bg-surface px-2.5 py-1.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      </div>
    </div>
  );
}

/** add_comment: body + public/internal visibility. */
function CommentParams({ params, set, str }: CommentControlProps) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-fg-secondary">Comment body</label>
        <textarea
          value={str(params.body)}
          onChange={(event) => set({ body: event.target.value })}
          rows={2}
          placeholder="Auto-added by a rule…"
          className="rounded-md border border-strong bg-surface px-2.5 py-1.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      </div>
      <SelectField
        label="Visibility"
        value={str(params.visibility)}
        onChange={(event) => set({ visibility: event.target.value })}
      >
        {Object.values(CommentVisibility).map((visibility) => (
          <option key={visibility} value={visibility}>
            {COMMENT_VISIBILITY_LABELS[visibility]}
          </option>
        ))}
      </SelectField>
    </div>
  );
}
