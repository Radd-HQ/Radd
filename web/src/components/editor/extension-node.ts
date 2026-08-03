import { $nodeSchema, $prose, $remark } from "@milkdown/kit/utils";
import { Plugin, PluginKey } from "@milkdown/kit/prose/state";
import { Decoration, DecorationSet } from "@milkdown/kit/prose/view";
import { visit } from "unist-util-visit";
import type { Node as UnistNode, Parent } from "unist";
import { extensionNameOfInfo } from "../../lib/page-extensions";

/**
 * `radd:*` fences as a real editor node (RADD-746).
 *
 * **The correction worth recording.** Overriding the editor's `code_block` node
 * view to catch these does collide — ProseMirror's `someProp` resolves node
 * views by FIRST match, and the preset registers first — but the right move is
 * **not to be a code block at all**. A `$remark` transform claims the fence
 * during markdown PARSING and hands back a distinct mdast type, so the
 * code-block view never sees it and no registration race decides the outcome.
 *
 * The race is real, not theoretical: the transformer resolves an mdast node to
 * a schema type with `Object.values(schema.nodes).find(spec.parseMarkdown.match)`
 * — insertion order. A second node also matching `type === "code"` would win or
 * lose depending on which plugin was `use()`d first. Matching a type nobody else
 * emits removes the question.
 *
 * **The wire format does not change.** The serializer writes the fence back
 * from the verbatim body it parsed, so a block nobody edited round-trips
 * byte-identically and FTS, the embedder, the export and the public surface
 * (RADD-709) keep reading the markdown they always did.
 */

/** The mdast node type this transform emits. Deliberately not `code`. */
const MDAST_TYPE = "raddExtension";

/** The ProseMirror node name. */
export const RADD_EXTENSION_NODE = "radd_extension";

interface RaddExtensionMdast extends UnistNode {
  type: typeof MDAST_TYPE;
  name: string;
  body: string;
}

/**
 * Parse-time claim: a ```` ```radd:<name> ```` fence stops being a `code` node
 * before the schema ever sees it.
 *
 * Only the fence's own `lang` is inspected, so a `radd:toc` written INSIDE a
 * ```` ```markdown ```` example is still the code it is — remark has already
 * decided what is a fence and what is fence-shaped prose, which is exactly why
 * this runs on the mdast tree rather than over the source text.
 */
export const raddExtensionRemark = $remark(
  "raddExtension",
  () => () => (tree: UnistNode) => {
    visit(tree, "code", (node, index, parent: Parent | undefined) => {
      if (!parent || index === null || index === undefined) return;
      const code = node as UnistNode & { lang?: string | null; value?: string };
      const name = extensionNameOfInfo(code.lang ?? "");
      if (!name) return;
      const replacement: RaddExtensionMdast = {
        type: MDAST_TYPE,
        name,
        body: code.value ?? "",
      };
      parent.children[index] = replacement as never;
    });
  },
);

/**
 * The node itself: an ATOM, because the block's content is a rendered
 * extension, not text a cursor belongs inside. `body` holds the fence's
 * payload verbatim — it is what gets written back, and keeping the source
 * rather than a re-stringified parse is what makes an untouched block
 * byte-identical on save.
 */
export const raddExtensionSchema = $nodeSchema(RADD_EXTENSION_NODE, () => ({
  group: "block",
  atom: true,
  isolating: true,
  selectable: true,
  draggable: true,
  attrs: {
    name: { default: "", validate: "string" },
    body: { default: "", validate: "string" },
  },
  parseDOM: [
    {
      tag: "div[data-radd-extension]",
      getAttrs: (dom) => {
        if (!(dom instanceof HTMLElement)) return false;
        return {
          name: dom.dataset.raddExtension ?? "",
          body: dom.dataset.raddExtensionBody ?? "",
        };
      },
    },
  ],
  // The no-node-view fallback, and what a copy to another app pastes as: a
  // labelled code block, the same honest degradation the fence itself has.
  toDOM: (node) => [
    "div",
    {
      "data-radd-extension": node.attrs.name,
      "data-radd-extension-body": node.attrs.body,
    },
    ["pre", {}, ["code", {}, `radd:${node.attrs.name}\n${node.attrs.body}`]],
  ],
  parseMarkdown: {
    match: ({ type }) => type === MDAST_TYPE,
    runner: (state, node, type) => {
      const extension = node as unknown as RaddExtensionMdast;
      state.addNode(type, { name: extension.name, body: extension.body });
    },
  },
  toMarkdown: {
    match: (node) => node.type.name === RADD_EXTENSION_NODE,
    runner: (state, node) => {
      state.addNode("code", undefined, node.attrs.body, {
        lang: `radd:${node.attrs.name}`,
      });
    },
  },
}));

/** Carries "configure the block at this position" from the insert menu to the
 *  node view that will render it (RADD-747). */
export const configOnInsertKey = new PluginKey<number | null>("raddExtensionConfigOnInsert");

/** Spec flag on the decoration a waiting block carries. */
export const CONFIG_ON_INSERT = "raddConfigOnInsert";

/**
 * Open the config form on a block that was just inserted (RADD-747).
 *
 * A DECORATION rather than a callback or a shared variable, because the node
 * view is created by ProseMirror and rendered through a portal: it has no
 * constructor the menu could reach, and a module-level flag would address the
 * wrong editor as soon as two are mounted. A decoration is already the channel
 * ProseMirror gives a plugin for saying something about ONE node, and it
 * survives the position moving under concurrent edits because the state is
 * mapped through every transaction.
 */
export const raddExtensionConfigOnInsert = $prose(
  () =>
    new Plugin<number | null>({
      key: configOnInsertKey,
      state: {
        init: () => null,
        apply(tr, value) {
          const requested = tr.getMeta(configOnInsertKey);
          if (requested !== undefined) return requested as number | null;
          if (value === null) return null;
          return tr.docChanged ? tr.mapping.map(value) : value;
        },
      },
      props: {
        decorations(state) {
          const pos = configOnInsertKey.getState(state);
          if (pos === null || pos === undefined) return null;
          const node = state.doc.nodeAt(pos);
          if (!node || node.type.name !== RADD_EXTENSION_NODE) return null;
          return DecorationSet.create(state.doc, [
            Decoration.node(pos, pos + node.nodeSize, {}, { [CONFIG_ON_INSERT]: true }),
          ]);
        },
      },
    }),
);
