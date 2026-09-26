import { EditorState as CmState, Compartment } from "@codemirror/state";
import { registerTextProjection } from "@radd/plugin-sdk";
import {
  EditorView as CmView,
  keymap,
  lineNumbers,
  highlightActiveLine,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import {
  syntaxHighlighting,
} from "@codemirror/language";
import { describeLanguage } from "../../lib/code-languages";
export { describeLanguage, languageOptions } from "../../lib/code-languages";
import { codeHighlight } from "../../lib/code-highlight";
import { exitCode } from "@milkdown/kit/prose/commands";
import { Selection, TextSelection } from "@milkdown/kit/prose/state";
import type { Node as ProseNode } from "@milkdown/kit/prose/model";
import type { EditorView as PmView } from "@milkdown/kit/prose/view";

/**
 * A CodeMirror 6 instance living inside a ProseMirror `code_block` (RADD-752).
 *
 * The two editors each believe they own their text, so the whole job is keeping
 * them agreeing without either one's echo starting a loop. The shape is the one
 * from ProseMirror's own guide, with the parts that matter written out rather
 * than inherited:
 *
 *  - CodeMirror → ProseMirror on every user edit, as a single replacement of the
 *    block's text;
 *  - ProseMirror → CodeMirror only for the part that actually differs, so an
 *    undo from outside does not reset the cursor to the top of the block;
 *  - `updating` guards the seam, because each direction's write triggers the
 *    other's listener.
 *
 * Owning this also owns its TIMING, which is the reason it is on this epic's
 * list at all: a code block is a `<pre>` only until the mode finishes loading,
 * after which it is a `.cm-editor` with no `<pre>`. An assertion that read the
 * page before the swap passed and the same one failed after.
 */

/** Layout only — colours come from the stylesheet so both themes follow. */
const BASE_THEME = CmView.theme({
  "&": { fontSize: "12.5px", backgroundColor: "transparent" },
  ".cm-content": { fontFamily: "var(--radd-code-font)", padding: "8px 0" },
  ".cm-gutters": { backgroundColor: "transparent", border: "none", color: "var(--code-gutter)" },
  ".cm-activeLine": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "var(--radd-code-font)", lineHeight: "1.55" },
});

export interface CodeMirrorHost {
  view: CmView;
  /** Push the node's text in, if it differs. Returns true when it changed. */
  syncFromNode: (node: ProseNode) => boolean;
  setLanguage: (name: string) => void;
  setEditable: (editable: boolean) => void;
  destroy: () => void;
}

/**
 * Build the inner editor.
 *
 * `getPos` and the outer view are taken as functions rather than values because
 * a node view outlives any single position: the block moves whenever anything
 * above it changes.
 */
