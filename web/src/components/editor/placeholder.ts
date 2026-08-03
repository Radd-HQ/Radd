import { $prose } from "@milkdown/kit/utils";
import { Plugin } from "@milkdown/kit/prose/state";
import { Decoration, DecorationSet } from "@milkdown/kit/prose/view";

/**
 * Per-surface placeholder text (RADD-754).
 *
 * The smallest of the pieces Crepe supplied, and the one least worth a
 * dependency: a widget decoration on the first block when the document is
 * empty, with the text on a `::before` so it can never be selected, copied, or
 * counted by anything reading `textContent` — which a real element would be.
 *
 * "Empty" means ONE empty textblock, not `doc.textContent === ""`. A document
 * holding an image and nothing else is not empty, and neither is one whose only
 * paragraph sits below a heading someone already typed.
 */
export const placeholderPlugin = (text: string) =>
  $prose(
    () =>
      new Plugin({
        props: {
          decorations(state) {
            const { doc } = state;
            const empty =
              doc.childCount === 1 &&
              doc.firstChild?.isTextblock === true &&
              doc.firstChild.content.size === 0;
            if (!empty || !text) return null;
            return DecorationSet.create(doc, [
              Decoration.node(0, doc.firstChild!.nodeSize, {
                class: "radd-placeholder",
                "data-placeholder": text,
              }),
            ]);
          },
        },
      }),
  );
