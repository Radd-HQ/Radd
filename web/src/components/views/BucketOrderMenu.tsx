import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ListOrdered } from "lucide-react";
import type { ViewGroup } from "../../lib/view-utils";
import { Button } from "../Button";

/**
 * Per-VIEW bucket ordering (RADD-855): the current columns (and, on boards
 * with swimlanes, the lanes) with up/down controls. A move writes the FULL
 * key list to the view (`column_order`/`swimlane_order`) through the ordinary
 * view PATCH — shared and edit-gated like `group_by`, unlike the personal
 * DisplayMenu beside it. Buckets a future axis adds simply append after the
 * listed ones (the applyBucketOrder contract), so this list can never strand
 * a new state or category.
 */
export function BucketOrderMenu({
  columns,
  lanes,
  onReorderColumns,
  onReorderLanes,
}: {
  columns: ViewGroup[];
  /** Empty = no swimlane axis; the lanes section hides. */
  lanes: ViewGroup[];
  onReorderColumns: (keys: string[]) => void;
  onReorderLanes: (keys: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const move = (
    buckets: ViewGroup[],
    index: number,
    delta: -1 | 1,
    apply: (keys: string[]) => void,
  ) => {
    const keys = buckets.map((bucket) => bucket.key);
    const target = index + delta;
    if (target < 0 || target >= keys.length) return;
    [keys[index], keys[target]] = [keys[target], keys[index]];
    apply(keys);
  };

  const section = (
    label: string,
    buckets: ViewGroup[],
    apply: (keys: string[]) => void,
  ) => (
    <div className="flex flex-col gap-0.5">
      <p className="px-1 text-[10px] font-medium uppercase tracking-wide text-fg-faint">{label}</p>
      {buckets.map((bucket, index) => (
        <div key={bucket.key} className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-elevated">
          <span className="flex-1 truncate text-xs text-fg">{bucket.label}</span>
          <button
            type="button"
            onClick={() => move(buckets, index, -1, apply)}
            disabled={index === 0}
            aria-label={`Move ${bucket.label} earlier`}
            className="rounded p-0.5 text-fg-faint hover:text-fg cursor-pointer disabled:cursor-default disabled:opacity-30"
          >
            <ArrowUp size={12} />
          </button>
          <button
            type="button"
            onClick={() => move(buckets, index, 1, apply)}
            disabled={index === buckets.length - 1}
            aria-label={`Move ${bucket.label} later`}
            className="rounded p-0.5 text-fg-faint hover:text-fg cursor-pointer disabled:cursor-default disabled:opacity-30"
          >
            <ArrowDown size={12} />
          </button>
        </div>
      ))}
    </div>
  );

  return (
    <div ref={rootRef} className="relative">
      <Button variant="ghost" size="sm" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <ListOrdered size={12} aria-hidden />
        Order
      </Button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 flex w-60 flex-col gap-3 rounded-lg border border-strong bg-overlay p-2 shadow-pop animate-menu-in">
          {section("Columns", columns, onReorderColumns)}
          {lanes.length > 0 && section("Swimlanes", lanes, onReorderLanes)}
          <p className="px-1 text-[10px] text-fg-faint">
            Saved on this view for everyone who sees it. New buckets appear at the end.
          </p>
        </div>
      )}
    </div>
  );
}
