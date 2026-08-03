import { $prose } from "@milkdown/kit/utils";
import { Plugin } from "@milkdown/kit/prose/state";

/**
 * Where the selection is on screen, for chrome that floats over it (RADD-753).
 *
 * Reported from a plugin view rather than from a React `selectionchange`
 * listener, because ProseMirror's selection is the one that matters — a cell
 * selection in a table, or a node selection on an image, has no DOM range at
 * all — and because the view already runs on exactly the updates that can move
 * it.
 */
export interface SelectionRect {
  /** Screen coordinates of the selection's midpoint and top edge. */
  left: number;
  top: number;
  bottom: number;
  /** The ProseMirror range. Carried so chrome can CAPTURE it rather than read
   *  the live selection later: opening a prompt input necessarily moves focus
   *  out of the editor, which collapses the very range the run applies to. */
  from: number;
  to: number;
  /** Nothing selected: the floating surface should not appear. */
  empty: boolean;
  /** The editor has focus. A stale toolbar over an unfocused editor is noise. */
  focused: boolean;
}

export const NO_SELECTION: SelectionRect = {
  left: 0,
  top: 0,
  bottom: 0,
  from: 0,
  to: 0,
  empty: true,
  focused: false,
};

const near = (a: number, b: number) => Math.abs(a - b) < 1;

const same = (a: SelectionRect, b: SelectionRect) =>
  a.empty === b.empty &&
  a.from === b.from &&
  a.to === b.to &&
  a.focused === b.focused &&
  near(a.left, b.left) &&
  near(a.top, b.top) &&
  near(a.bottom, b.bottom);

export const selectionRectPlugin = (onChange: (rect: SelectionRect) => void) =>
  $prose(
    () =>
      new Plugin({
        view: (view) => {
          let last = NO_SELECTION;
          const publish = () => {
            const { state } = view;
            const { from, to, empty } = state.selection;
            let next: SelectionRect = {
              ...NO_SELECTION,
              from,
              to,
              focused: view.hasFocus(),
            };
            if (!empty) {
              try {
                const start = view.coordsAtPos(from);
                const end = view.coordsAtPos(to);
                next = {
                  left: (start.left + end.right) / 2,
                  top: Math.min(start.top, end.top),
                  bottom: Math.max(start.bottom, end.bottom),
                  from,
                  to,
                  empty: false,
                  focused: view.hasFocus(),
                };
              } catch {
                // A position with no coordinates yet (mid-render) is not an
                // error — the next update will have them.
              }
            }
            if (same(last, next)) return;
            last = next;
            onChange(next);
          };
          publish();
          // Focus changes move nothing in the document, so `update` never fires
          // for them — the toolbar would linger over an editor nobody is in.
          view.dom.addEventListener("focus", publish, true);
          view.dom.addEventListener("blur", publish, true);
          return {
            update: publish,
            destroy: () => {
              view.dom.removeEventListener("focus", publish, true);
              view.dom.removeEventListener("blur", publish, true);
            },
          };
        },
      }),
  );
