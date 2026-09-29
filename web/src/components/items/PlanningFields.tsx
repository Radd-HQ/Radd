import { CycleSelect } from "../cycles/CycleSelect";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { RELEASE_STATUS_META } from "../../lib/meta";
import { releasesQuery } from "../../lib/queries";
import { ItemKind, type Item, type ItemUpdate } from "../../lib/types";
import { Select } from "../Select";
import { HiddenParentField, ParentPickerField, parentLabel, requiredParentKind } from "./ParentPicker";

/**
 * RADD-1472: where the item sits in the hierarchy — an issue's epic, a subtask's parent issue (an
 * epic has none, so this renders nothing). Search-as-you-type over the required kind; a pick
 * PATCHes `parent_id`, Clear sends null. A subtask cannot be cleared — the server refuses an
 * orphan — so it offers only a move, and the hint says why.
 */
export function ParentField({
  item,
  onPatch,
}: {
  item: Item;
  onPatch: (patch: ItemUpdate) => void;
}) {
  const kind = item.kind ?? ItemKind.issue;
  const parentKind = requiredParentKind(kind);
  const excludeIds = useMemo(() => new Set([item.id]), [item.id]);
  if (parentKind === null) return null;
  if (item.parent_hidden) return <HiddenParentField kind={kind} />;
  const isSubtask = kind === ItemKind.subtask;
  return (
    <ParentPickerField
      id="parent-picker"
      label={parentLabel(kind)}
      projectId={item.project_id}
      kind={parentKind}
      value={item.parent ?? null}
      excludeIds={excludeIds}
      onChange={(next) => onPatch({ parent_id: next ? next.id : null })}
      allowClear={!isSubtask}
      hint={isSubtask ? "A subtask always belongs to an issue — pick another one to move it." : undefined}
    />
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
      <CycleSelect label="Cycle" value={selected?.id ?? ""} selectedLabel={selected?.name} projectId={item.project_id}
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
