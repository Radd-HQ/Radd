import type { ReactNode } from "react";
import type { MailKindInfo } from "../../../lib/types";

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

/**
 * The operational precondition a preset carries — app passwords, in both
 * cases. Stating it in the form is the difference between one paste and an
 * authentication failure nobody can explain: Google and Microsoft both reject
 * an account password over SMTP/IMAP, and say so only in the relay's error.
 */
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
