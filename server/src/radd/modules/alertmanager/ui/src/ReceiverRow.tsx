import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BellRing, Copy } from "lucide-react";
import { api, copyText, Button, SelectField, Slot, Switch, TextField } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT } from "@radd-plugin-ui/projects/picker-contract";
import type { AlertReceiver, ReceiverPatch, StateChoice } from "./types";

export function webhookUrl(token: string): string {
  return `${window.location.origin}/api/v1/integrations/alertmanager?token=${token}`;
}

/**
 * One receiver: where its alerts become issues, and what it does to them
 * (RADD-1370) — a label on creation, an internal comment on each repeat and on
 * resolution, and a move to one of its project's states when resolved. Each is
 * off until set here; the triggers fire either way.
 */
export function ReceiverRow({ receiver, revealedToken, onPatch, onNewToken, onDelete }: {
  receiver: AlertReceiver;
  revealedToken: string | null;
  onPatch: (patch: ReceiverPatch) => void;
  onNewToken: () => void;
  onDelete: () => void;
}) {
  const [label, setLabel] = useState(receiver.label);
  useEffect(() => setLabel(receiver.label), [receiver.label]);
  const states = useQuery({
    queryKey: ["alertmanager", "states", receiver.project_id],
    enabled: Boolean(receiver.project_id),
    queryFn: ({ signal }) => api.get<StateChoice[]>("/states", { signal, query: { project_id: receiver.project_id! } }),
    staleTime: 60_000,
  });
  const savedState = receiver.resolve_state_id;
  const stateKnown = !savedState || (states.data ?? []).some((state) => state.id === savedState);

  return (
    <li className="rounded-lg border border-subtle bg-surface/40" data-receiver={receiver.name}>
      <div className="flex flex-wrap items-center gap-3 px-3 py-2.5">
        <BellRing size={14} className="text-fg-muted" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-heading">{receiver.name}</span>
        {!receiver.project_id && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-status-warning-ink">no project</span>}
        {!receiver.active && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-muted">inactive</span>}
        <Button size="sm" variant="secondary" onClick={() => onPatch({ active: !receiver.active })}>
          {receiver.active ? "Disable" : "Enable"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onNewToken}>New token…</Button>
        <Button size="sm" variant="ghost" onClick={onDelete}>Delete…</Button>
      </div>
      <div className="flex flex-wrap items-end gap-3 border-t border-subtle/60 px-3 py-3">
        <div className="w-64">
          <Slot id={PROJECT_SELECT_SLOT} value={receiver.project_id ?? ""} label="Project" emptyLabel="No project"
            onChange={(id: string) => onPatch({ project_id: id || null })}
            fallback={<span className="text-xs text-fg-muted">Projects are unavailable.</span>} />
        </div>
        <div className="w-48">
          <TextField label="Label new issues" placeholder="none" value={label} maxLength={100}
            onChange={(event) => setLabel(event.target.value)}
            onBlur={() => { if (label.trim() !== receiver.label) onPatch({ label: label.trim() }); }} />
        </div>
        <div className="w-56">
          <SelectField label="When resolved, move the issue to" value={savedState ?? ""}
            disabled={!receiver.project_id || states.isPending}
            onChange={(event) => onPatch({ resolve_state_id: event.target.value || null })}>
            <option value="">Don't move it</option>
            {!stateKnown && states.isSuccess && <option value={savedState ?? ""}>A deleted state</option>}
            {(states.data ?? []).map((state) => <option key={state.id} value={state.id}>{state.name}</option>)}
          </SelectField>
        </div>
        {/* Never disabled while another field saves: each is its own PATCH, and a
            label's blur-save starting as this is clicked would swallow the click. */}
        <Switch label="Comment when it fires again or resolves" checked={receiver.comment_updates}
          onChange={(next) => onPatch({ comment_updates: next })} data-comment-updates={receiver.name} />
      </div>
      {revealedToken && (
        <div className="flex flex-col gap-2 border-t border-subtle/60 px-3 py-3" data-receiver-url>
          <div className="flex items-end gap-2">
            <div className="flex-1"><TextField label="Webhook URL" readOnly value={webhookUrl(revealedToken)} /></div>
            <Button size="sm" variant="secondary" onClick={() => void copyText(webhookUrl(revealedToken))}>
              <Copy size={13} aria-hidden /> Copy
            </Button>
          </div>
          <p className="text-[11px] text-fg-muted">Shown once — the token is not stored anywhere you can read it back.</p>
        </div>
      )}
    </li>
  );
}
