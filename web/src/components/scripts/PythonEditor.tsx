/**
 * A Python editor for the script library (RADD-1269): CodeMirror 6, wired
 * directly the way the wiki's code block is (RADD-745), reusing its language
 * registry so the grammar is the same one the editor already ships.
 *
 * Deliberately a plain controlled component: `value` in, `onChange` out. The
 * view is created once and re-seeded only when `value` changes from OUTSIDE
 * (a version restored, a script switched), never on its own keystrokes — a
 * `setState` per keystroke that rebuilt the document would lose the cursor.
 */
import { useEffect, useRef } from "react";
import { EditorState, Compartment } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle, indentUnit } from "@codemirror/language";
import { describeLanguage } from "../editor/code-block";

interface PythonEditorProps {
  value: string;
  onChange: (next: string) => void;
  /** Minimum height in px; the editor grows with its content. */
  minHeight?: number;
  ariaLabel?: string;
}

export function PythonEditor({ value, onChange, minHeight = 320, ariaLabel = "Script body" }: PythonEditorProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  const latest = useRef(value);
  const language = useRef(new Compartment());

  useEffect(() => {
    if (!host.current) return;
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        drawSelection(),
        history(),
        indentUnit.of("    "),
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        language.current.of([]),
        EditorView.theme({
          "&": { minHeight: `${minHeight}px`, fontSize: "13px" },
          ".cm-scroller": { fontFamily: "var(--font-mono, ui-monospace, monospace)" },
          ".cm-content": { padding: "8px 0" },
        }),
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return;
          const text = update.state.doc.toString();
          latest.current = text;
          onChange(text);
        }),
      ],
    });
    const created = new EditorView({ state, parent: host.current });
    view.current = created;
    // The Python grammar loads lazily from the language registry; until it
    // arrives the editor is a plain text editor, which is fine.
    void describeLanguage("python")?.load().then((support) => {
      if (view.current === created) created.dispatch({ effects: language.current.reconfigure(support) });
    });
    return () => {
      created.destroy();
      view.current = null;
    };
    // Mounted once; external value changes are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const current = view.current;
    if (!current || value === latest.current) return;
    latest.current = value;
    current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: value } });
  }, [value]);

  return (
    <div
      ref={host}
      role="textbox"
      aria-label={ariaLabel}
      aria-multiline="true"
      data-python-editor
      className="rounded-[8px] border border-subtle bg-base text-fg [&_.cm-editor]:outline-none [&_.cm-gutters]:border-subtle [&_.cm-gutters]:bg-surface [&_.cm-gutters]:text-fg-faint [&_.cm-activeLine]:bg-elevated/60"
    />
  );
}
