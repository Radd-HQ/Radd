import { callCommand } from "@milkdown/kit/utils";
import {
  addColAfterCommand,
  addColBeforeCommand,
  addRowAfterCommand,
  addRowBeforeCommand,
  deleteSelectedCellsCommand,
  selectColCommand,
  selectRowCommand,
  setAlignCommand,
} from "@milkdown/kit/preset/gfm";
import type { Editor } from "@milkdown/kit/core";

/** Which line a handle addresses. */
export const TableAxis = { row: "row", column: "column" } as const;
export type TableAxisValue = (typeof TableAxis)[keyof typeof TableAxis];

export type CellAlignment = "left" | "center" | "right";

/**
 * The table operations, as the node view needs them (RADD-750).
 *
 * A thin object rather than the commands directly, for one reason: every one of
 * them acts on the CURRENT cell selection, so a handle has to select its line
 * before it can do anything to it. Keeping the two next to each other means a
 * new menu entry cannot forget the selection step — which would silently apply
 * the operation to wherever the cursor happened to be.
 */
export interface TableCommandRunner {
  select: (axis: TableAxisValue, index: number, pos: number | undefined) => void;
  insert: (axis: TableAxisValue, where: "before" | "after") => void;
  remove: () => void;
  align: (alignment: CellAlignment) => void;
}

export function tableCommands(editor: () => Editor | null): TableCommandRunner {
  const run = (command: Parameters<typeof callCommand>[0], payload?: unknown) =>
    editor()?.action(callCommand(command, payload));

  return {
    select: (axis, index, pos) =>
      run(
        axis === TableAxis.column ? selectColCommand.key : selectRowCommand.key,
        // INSIDE the table, not AT it. Milkdown resolves the table with
        // `findParentNodeClosestToPos`, which walks a position's ANCESTORS — at
        // the node's own position the table is a sibling, not an ancestor, so the
        // selection silently does nothing and the operation lands wherever the
        // cursor happened to be. That is the failure this whole object exists to
        // prevent, and it still needed the +1.
        { index, pos: pos === undefined ? undefined : pos + 1 },
      ),
    insert: (axis, where) =>
      run(
        axis === TableAxis.column
          ? where === "before"
            ? addColBeforeCommand.key
            : addColAfterCommand.key
          : where === "before"
            ? addRowBeforeCommand.key
            : addRowAfterCommand.key,
      ),
    remove: () => run(deleteSelectedCellsCommand.key),
    align: (alignment) => run(setAlignCommand.key, alignment),
  };
}
