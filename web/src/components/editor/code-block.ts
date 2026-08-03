import { EditorState as CmState, Compartment } from "@codemirror/state";
import {
  EditorView as CmView,
  keymap,
  lineNumbers,
  highlightActiveLine,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import {
  HighlightStyle,
  LanguageDescription,
  StreamLanguage,
  syntaxHighlighting,
} from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import { tags } from "@lezer/highlight";
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

/** Theme-following highlight. The app's palette, not one-dark's opinion. */
const HIGHLIGHT = HighlightStyle.define([
  { tag: [tags.keyword, tags.modifier, tags.controlKeyword], color: "var(--code-keyword)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--code-string)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--code-comment)", fontStyle: "italic" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--code-number)" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--code-function)" },
  { tag: [tags.typeName, tags.className, tags.namespace], color: "var(--code-type)" },
  { tag: [tags.propertyName, tags.attributeName], color: "var(--code-property)" },
  { tag: [tags.operator, tags.punctuation, tags.bracket], color: "var(--code-punct)" },
  { tag: [tags.invalid], color: "var(--code-invalid)" },
]);

/** Layout only — colours come from the stylesheet so both themes follow. */
const BASE_THEME = CmView.theme({
  "&": { fontSize: "12.5px", backgroundColor: "transparent" },
  ".cm-content": { fontFamily: "var(--radd-code-font)", padding: "8px 0" },
  ".cm-gutters": { backgroundColor: "transparent", border: "none", color: "var(--code-gutter)" },
  ".cm-activeLine": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "var(--radd-code-font)", lineHeight: "1.55" },
});

/**
 * Languages CodeMirror can load, keyed by the token a FENCE should carry.
 *
 * Not `alias[0]`, which is what this did first and got wrong in a way that only
 * shows up outside Radd: JavaScript's alias list begins `ecmascript`, so picking
 * "JavaScript" wrote ```` ```ecmascript ````. Valid, resolvable here, and a
 * fence nobody writes — GitHub and every other renderer of this markdown would
 * fail to highlight it. The lowercased NAME is what people type, so it wins
 * whenever it is a single token; a multi-word name ("Web IDL") falls back to the
 * first whitespace-free alias, since a fence's info string ends at the space.
 */
export function languageOptions(): { value: string; label: string }[] {
  const seen = new Set<string>();
  const out: { value: string; label: string }[] = [];
  for (const description of languages) {
    const value = fenceTokenFor(description);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label: description.name });
  }
  return out.sort((a, b) => a.label.localeCompare(b.label));
}

function fenceTokenFor(description: LanguageDescription): string {
  const name = description.name.toLowerCase();
  if (!/\s/.test(name)) return name;
  return description.alias.find((alias) => !/\s/.test(alias)) ?? "";
}

/** The `LanguageDescription` a fence's info string names, if any. */
export const describeLanguage = (name: string): LanguageDescription | null =>
  name ? LanguageDescription.matchLanguageName(languages, name, true) : null;

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
        syntaxHighlighting(HIGHLIGHT),
        BASE_THEME,
        keymap.of([...escapeKeymap(), ...defaultKeymap, ...historyKeymap, indentWithTab]),
        language.of([]),
        editable.of([
          CmView.editable.of(options.editable),
          CmState.readOnly.of(!options.editable),
        ]),
        CmView.updateListener.of((update) => {
          if (updating || !update.docChanged) return;
          pushToProseMirror(update.state.doc.toString());
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
   *  the top on every outside change (an undo, a collaborative edit), which is
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
    destroy: () => view.destroy(),
  };
}

/** Is the ProseMirror selection inside this node? Drives focus hand-off. */
export function selectionInsideNode(pmView: PmView, pos: number | undefined): boolean {
  if (pos === undefined) return false;
  const node = pmView.state.doc.nodeAt(pos);
  if (!node) return false;
  const { from } = pmView.state.selection;
  return from > pos && from < pos + node.nodeSize;
}

export { StreamLanguage };
