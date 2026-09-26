import { DirectorySelect, IconButton, useCurrentUser, type DirectoryChoice } from "@radd/plugin-sdk";
import type { TransitionRuleEditorProps } from "@radd-plugin-ui/workflow/transition-rule-contract";
import { User as UserIcon, Users, X } from "lucide-react";

/** The check this plugin serves on the kernel TRANSITION_CHECK socket (backend `ApprovalCheck`). */
export const REQUIRE_APPROVAL = "require_approval";

/** One approver entry (spec 107): a user approves personally; a team needs `required` approvals
 *  from its current members. `name` is a display snapshot the server re-resolves on write. */
interface ApproverEntry {
  kind: "user" | "team";
  id: string;
  name?: string;
  required?: number;
}

/**
 * "Require approval" on a workflow transition row (RADD-1383): contributed into the transitions
 * editor's rule slot, so the host carries no approval vocabulary and a disabled approvals plugin
 * takes its editor with it. Every entry must be satisfied; the server validates the subjects and
 * snapshots their names. Removing the last approver removes the rule.
 */
export function ApprovalRuleEditor({ rules, onChange, canManage, saving }: TransitionRuleEditorProps) {
  const me = useCurrentUser();
  const rule = rules.find((entry) => entry.check === REQUIRE_APPROVAL);
  const entries = (rule?.params.approvers as ApproverEntry[] | undefined) ?? [];
  const write = (next: ApproverEntry[]) =>
    onChange(REQUIRE_APPROVAL, next.length > 0 ? { ...rule?.params, approvers: next } : null);
  const add = (kind: ApproverEntry["kind"], choice: DirectoryChoice | null) => {
    if (!choice || entries.some((entry) => entry.kind === kind && entry.id === choice.id)) return;
    write([...entries, { kind, id: choice.id, name: choice.name, ...(kind === "team" ? { required: 1 } : {}) }]);
  };
  const setRequired = (index: number, required: number) => {
    if (!Number.isInteger(required) || required < 1) return;
    write(entries.map((entry, i) => (i === index ? { ...entry, required } : entry)));
  };
  const disabled = !canManage || saving;

  return (
    <div data-approval-rule>
      <label className="mt-2 flex items-center gap-1.5 text-xs text-fg">
        <input
          type="checkbox"
          checked={rule !== undefined}
          // Seed with the configuring user: the server refuses a rule with no approver.
          onChange={() => (rule ? onChange(REQUIRE_APPROVAL, null) : me && write([{ kind: "user", id: me.id, name: me.name }]))}
          disabled={disabled || (rule === undefined && !me)}
          className="size-3.5 accent-accent"
        />
        Require approval
      </label>
      {rule && (
        <div className="mt-2 flex flex-col gap-1.5 rounded-md border border-subtle bg-surface/40 px-3 py-2">
          <span className="text-[11px] uppercase tracking-wide text-fg-faint">
            Approvers — every entry must be satisfied
          </span>
          {entries.map((entry, index) => (
            <div key={`${entry.kind}:${entry.id}`} className="flex flex-wrap items-center gap-2 text-xs text-fg" data-approver={entry.id}>
              {entry.kind === "team"
                ? <Users size={13} className="text-fg-muted" aria-hidden />
                : <UserIcon size={13} className="text-fg-muted" aria-hidden />}
              <span>{entry.name ?? entry.id}</span>
              {entry.kind === "team" && (
                <label className="flex items-center gap-1.5 text-[11px] text-fg-secondary">
                  — requires
                  <input
                    type="number"
                    min={1}
                    value={entry.required ?? 1}
                    onChange={(event) => setRequired(index, Number(event.target.value))}
                    disabled={disabled}
                    className="h-6 w-14 rounded border border-strong bg-surface px-1.5 text-xs text-fg"
                  />
                  member approval(s)
                </label>
              )}
              {canManage && (
                <IconButton
                  danger
                  onClick={() => write(entries.filter((_, i) => i !== index))}
                  disabled={saving}
                  aria-label={`Remove approver ${entry.name ?? entry.id}`}
                >
                  <X size={12} />
                </IconButton>
              )}
            </div>
          ))}
          {canManage && (
            <div className="flex flex-wrap items-center gap-2">
              <DirectorySelect source="auth.people" value={null} onChange={(choice) => add("user", choice)}
                label="Add a person as approver" emptyLabel="Add a person…" disabled={saving} />
              <DirectorySelect source="teams.teams" value={null} onChange={(choice) => add("team", choice)}
                label="Add a team as approver" emptyLabel="Add a team…" disabled={saving} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
