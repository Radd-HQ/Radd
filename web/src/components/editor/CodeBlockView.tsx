import { useEffect, useMemo, useRef, useState } from "react";
import { useNodeViewContext } from "@prosemirror-adapter/react";
import { Check, Copy } from "lucide-react";
import { Select } from "../Select";
import {
  describeLanguage,
  languageOptions,
  mountCodeMirror,
  type CodeMirrorHost,
} from "./code-block";

/**
 * The code block, ours (RADD-752).
 *
 * Chrome — the language picker and copy — in React, the text in CodeMirror,
 * and the same component in read mode with editing off. That last part is the
 * property `RichViewer` exists to preserve: code has to look identical in both,
 * and it will not if the two are different components that happen to agree
 * today.
 */
export function CodeBlockView() {
  const { node, view, getPos, setAttrs, contentRef } = useNodeViewContext();
  const hostRef = useRef<HTMLDivElement>(null);
  const cmRef = useRef<CodeMirrorHost | null>(null);
  const [copied, setCopied] = useState(false);
  const language = String(node.attrs.language ?? "");
  /**
   * The picker must be able to REPRESENT the value it has.
   *
   * The option list is keyed by canonical fence tokens ("python"), but a body can
   * carry any token a person or an importer wrote — Confluence writes `py`. A
   * `<Select>` whose value matches no option shows nothing selected, which reads
   * as "I cannot choose a language here" even though the control works. So an
   * unlisted-but-RESOLVABLE token joins the list under its real language name,
   * and an unresolvable one still appears as itself rather than vanishing.
   */
  const options = useMemo(() => {
    const base = [{ value: "", label: "Plain text" }, ...languageOptions()];
    if (language && !base.some((option) => option.value === language)) {
      const resolved = describeLanguage(language);
      base.splice(1, 0, {
        value: language,
        label: resolved ? `${resolved.name} (${language})` : language,
      });
    }
    return base;
  }, [language]);
  const editable = view.editable;

  // Create once. The instance outlives every re-render — rebuilding it on each
  // one would lose the cursor and the undo history on every keystroke.
  useEffect(() => {
    const parent = hostRef.current;
    if (!parent) return;
    const pos = getPos();
    if (pos === undefined) return;
    const host = mountCodeMirror({
      parent,
      node,
      outerView: view,
      getPos,
      editable,
    });
    cmRef.current = host;
    return () => {
      host.destroy();
      cmRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Text arriving from outside (undo, an AI diff accept, a reseed).
  useEffect(() => {
    cmRef.current?.syncFromNode(node);
  }, [node]);

  useEffect(() => {
    cmRef.current?.setLanguage(language);
  }, [language]);

  useEffect(() => {
    cmRef.current?.setEditable(editable);
  }, [editable]);

  const copy = async () => {
    const text = cmRef.current?.view.state.doc.toString() ?? node.textContent;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // A denied clipboard permission is not an error worth a toast — the code
      // is on screen and selectable.
    }
  };

  return (
    <div
      className="radd-code-block group relative my-2 overflow-hidden rounded-lg border border-subtle bg-base"
      data-code-block
      data-language={language}
    >
      <div className="flex items-center justify-between gap-2 border-b border-subtle px-2 py-1">
        {editable ? (
          <Select
            size="sm"
            aria-label="Code language"
            className="w-40"
            value={language}
            onChange={(next) => setAttrs({ language: next })}
            options={options}
          />
        ) : (
          <span className="px-1 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
            {options.find((option) => option.value === language)?.label ?? language ?? "Plain text"}
          </span>
        )}
        <button
          type="button"
          onClick={copy}
          title="Copy code"
          aria-label="Copy code"
          className="radd-code-copy inline-flex h-6 items-center gap-1 rounded px-1.5 text-[11px] text-fg-muted transition-colors hover:text-heading focus-visible:outline-2 focus-visible:outline-focus cursor-pointer"
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {/* CodeMirror mounts here. */}
      <div ref={hostRef} />
      {/* ProseMirror needs somewhere to put the node's content, and it must not
          be where CodeMirror lives — the two would fight over the same DOM. It
          is hidden, not absent: without it ProseMirror treats the node as a leaf
          and the text stops round-tripping. */}
      <div ref={contentRef} className="hidden" />
    </div>
  );
}
