import { useState } from "react";

/**
 * Pick a table's size by dragging across a grid (RADD-750).
 *
 * The complaint this answers is that inserting gave you a fixed default you
 * then had to correct — add a column, delete two rows — which is several edits
 * to reach the shape you already knew you wanted. Sweeping a grid says it once.
 *
 * The grid GROWS as you approach its edge, so a 2×2 is one small gesture and a
 * 6×8 is still reachable without a scrollbar or a number field.
 */
const MIN = 5;
const MAX = 10;
/** The header row is always one of them, so 1×1 is the smallest real table. */
const MIN_ROWS = 1;

export function TableGridPicker({
  at,
  onPick,
  onDismiss,
}: {
  at: { left: number; top: number };
  /** `rows` INCLUDES the header row, matching what the command expects. */
  onPick: (rows: number, cols: number) => void;
  onDismiss: () => void;
}) {
  const [hover, setHover] = useState({ rows: 0, cols: 0 });
  const rows = Math.min(MAX, Math.max(MIN, hover.rows + 1));
  const cols = Math.min(MAX, Math.max(MIN, hover.cols + 1));

  return (
    <>
      <div className="fixed inset-0 z-[59]" onMouseDown={onDismiss} />
      <div
        className="fixed z-[60] rounded-lg border border-strong bg-overlay p-2 shadow-modal animate-menu-in"
        style={{ left: at.left, top: at.top }}
        role="dialog"
        aria-label="Insert table"
      >
        <div
          className="flex flex-col gap-0.5"
          onMouseLeave={() => setHover({ rows: 0, cols: 0 })}
          role="grid"
          aria-label="Table size"
        >
          {Array.from({ length: rows }, (_, row) => (
            <div key={row} className="flex gap-0.5" role="row">
              {Array.from({ length: cols }, (_, col) => {
                const on = row <= hover.rows && col <= hover.cols;
                return (
                  <button
                    key={col}
                    type="button"
                    role="gridcell"
                    aria-label={`${row + 1} by ${col + 1}`}
                    data-grid-cell={`${row + 1}x${col + 1}`}
                    data-on={on ? "" : undefined}
                    onMouseEnter={() => setHover({ rows: row, cols: col })}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() =>
                      onPick(Math.max(MIN_ROWS, row + 1), col + 1)
                    }
                    className={
                      "h-4 w-4 cursor-pointer rounded-[3px] border transition-colors " +
                      (on
                        ? "border-accent bg-accent"
                        : "border-subtle bg-surface hover:border-strong")
                    }
                  />
                );
              })}
            </div>
          ))}
        </div>
        <p className="mt-1.5 text-center text-[11px] tabular-nums text-fg-muted">
          {hover.rows + 1} × {hover.cols + 1}
        </p>
      </div>
    </>
  );
}
