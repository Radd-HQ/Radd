import { useState, type FormEvent } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "../Button";
import { DropdownMenu } from "../DropdownMenu";
import { Popover } from "../Popover";

/**
 * Column-header ⋯ menu for state-axis boards (spec 76): "Set WIP limit…" opens
 * a small number-input popover that PATCHes the view's `wip_limits`. Rendered
 * only when the actor can edit the view AND the column key is a state id
 * (project-scoped boards — name-keyed all-projects buckets can't carry limits).
 * Limits are SOFT: the header count recolors, drops are never blocked.
 */
export function WipLimitMenu({
  columnLabel,
  limit,
  onSetLimit,
}: {
  columnLabel: string;
  /** The column's current limit; undefined = none set. */
  limit: number | undefined;
  /** null clears this column's limit. */
  onSetLimit: (limit: number | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const close = () => setEditing(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(draft);
    if (Number.isInteger(value) && value >= 1) {
      onSetLimit(value);
      close();
    }
  };

  return (
    <span className="relative ml-auto">
      <DropdownMenu
        label={`${columnLabel} column options`}
        align="end"
        items={[
          {
            kind: "action",
            label: "Set work-in-progress limit…",
            onSelect: () => {
              setDraft(limit !== undefined ? String(limit) : "");
              setEditing(true);
            },
          },
        ]}
        trigger={({ ref, open, toggle }) => (
          <button
            ref={ref}
            type="button"
            onClick={toggle}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={`${columnLabel} column options`}
            className="rounded p-0.5 text-fg-faint opacity-0 transition-opacity hover:bg-elevated hover:text-fg focus-visible:opacity-100 group-hover/column:opacity-100 cursor-pointer"
          >
            <MoreHorizontal size={14} aria-hidden />
          </button>
        )}
      />

      <Popover
        open={editing}
        onClose={close}
        label={`WIP limit for ${columnLabel}`}
        className="w-48 p-2"
      >
            <form onSubmit={submit} className="flex flex-col gap-2">
              <p className="text-xs text-fg-muted">Warn when this column reaches its intended workload. This does not hide issues or block moves.</p>
              <label className="text-[11px] font-medium text-fg-secondary">
                WIP limit for {columnLabel}
              </label>
              <input
                type="number"
                min={1}
                step={1}
                autoFocus
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="e.g. 3"
                className="h-7 rounded-md border border-strong bg-base px-2 text-xs text-heading focus:outline-2 focus:outline-offset-1 focus:outline-focus"
              />
              <div className="flex items-center gap-2">
                <Button
                  type="submit"
                  size="sm"
                  disabled={!(Number.isInteger(Number(draft)) && Number(draft) >= 1)}
                >
                  Set
                </Button>
                {limit !== undefined && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      onSetLimit(null);
                      close();
                    }}
                  >
                    Clear
                  </Button>
                )}
                <Button size="sm" variant="ghost" className="ml-auto" onClick={close}>
                  Cancel
                </Button>
              </div>
            </form>
      </Popover>
    </span>
  );
}