export function mountCodeMirror(options: {
  parent: HTMLElement;
  node: ProseNode;
  outerView: PmView;
  getPos: () => number | undefined;
  editable: boolean;
  /** Live text on every keystroke — what a mermaid preview follows. */
  onText?: (text: string) => void;
}): CodeMirrorHost {
  const { parent, node, outerView, getPos } = options;
  const language = new Compartment();
  const editable = new Compartment();
  let updating = false;

  const view = new CmView({
    parent,
    state: CmState.create({
      doc: node.textContent,
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        history(),
        syntaxHighlighting(codeHighlight),
        BASE_THEME,
        keymap.of([...escapeKeymap(), ...defaultKeymap, ...historyKeymap, indentWithTab]),
        language.of([]),
        editable.of([
          CmView.editable.of(options.editable),
          CmState.readOnly.of(!options.editable),
        ]),
        CmView.updateListener.of((update) => {
          if (updating || !update.docChanged) return;
          const text = update.state.doc.toString();
          // Told BEFORE the ProseMirror round trip: a preview that waits for the
          // document to come back is always one keystroke behind.
          options.onText?.(text);
          pushToProseMirror(text);
        }),
      ],
    }),
  });

  /** CodeMirror → ProseMirror, as one replacement of the block's text. */
  function pushToProseMirror(text: string) {
    const pos = getPos();
    if (pos === undefined) return;
    const start = pos + 1;
    const end = start + outerView.state.doc.nodeAt(pos)!.content.size;
    const tr = outerView.state.tr.replaceWith(
      start,
      end,
      text ? outerView.state.schema.text(text) : [],
    );
    outerView.dispatch(tr);
  }

  /** ProseMirror → CodeMirror, replacing only the differing RANGE.
   *
   *  Replacing the whole document would work and would also move the cursor to
   *  the top on every outside change (an undo, an edit a binding applied), which is
   *  why the common prefix and suffix are found first. */
  function syncFromNode(next: ProseNode) {
    const incoming = next.textContent;
    const current = view.state.doc.toString();
    if (incoming === current) return false;
    let start = 0;
    let endA = current.length;
    let endB = incoming.length;
    while (start < endA && start < endB && current[start] === incoming[start]) start++;
    while (endA > start && endB > start && current[endA - 1] === incoming[endB - 1]) {
      endA--;
      endB--;
    }
    updating = true;
    view.dispatch({
      changes: { from: start, to: endA, insert: incoming.slice(start, endB) },
    });
    updating = false;
    return true;
  }

  /**
   * Keys that must leave the block, because CodeMirror would otherwise swallow
   * them and the block becomes a place the cursor cannot get out of.
   */
  function escapeKeymap() {
    const toProseMirror = (dir: -1 | 1) => () => {
      const pos = getPos();
      if (pos === undefined) return false;
      const target = dir < 0 ? pos : pos + outerView.state.doc.nodeAt(pos)!.nodeSize;
      const selection = Selection.near(outerView.state.doc.resolve(target), dir);
      outerView.dispatch(outerView.state.tr.setSelection(selection).scrollIntoView());
      outerView.focus();
      return true;
    };
    return [
      {
        key: "ArrowUp",
        run: (cm: CmView) => (atFirstLine(cm) ? toProseMirror(-1)() : false),
      },
      {
        key: "ArrowDown",
        run: (cm: CmView) => (atLastLine(cm) ? toProseMirror(1)() : false),
      },
      { key: "Mod-Enter", run: () => exitCode(outerView.state, outerView.dispatch) },
      { key: "Escape", run: toProseMirror(1) },
      {
        // Backspace in an EMPTY block removes it, rather than trapping the
        // cursor in a block with nothing to delete.
        key: "Backspace",
        run: (cm: CmView) => {
          if (cm.state.doc.length > 0) return false;
          const pos = getPos();
          if (pos === undefined) return false;
          const node = outerView.state.doc.nodeAt(pos);
          if (!node) return false;
          const tr = outerView.state.tr.delete(pos, pos + node.nodeSize);
          tr.setSelection(TextSelection.near(tr.doc.resolve(Math.max(0, pos - 1)), -1));
          outerView.dispatch(tr);
          outerView.focus();
          return true;
        },
      },
    ];
  }

  const atFirstLine = (cm: CmView) => cm.state.doc.lineAt(cm.state.selection.main.head).number === 1;
  const atLastLine = (cm: CmView) =>
    cm.state.doc.lineAt(cm.state.selection.main.head).number === cm.state.doc.lines;

  async function setLanguage(name: string) {
    const description = describeLanguage(name);
    if (!description) {
      view.dispatch({ effects: language.reconfigure([]) });
      return;
    }
    // Loading is ASYNC — `language-data` imports the mode on demand, which is
    // what keeps 30 languages out of the main bundle. It is also exactly the
    // moment when a `<pre>` becomes a `.cm-editor`.
    const support = description.support ?? (await description.load());
    view.dispatch({ effects: language.reconfigure([support]) });
  }

  const source = parent.closest("[data-code-block]")?.querySelector("[data-code-source]");
  const unregisterProjection = source ? registerTextProjection(source, {
    pointAt: (offset) => view.visibleRanges.some(range => offset >= range.from && offset <= range.to)
      ? view.domAtPos(offset) : null,
    offsetAt: (node, offset) => view.contentDOM.contains(node) ? view.posAtDOM(node, offset) : null,
    reveal: (offset) => view.dispatch({effects: CmView.scrollIntoView(offset, {y: "center"})}),
  }) : undefined;

  return {
    view,
    syncFromNode,
    setLanguage: (name: string) => void setLanguage(name),
    setEditable: (next: boolean) =>
      view.dispatch({
        effects: editable.reconfigure([
          CmView.editable.of(next),
          CmState.readOnly.of(!next),
        ]),
      }),
    destroy: () => { unregisterProjection?.(); view.destroy(); },
  };
}
