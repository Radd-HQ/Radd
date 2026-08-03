import { useCallback, useEffect, useRef, useState } from "react";
import { useNodeViewContext } from "@prosemirror-adapter/react";
import { AlignCenter, AlignLeft, AlignRight, Plus, Trash2 } from "lucide-react";
import { DropdownMenu, type DropdownMenuItem } from "../DropdownMenu";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import { TableAxis, type TableCommandRunner } from "./table-commands";

/**
 * A table, with handles (RADD-750).
 *
 * The engine is untouched: `prosemirror-tables` is what every ProseMirror editor
 * uses, including whichever alternative we might have switched to, so only the
 * chrome is ours. What that chrome has to do is make the operations reachable —
 * add and remove a row or column, set a column's alignment — without a
 * right-click menu nobody discovers.
 *
 * Handles are positioned from MEASURED cell rects rather than from a CSS grid
 * mirroring the table, because a table's columns are resizable and its cells
 * wrap: any layout that duplicates the table's geometry is a copy that goes
 * stale. A `ResizeObserver` re-measures when it changes.
 */
export function TableNodeView({ run }: { run: TableCommandRunner }) {
  const { node, view, getPos, contentRef, selected } = useNodeViewContext();
  const wrapRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const [cols, setCols] = useState<{ left: number; width: number }[]>([]);
  const [rows, setRows] = useState<{ top: number; height: number }[]>([]);
  const editable = view.editable;

  const measure = useCallback(() => {
    const table = tableRef.current;
    const wrap = wrapRef.current;
    if (!table || !wrap) return;
    const base = wrap.getBoundingClientRect();
    const firstRow = table.querySelector("tr");
    setCols(
      firstRow
        ? [...firstRow.children].map((cell) => {
            const rect = cell.getBoundingClientRect();
            return { left: rect.left - base.left, width: rect.width };
          })
        : [],
    );
    setRows(
      [...table.querySelectorAll("tr")].map((tr) => {
        const rect = tr.getBoundingClientRect();
        return { top: rect.top - base.top, height: rect.height };
      }),
    );
  }, []);

  useEffect(() => {
    measure();
    const table = tableRef.current;
    if (!table || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(table);
    for (const cell of table.querySelectorAll("th, td")) observer.observe(cell);
    return () => observer.disconnect();
  }, [measure, node]);

  const at = () => getPos();

  return (
    <div
      ref={wrapRef}
      data-table-block
      className={
        "radd-table group relative my-3 ml-4 mt-4 " + (selected ? "outline-2 outline-focus" : "")
      }
    >
      {editable && (
        <>
          {cols.map((col, index) => (
            <Handle
              key={`col-${index}`}
              axis={TableAxis.column}
              index={index}
              style={{ left: col.left, width: col.width, top: -14, height: 12 }}
              run={run}
              pos={at}
            />
          ))}
          {rows.map((row, index) => (
            <Handle
              key={`row-${index}`}
              axis={TableAxis.row}
              index={index}
              style={{ top: row.top, height: row.height, left: -14, width: 12 }}
              run={run}
              pos={at}
            />
          ))}
        </>
      )}
      <table ref={tableRef} className="w-full border-collapse">
        {/* prosemirror-tables' resizing plugin writes widths into cell
            `colwidth` attrs and expects a <colgroup> to apply them — its own
            table view renders one, and replacing that view meant the plugin had
            nowhere to put the width it was computing. Rebuilt here from the same
            attrs, so dragging a column edge actually moves it.

            The width is NOT stored: GFM cannot express a column width, and this
            body is markdown by design. It is a per-session affordance, and the
            markdown round-trips untouched because `colwidth` never serialises. */}
        <colgroup>
          {columnWidths(node).map((width, index) => (
            <col key={index} style={width ? { width: `${width}px` } : undefined} />
          ))}
        </colgroup>
        <tbody ref={contentRef} />
      </table>
    </div>
  );
}

/** Per-column widths from the header row's `colwidth` attrs (0 = auto). */
function columnWidths(table: ProseNode): number[] {
  const header = table.firstChild;
  if (!header) return [];
  const widths: number[] = [];
  header.forEach((cell) => {
    const colwidth = cell.attrs.colwidth as number[] | null;
    const span = Number(cell.attrs.colspan ?? 1);
    for (let i = 0; i < span; i++) widths.push(colwidth?.[i] ?? 0);
  });
  return widths;
}

/**
 * One row or column handle: a thin bar that selects its line and opens its menu.
 *
 * Selecting first is not decoration — `addColumnBefore`, `deleteRow` and
 * `setCellAttr` all act on the CURRENT cell selection, so the menu's entries
 * would apply to wherever the cursor happened to be otherwise.
 */
function Handle({
  axis,
  index,
  style,
  run,
  pos,
}: {
  axis: (typeof TableAxis)[keyof typeof TableAxis];
  index: number;
  style: React.CSSProperties;
  run: TableCommandRunner;
  pos: () => number | undefined;
}) {
  const isColumn = axis === TableAxis.column;
  const label = `${isColumn ? "Column" : "Row"} ${index + 1}`;

  const select = () => run.select(axis, index, pos());

  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      label: isColumn ? "Insert column before" : "Insert row above",
      icon: Plus,
      onSelect: () => {
        select();
        run.insert(axis, "before");
      },
    },
    {
      kind: "action",
      label: isColumn ? "Insert column after" : "Insert row below",
      icon: Plus,
      onSelect: () => {
        select();
        run.insert(axis, "after");
      },
    },
    ...(isColumn
      ? ([
          { kind: "separator" },
          {
            kind: "action",
            label: "Align left",
            icon: AlignLeft,
            onSelect: () => {
              select();
              run.align("left");
            },
          },
          {
            kind: "action",
            label: "Align centre",
            icon: AlignCenter,
            onSelect: () => {
              select();
              run.align("center");
            },
          },
          {
            kind: "action",
            label: "Align right",
            icon: AlignRight,
            onSelect: () => {
              select();
              run.align("right");
            },
          },
        ] as DropdownMenuItem[])
      : []),
    { kind: "separator" },
    {
      kind: "action",
      label: isColumn ? "Delete column" : "Delete row",
      icon: Trash2,
      danger: true,
      onSelect: () => {
        select();
        run.remove();
      },
    },
  ];

  return (
    // The absolute placement lives on a wrapper, not on the menu: the panel
    // positions itself against its trigger, so moving the menu itself would move
    // the panel too.
    <div className="absolute z-[2]" style={style}>
      <DropdownMenu
        items={items}
        label={label}
        className="h-full w-full"
        trigger={({ ref, toggle }) => (
          <button
            ref={ref}
            type="button"
            aria-label={label}
            title={label}
            data-table-handle={isColumn ? "column" : "row"}
            data-index={index}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              select();
              toggle();
            }}
            className="h-full w-full cursor-pointer rounded-[3px] bg-[var(--color-border-subtle)] opacity-0 transition-opacity hover:bg-accent group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus"
          />
        )}
      />
    </div>
  );
}
