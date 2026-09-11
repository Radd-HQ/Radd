import { CycleSelect } from "../cycles/CycleSelect";
import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { RELEASE_STATUS_META } from "../../lib/meta";
import { releasesQuery } from "../../lib/queries";
import type { Item, ItemUpdate } from "../../lib/types";
import { Select } from "../Select";

/**
 * Spec-18 planning pickers for the item detail grid: Cycle + Release selects
 * (each with the selected entity's status dot) and native Start/Target date
 * inputs. An empty value clears the field (PATCH with `null`).
 */

const dateClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]";

interface PlanningFieldsProps {
  projectId: string;
  item: Item;
  onPatch: (patch: ItemUpdate) => void;
}

export function PlanningFields({ projectId, item, onPatch }: PlanningFieldsProps) {
  return (
    <>
      <CyclePicker item={item} onPatch={onPatch} />
      <ReleasePicker projectId={projectId} item={item} onPatch={onPatch} />
      <DateField
        label="Start date"
        value={item.start_date ?? null}
        onChange={(value) => onPatch({ start_date: value })}
      />
      <DateField
        label="Target date"
        value={item.target_date ?? null}
        onChange={(value) => onPatch({ target_date: value })}
      />
    </>
  );
}

export function CyclePicker({
  item,
  onPatch,
}: {
  item: Item;
  onPatch: (patch: ItemUpdate) => void;
}) {
  const selected = item.cycle ?? null;
  return (
    <div className="flex flex-col gap-1.5">
      <CycleSelect label="Cycle" value={selected?.id ?? ""} selectedLabel={selected?.name}
        onChange={value => onPatch({ cycle_id: value || null })} />
      {/* Carryover trail (spec 56): cycles this item was in before — first-class
          data (SLQ `past_cycle`), not just an audit-log footnote. */}
      {(item.past_cycles ?? []).length > 0 && (
        <div className="flex flex-wrap items-baseline gap-1 text-[11px] text-fg-muted">
          <span>Previously in</span>
          {(item.past_cycles ?? []).map((cycle) => (
            <span
              key={cycle.id}
              className="rounded border border-strong/70 bg-elevated/50 px-1.5 py-px text-fg-secondary"
              title={`Carried over from ${cycle.name}`}
            >
              {cycle.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function ReleasePicker({
  projectId,
  item,
  onPatch,
}: {
  projectId: string;
  item: Item;
  onPatch: (patch: ItemUpdate) => void;
}) {
  const releases = useQuery(releasesQuery(projectId));
  const selected = item.release ?? null;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="release-picker" className="text-xs font-medium text-fg-secondary">
        Release
      </label>
      <div className="relative">
        {selected && (
          <span
            className={`pointer-events-none absolute left-2 top-1/2 size-2 -translate-y-1/2 rounded-full ${RELEASE_STATUS_META[selected.status].dotClassName}`}
            aria-hidden
          />
        )}
        <Select
          id="release-picker"
          value={selected?.id ?? ""}
          onChange={(value) => onPatch({ release_id: value || null })}
          className="w-full"
          triggerClassName={selected ? "pl-6" : ""}
          options={[
            { value: "", label: "No release" },
            ...(releases.data ?? []).map((release) => ({
              value: release.id,
              label: `${release.version}${
                release.name && release.name !== release.version ? ` — ${release.name}` : ""
              }`,
            })),
          ]}
        />
      </div>
    </div>
  );
}

export function DateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        className={dateClasses}
      />
    </div>
  );
}
