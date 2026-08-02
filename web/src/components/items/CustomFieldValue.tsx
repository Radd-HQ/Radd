import { formatDate } from "../../lib/dates";
import { formatDuration } from "../../lib/duration";
import { FieldType, type CustomFieldValue } from "../../lib/types";
import { LabelChip } from "./ItemBadges";

/**
 * Typed rendering for a custom-field VALUE (spec 108, extracted for spec 109):
 * shared by list-column cells and board-card cells so both surfaces read a
 * field the same way. `usersById` resolves user-field ids to names (fetched by
 * the surface only while such a field is visible).
 */

export function Dash() {
  return <span className="text-[11px] text-fg-faint">—</span>;
}

export function DateText({ iso }: { iso: string }) {
  return <span className="text-xs tabular-nums text-fg-secondary">{formatDate(iso)}</span>;
}

/** True when the value should render as an empty cell (list: a dash; card:
 * nothing at all). */
export function isEmptyCustomValue(value: CustomFieldValue | null | undefined): boolean {
  return (
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

export function CustomCell({
  type,
  value,
  usersById,
  durations,
}: {
  type: string;
  value: CustomFieldValue | null;
  usersById?: Map<string, string>;
  durations: Parameters<typeof formatDuration>[1];
}) {
  if (isEmptyCustomValue(value)) {
    return <Dash />;
  }
  switch (type) {
    case FieldType.boolean:
      return <span className="text-xs text-fg-secondary">{value === true ? "Yes" : "No"}</span>;
    case FieldType.number:
      return <span className="text-xs tabular-nums text-fg-secondary">{String(value)}</span>;
    case FieldType.duration:
      // Duration fields store whole minutes (fields registry contract).
      return (
        <span className="text-xs tabular-nums text-fg-secondary">
          {formatDuration(Number(value) * 60, durations)}
        </span>
      );
    case FieldType.date:
      return <DateText iso={String(value)} />;
    case FieldType.select:
      return <LabelChip name={String(value)} />;
    case FieldType.multi_select:
      return (
        <span className="truncate text-xs text-fg-secondary">
          {(Array.isArray(value) ? value : [value]).map(String).join(", ")}
        </span>
      );
    case FieldType.user: {
      const name = usersById?.get(String(value));
      return name ? (
        <span className="truncate text-xs text-fg-secondary">{name}</span>
      ) : (
        <Dash />
      );
    }
    case FieldType.url:
      return (
        <a
          href={String(value)}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => event.stopPropagation()}
          className="truncate text-xs text-accent-text underline-offset-2 hover:underline"
        >
          {String(value)}
        </a>
      );
    default: // text
      return <span className="truncate text-xs text-fg-secondary">{String(value)}</span>;
  }
}
