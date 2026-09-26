import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { Slot, SlotId } from "./slots";
import type { HistoryChange } from "./changes";
export function ChangeList({ changes, entityType, className = "" }: { changes: HistoryChange[]; entityType?: string; className?: string }) {
  if (changes.length === 0) return null;
  return (
    <ul className={`flex flex-col gap-0.5 ${className}`}>
      {changes.map((change, index) => (
        <li key={index} className="text-[13px] leading-relaxed text-fg">
          <Slot id={SlotId.entityChangeLine} match={entityType ?? ""} change={safeChange(change)} fallback={<ChangeLine change={change} />} errorFallback={<ChangeLine change={change} />} />
        </li>
      ))}
    </ul>
  );
}

/** Withheld values never reach a presentation contribution. */
function safeChange(change: HistoryChange): HistoryChange {
  return change.redacted ? { field: change.field, name: change.name, key: change.key, redacted: true } : change;
}
export function changeLabel(change: HistoryChange): string { return change.name || humanize(change.field); }

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
      <ValueSpan value={change.from} muted />
      <ArrowRight size={12} className="mx-1 inline align-[-1px] text-fg-faint" aria-hidden />
      <ValueSpan value={change.to} />
    </>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-fg-muted">{children}</span>;
}

function ValueSpan({
  value,
  muted = false,
}: {
  value: HistoryChange["from"];
  muted?: boolean;
}) {
  const text = formatChangeValue(value);
  return <span className={muted ? "text-fg-muted line-through" : "text-heading"}>{text}</span>;
}

export function formatChangeValue(value: HistoryChange["from"]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return legible(value as Record<string, unknown>);
  return String(value);
}

/** A structured value by a generic legible key — its name, title, label or key — instead of raw JSON
 * (RADD-1376); only a value with none of them shows its JSON, so nothing is hidden. Domain wording
 * (a grant's "Alice as manager (project TEST)") is the owner's contributed formatter, not this. */
function legible(record: Record<string, unknown>): string {
  const text = ["name", "title", "label", "key"]
    .map((key) => record[key])
    .find((value): value is string => typeof value === "string" && value !== "");
  return text ?? JSON.stringify(record);
}

function ChipDelta({ added, removed }: { added: string[]; removed: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {added.map((name, index) => (
        <span key={`+${index}`} className="text-status-success-ink">
          +{name}
        </span>
      ))}
      {removed.map((name, index) => (
        <span key={`-${index}`} className="text-status-danger-ink">
          −{name}
        </span>
      ))}
    </span>
  );
}

/** A collection's entries as text: strings as they are, objects by their most legible key. */
function asStrings(value: HistoryChange["added"]): string[] {
  return Array.isArray(value) ? value.map(formatChangeValue) : [];
}
