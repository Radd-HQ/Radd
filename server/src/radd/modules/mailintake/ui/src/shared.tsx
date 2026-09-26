import type { ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api, Button, ButtonVariant, ErrorText, Slot, useConfirm, type ConfirmOptions } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT, type ProjectSelectProps } from "@radd-plugin-ui/projects/picker-contract";
import type { MailKindInfo } from "./types";

/**
 * A project picker, as the projects plugin contributes it (a contract, never
 * its source): it resolves the selected project and loads a bounded catalog
 * only when opened, so no dialog here downloads every project up front.
 */
export function ProjectField(props: ProjectSelectProps) {
  return (
    <Slot
      id={PROJECT_SELECT_SLOT}
      {...props}
      fallback={<span className="text-xs text-fg-muted">Projects are unavailable.</span>}
    />
  );
}

/** Small uppercase tag — a kind, a "default" marker, a disabled state. */
export function Chip({ children, tone }: { children: ReactNode; tone?: "muted" }) {
  return (
    <span
      className={
        "rounded px-1.5 py-px text-[10px] uppercase tracking-wide " +
        (tone === "muted" ? "bg-elevated text-fg-faint" : "bg-elevated text-fg-secondary")
      }
    >
      {children}
    </span>
  );
}

/** Labeled checkbox with an indented help line (the ProviderDialog idiom). */
export function CheckboxField({
  label,
  help,
  checked,
  onChange,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div>
      <label className="flex items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          className="size-3.5 accent-accent"
        />
        {label}
      </label>
      {help && <p className="mt-0.5 pl-[22px] text-xs text-fg-muted">{help}</p>}
    </div>
  );
}

/** The kind's entry in the catalog `GET /mail/kinds` returned. */
export function findKind(
  kinds: MailKindInfo[] | undefined,
  kind: string,
): MailKindInfo | undefined {
  return (kinds ?? []).find((info) => info.kind === kind);
}

/** The kind's display name, falling back to the raw value for a kind this
 *  build does not know (a row written by a newer server). */
export function kindLabel(kinds: MailKindInfo[] | undefined, kind: string): string {
  return findKind(kinds, kind)?.name ?? kind;
}

/** A preset's precondition (app passwords): Google/Microsoft reject account passwords and say so only in the relay error. */
export function KindGuidance({ info }: { info?: MailKindInfo }) {
  if (!info?.guidance) return null;
  return (
    <p className="rounded-md border border-subtle bg-surface/60 px-3 py-2 text-[11px] text-fg-secondary">
      {info.guidance}
      {info.help_url && (
        <>
          {" "}
          <a
            href={info.help_url}
            target="_blank"
            rel="noreferrer"
            className="text-accent-text underline underline-offset-2"
          >
            How to create one
          </a>
        </>
      )}
    </p>
  );
}

/** The connection line under a source/sender row: what it will ACTUALLY dial. */
export function connectionLine(username: string, host: string, port: number): string {
  return `${username || "—"} at ${host || "—"}:${port}`;
}

/** Save (POST when new, PATCH when it exists) and delete for one source or sender row; either
 *  refreshes the list and closes the dialog. A blank `secret` is omitted — omitted means unchanged,
 *  so editing a port never re-types a password. */
export function useRowEditor(listKey: readonly string[], collectionPath: string, rowPath: string | null, onClose: () => void) {
  const queryClient = useQueryClient();
  const done = async () => {
    await queryClient.invalidateQueries({ queryKey: listKey });
    onClose();
  };
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => {
      if (!body.secret) delete body.secret;
      return rowPath ? api.patch(rowPath, body) : api.post(collectionPath, body);
    },
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => api.delete(rowPath!), onSuccess: done });
  return { save, remove };
}

type RowEditor = ReturnType<typeof useRowEditor>;

/** A row dialog's error line and footer: Delete (existing rows, behind a confirm) | Cancel | Save. */
export function RowDialogFooter({ save, remove, confirmDelete, canSave, onSave, onClose }: RowEditor & {
  /** The delete prompt; null for a row that does not exist yet. */
  confirmDelete: ConfirmOptions | null;
  canSave: boolean;
  onSave: () => void;
  onClose: () => void;
}) {
  const [confirmDialog, confirm] = useConfirm();
  return (
    <>
      {(save.isError || remove.isError) && (
        <ErrorText error={save.isError ? save.error : remove.error} />
      )}
      <div className="flex justify-between gap-2">
        {confirmDelete ? (
          <Button
            variant={ButtonVariant.dangerGhost}
            onClick={() => void confirm(confirmDelete).then((ok) => ok && remove.mutate())}
          >
            <Trash2 size={13} aria-hidden />
            Delete
          </Button>
        ) : (
          <span />
        )}
        <span className="flex gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={save.isPending || !canSave}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </span>
      </div>
      {confirmDialog}
    </>
  );
}
