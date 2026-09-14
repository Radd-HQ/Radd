import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { HISTORY_FIELD_LABELS, PRIORITY_META } from "../../lib/meta";
import type { HistoryChange, LinkChangeRef, PriorityValue } from "../../lib/types";

/**
 * The one renderer for a change list (spec 123): `{field, from, to}` as
 * old → new, `{added, removed}` as ±chips, a bare `{field}` (a hidden value —
 * a body, a secret) or a `redacted` entry as "changed". Shared by the issue
 * History tab, the audit log and the settings history panels, so the three
 * cannot disagree about what a diff looks like.
 *
 * Labels: the item vocabulary (`HISTORY_FIELD_LABELS`) where it applies, an
 * entry's own `name` when the emitter supplied one (custom fields, widget
 * labels), else the field key humanised.
 */
export function ChangeList({ changes, className = "" }: { changes: HistoryChange[]; className?: string }) {
  if (changes.length === 0) return null;
  return (
    <ul className={`flex flex-col gap-0.5 ${className}`}>
      {changes.map((change, index) => (
        <li key={index} className="text-[13px] leading-relaxed text-fg">
          <ChangeLine change={change} />
        </li>
      ))}
    </ul>
  );
}

export function changeLabel(change: HistoryChange): string {
  if (change.field === "custom_field") return change.name ?? "Field";
  if (change.name) return change.name;
  return HISTORY_FIELD_LABELS[change.field] ?? humanize(change.field);
}

export function humanize(key: string): string {
  const words = key.replace(/[._]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

export function ChangeLine({ change }: { change: HistoryChange }): ReactNode {
  const label = changeLabel(change);
  const hidden =
    change.redacted ||
    (!("from" in change) && !("to" in change) && !("added" in change) && !("removed" in change));
  if (hidden) {
    return (
      <>
        <FieldLabel>{label}</FieldLabel> changed
      </>
    );
  }
  if (change.field === "flagged") {
    return change.to ? "Flagged this issue" : "Removed the flag";
  }
  if (change.field === "links") {
    return (
      <>
        <FieldLabel>{label}</FieldLabel>{" "}
        <LinkDelta added={asLinks(change.added)} removed={asLinks(change.removed)} />
      </>
    );
  }
  if (Array.isArray(change.added) || Array.isArray(change.removed)) {
    return (
      <>
        <FieldLabel>{label}</FieldLabel>{" "}
        <ChipDelta added={asStrings(change.added)} removed={asStrings(change.removed)} />
      </>
    );
  }
  return (
    <>
      <FieldLabel>{label}:</FieldLabel>{" "}
      <ValueSpan field={change.field} value={change.from} muted />
      <ArrowRight size={12} className="mx-1 inline align-[-1px] text-fg-faint" aria-hidden />
      <ValueSpan field={change.field} value={change.to} />
    </>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-fg-muted">{children}</span>;
}

function ValueSpan({
  field,
  value,
  muted = false,
}: {
  field: string;
  value: HistoryChange["from"];
  muted?: boolean;
}) {
  const text = formatValue(field, value);
  return <span className={muted ? "text-fg-muted line-through" : "text-heading"}>{text}</span>;
}

export function formatValue(field: string, value: HistoryChange["from"]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "priority") {
    const meta = PRIORITY_META[value as PriorityValue];
    if (meta) return meta.label;
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function ChipDelta({ added, removed }: { added: string[]; removed: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {added.map((name) => (
        <span key={`+${name}`} className="text-emerald-400">
          +{name}
        </span>
      ))}
      {removed.map((name) => (
        <span key={`-${name}`} className="text-red-400">
          −{name}
        </span>
      ))}
    </span>
  );
}

function LinkDelta({ added, removed }: { added: LinkChangeRef[]; removed: LinkChangeRef[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {added.map((link) => (
        <span key={`+${link.key}`} className="text-emerald-400">
          +{link.key} ({link.link_type})
        </span>
      ))}
      {removed.map((link) => (
        <span key={`-${link.key}`} className="text-red-400">
          −{link.key} ({link.link_type})
        </span>
      ))}
    </span>
  );
}

/** A collection entry as text: strings as they are, objects by their most legible key. */
function asStrings(value: HistoryChange["added"]): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => {
    if (typeof entry === "string") return entry;
    if (entry && typeof entry === "object") {
      const record = entry as unknown as Record<string, unknown>;
      const parts = ["subject", "name", "key", "field", "title"]
        .map((k) => record[k])
        .filter((v): v is string => typeof v === "string");
      const scope = typeof record.scope === "string" ? ` (${record.scope})` : "";
      const role = typeof record.role === "string" && parts.length ? ` as ${record.role}` : "";
      if (parts.length) return `${parts[0]}${role}${scope}`;
      return JSON.stringify(entry);
    }
    return String(entry);
  });
}

function asLinks(value: HistoryChange["added"]): LinkChangeRef[] {
  return Array.isArray(value)
    ? value.filter((v): v is LinkChangeRef => typeof v === "object" && v !== null && "link_type" in v)
    : [];
}
