/** Generic controlled CodeMirror input; plugins choose language, label and behavior. */
import { useEffect, useRef } from "react";
import { Annotation, EditorState, Compartment, Transaction } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { syntaxHighlighting, indentUnit } from "@codemirror/language";
import type { CodeEditorProps } from "@radd/plugin-sdk";
import { codeHighlight } from "../lib/code-highlight";
import { describeLanguage } from "../lib/code-languages";

const externalChange = Annotation.define<boolean>();

export function CodeEditor({ value, onChange, language = "", minHeight = 160, ariaLabel = "Code", readOnly = false }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onEdit = useRef(onChange);
  const grammar = useRef(new Compartment());
  const access = useRef(new Compartment());
  const attributes = useRef(new Compartment());
  useEffect(() => { onEdit.current = onChange; }, [onChange]);

  useEffect(() => {
    if (!host.current) return;
    const created = new EditorView({
      parent: host.current,
      state: EditorState.create({ doc: value, extensions: [
        lineNumbers(), highlightActiveLine(), drawSelection(), history(),
        indentUnit.of("    "), keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        syntaxHighlighting(codeHighlight),
        grammar.current.of([]), access.current.of([]), attributes.current.of([]),
        EditorView.theme({
          "&": { minHeight: "inherit", fontSize: "13px" },
          ".cm-scroller": { fontFamily: "var(--font-mono, ui-monospace, monospace)" },
          ".cm-content": { padding: "8px 0" },
          ".cm-gutters": { backgroundColor: "var(--color-surface)", borderColor: "var(--color-subtle)", color: "var(--code-gutter)" },
          ".cm-activeLine": { backgroundColor: "var(--color-elevated)" },
          ".cm-cursor": { borderLeftColor: "var(--color-fg)" },
          "&.cm-focused": { outline: "none" },
        }),
        EditorView.updateListener.of(update => {
          if (update.docChanged && !update.transactions.every(tr => tr.annotation(externalChange))) {
            onEdit.current(update.state.doc.toString());
          }
        }),
      ] }),
    });
    view.current = created;
    return () => { created.destroy(); view.current = null; };
    // Only the view's lifetime is tied to mount. Controlled props update compartments below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const current = view.current;
    if (!current || current.state.doc.toString() === value) return;
    current.dispatch({
      changes: { from: 0, to: current.state.doc.length, insert: value },
      annotations: [externalChange.of(true), Transaction.addToHistory.of(false)],
    });
  }, [value]);

  useEffect(() => {
    const current = view.current;
    if (!current) return;
    let active = true;
    current.dispatch({ effects: grammar.current.reconfigure([]) });
    void describeLanguage(language)?.load().then(support => {
      if (active && view.current === current) current.dispatch({ effects: grammar.current.reconfigure(support) });
    }).catch(() => { /* Keep editable plain text if a grammar cannot load. */ });
    return () => { active = false; };
  }, [language]);

  useEffect(() => {
    view.current?.dispatch({ effects: access.current.reconfigure([
      EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly),
    ]) });
  }, [readOnly]);
  useEffect(() => {
    view.current?.dispatch({ effects: attributes.current.reconfigure(
      EditorView.contentAttributes.of({ "aria-label": ariaLabel, "aria-multiline": "true" }),
    ) });
  }, [ariaLabel]);

  return <div ref={host} data-code-editor data-language={language} style={{ minHeight }}
    className="rounded-[8px] border border-subtle bg-base text-fg" />;
}
