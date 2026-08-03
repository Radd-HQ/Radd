import { $prose } from "@milkdown/kit/utils";
import { Plugin } from "@milkdown/kit/prose/state";
import type { EditorState } from "@milkdown/kit/prose/state";

/**
 * What the toolbar needs to know about the selection (RADD-749).
 *
 * A compact SNAPSHOT rather than the editor state itself, and that is the whole
 * design. Putting `EditorState` into React state re-renders the chrome on every
 * keystroke; putting a small derived object there and only publishing it when it
 * CHANGES means the toolbar re-renders when the answer changes — typing inside a
 * paragraph produces one snapshot for the whole paragraph.
 */
export interface ToolbarSnapshot {
  /** Active inline marks, by schema name. */
  marks: string[];
  /** The block the cursor is in: `paragraph`, `heading`, `code_block`, … */
  block: string;
  /** Heading level when `block === "heading"`, else 0. */
  level: number;
  /** Enclosing list type, if any. */
  list: "bullet_list" | "ordered_list" | "";
  inBlockquote: boolean;
  inTable: boolean;
  /** No selected range — the AI and link affordances care. */
  empty: boolean;
}

export const EMPTY_SNAPSHOT: ToolbarSnapshot = {
  marks: [],
  block: "paragraph",
  level: 0,
  list: "",
  inBlockquote: false,
  inTable: false,
  empty: true,
};

/**
 * Marks at the cursor — `storedMarks` first.
 *
 * That order matters and is easy to get wrong: after pressing bold with no
 * selection, the mark is STORED for the next input and is not yet on any node.
 * Reading only `$from.marks()` makes the button flick off the instant you press
 * it, which reads as the toggle not working.
 */
function activeMarks(state: EditorState): string[] {
  const { from, $from, to, empty } = state.selection;
  if (empty) {
    return (state.storedMarks ?? $from.marks()).map((mark) => mark.type.name);
  }
  return Object.values(state.schema.marks)
    .filter((type) => state.doc.rangeHasMark(from, to, type))
    .map((type) => type.name);
}

export function snapshotOf(state: EditorState): ToolbarSnapshot {
  const { $from, empty } = state.selection;
  let block = $from.parent.type.name;
  let level = Number($from.parent.attrs.level ?? 0);
  let list: ToolbarSnapshot["list"] = "";
  let inBlockquote = false;
  let inTable = false;
  for (let depth = $from.depth; depth > 0; depth--) {
    const name = $from.node(depth).type.name;
    if (name === "bullet_list" || name === "ordered_list") list ||= name;
    if (name === "blockquote") inBlockquote = true;
    if (name === "table") inTable = true;
  }
  // A list ITEM's paragraph is still a paragraph; report the list separately so
  // the heading picker does not claim the cursor is "just a paragraph" when the
  // list buttons are the ones lit.
  if (block === "text") block = "paragraph";
  if ($from.parent.type.name !== "heading") level = 0;
  return { marks: activeMarks(state), block, level, list, inBlockquote, inTable, empty };
}

const same = (a: ToolbarSnapshot, b: ToolbarSnapshot) =>
  a.block === b.block &&
  a.level === b.level &&
  a.list === b.list &&
  a.inBlockquote === b.inBlockquote &&
  a.inTable === b.inTable &&
  a.empty === b.empty &&
  a.marks.length === b.marks.length &&
  a.marks.every((mark) => b.marks.includes(mark));

/**
 * Publish a snapshot whenever it changes.
 *
 * A plugin `view` rather than a `dispatchTransaction` wrapper: Milkdown owns the
 * dispatch, and a wrapper would have to be the only one.
 */
export const toolbarStatePlugin = (onChange: (snapshot: ToolbarSnapshot) => void) =>
  $prose(
    () =>
      new Plugin({
        view: (view) => {
          let last = snapshotOf(view.state);
          onChange(last);
          return {
            update(updated) {
              const next = snapshotOf(updated.state);
              if (same(last, next)) return;
              last = next;
              onChange(next);
            },
          };
        },
      }),
  );
