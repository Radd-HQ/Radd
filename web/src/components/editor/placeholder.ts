import { $prose } from "@milkdown/kit/utils";
import { Plugin } from "@milkdown/kit/prose/state";
import { Decoration, DecorationSet } from "@milkdown/kit/prose/view";

/**
 * Per-surface placeholder: a node decoration while the document is ONE empty textblock (an image-only
 * doc, or a paragraph under a typed heading, is not empty), with the text on a `::before` so it is never
 * selected, copied or counted in `textContent`.
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
