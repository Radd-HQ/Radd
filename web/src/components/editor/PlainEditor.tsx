import { useEffect, useRef } from "react";
import {
  Bold,
  Code,
  Heading1,
  Heading2,
  Heading3,
  Image,
  Italic,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  Minus,
  SquareCode,
  Strikethrough,
  Table,
  TextQuote,
} from "lucide-react";
import { KEY_ACTIONS, SLASH_RE, TRIGGER_RE, type MentionQuery } from "./mention";

/** Imperative bridge back from the popup: splice text at the trigger range. */
export interface PlainEditorApi {
  /** Replace [from, to) with `text`, put the caret after it, and refocus. */
  replaceRange: (from: number, to: number, text: string) => void;
}

interface PlainEditorProps {
  value: string;
  onChange: (markdown: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  /** Same upload seam as the rich editor — enables the Image button + paste-to-upload. */
  onUploadImage?: (file: File) => Promise<string>;
  /** Trigger reporting (same `@`/`#`/`/` contract as the ProseMirror plugin; `from`/`to`
   * are character offsets into `value` instead of doc positions). */
  onQuery: (query: MentionQuery | null) => void;
  /** Popup nav routing — true = consumed (mirror of MentionStore.keydown). */
  onNavKey: (action: "up" | "down" | "enter" | "escape") => boolean;
  apiRef: React.MutableRefObject<PlainEditorApi | null>;
}

/** Caret → viewport coords via the mirror-div trick (textareas expose no ranges). */
function caretCoords(textarea: HTMLTextAreaElement, caret: number) {
  const mirror = document.createElement("div");
  const style = getComputedStyle(textarea);
  for (const prop of [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "lineHeight",
    "letterSpacing",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "borderTopWidth",
    "borderRightWidth",
    "borderBottomWidth",
    "borderLeftWidth",
    "boxSizing",
  ] as const) {
    mirror.style[prop] = style[prop];
  }
  mirror.style.position = "absolute";
  mirror.style.top = "-9999px";
  mirror.style.left = "0";
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.overflowWrap = "break-word";
  mirror.style.width = `${textarea.clientWidth}px`;
  mirror.textContent = textarea.value.slice(0, caret);
  const marker = document.createElement("span");
  marker.textContent = "​";
  mirror.appendChild(marker);
  document.body.appendChild(mirror);
  const rect = textarea.getBoundingClientRect();
  const coords = {
    left: rect.left + marker.offsetLeft - textarea.scrollLeft,
    bottom: rect.top + marker.offsetTop + marker.offsetHeight - textarea.scrollTop,
  };
  mirror.remove();
  return coords;
}

/**
 * Plain-markdown editing surface — the feature-parity twin of the rich (Crepe) mode:
 * same toolbar actions (as markdown syntax edits), same `@`/`#`/`/` popups, same
 * image paste/upload. Only the RENDERING is plain text.
 */
export function PlainEditor({
  value,
  onChange,
  placeholder,
  autoFocus,
  onUploadImage,
  onQuery,
  onNavKey,
  apiRef,
}: PlainEditorProps) {
  const taRef = useRef<HTMLTextAreaElement>(null);

  const apply = (next: string, selectStart: number, selectEnd = selectStart) => {
    onChange(next);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(selectStart, selectEnd);
    });
  };

  useEffect(() => {
    apiRef.current = {
      replaceRange: (from, to, text) => {
        const ta = taRef.current;
        if (!ta) return;
        apply(ta.value.slice(0, from) + text + ta.value.slice(to), from + text.length);
      },
    };
    return () => {
      apiRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Same trigger rules as the ProseMirror plugin, against the caret's line. */
  const detectTrigger = () => {
    const ta = taRef.current;
    if (!ta) return;
    if (ta.selectionStart !== ta.selectionEnd) return onQuery(null);
    const caret = ta.selectionStart;
    const lineStart = ta.value.lastIndexOf("\n", caret - 1) + 1;
    const line = ta.value.slice(lineStart, caret);
    const slash = SLASH_RE.exec(line);
    const match = slash ?? TRIGGER_RE.exec(line.slice(-60));
    if (!match) return onQuery(null);
    const type = slash ? "/" : (match[1] as "@" | "#");
    const query = slash ? match[1] : match[2];
    onQuery({
      type,
      query,
      from: caret - (query.length + 1),
      to: caret,
      coords: caretCoords(ta, caret),
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const action = KEY_ACTIONS[event.key];
    if (action && onNavKey(action)) event.preventDefault();
  };

  // --- toolbar operations (selection-aware markdown edits) ---

  const wrap = (before: string, after = before, placeholderText = "text") => {
    const ta = taRef.current;
    if (!ta) return;
    const { selectionStart: start, selectionEnd: end, value: text } = ta;
    const selected = text.slice(start, end) || placeholderText;
    const next = text.slice(0, start) + before + selected + after + text.slice(end);
    apply(next, start + before.length, start + before.length + selected.length);
  };

  /** Toggle a markdown prefix on every selected line ("- ", "1. ", "> ", "- [ ] "). */
  const prefixLines = (prefix: string) => {
    const ta = taRef.current;
    if (!ta) return;
    const { selectionStart: start, selectionEnd: end, value: text } = ta;
    const from = text.lastIndexOf("\n", start - 1) + 1;
    const lineBreak = text.indexOf("\n", end);
    const to = lineBreak === -1 ? text.length : lineBreak;
    const lines = text.slice(from, to).split("\n");
    const allPrefixed = lines.every((line) => line === "" || line.startsWith(prefix));
    const nextBlock = lines
      .map((line) =>
        line === "" ? line : allPrefixed ? line.slice(prefix.length) : prefix + line,
      )
      .join("\n");
    apply(text.slice(0, from) + nextBlock + text.slice(to), from, from + nextBlock.length);
  };

  const heading = (level: number) => {
    const ta = taRef.current;
    if (!ta) return;
    const { selectionStart: start, value: text } = ta;
    const from = text.lastIndexOf("\n", start - 1) + 1;
    const lineEnd = text.indexOf("\n", from) === -1 ? text.length : text.indexOf("\n", from);
    const line = text.slice(from, lineEnd);
    const stripped = line.replace(/^#{1,6}\s+/, "");
    const marker = "#".repeat(level) + " ";
    const nextLine = line.startsWith(marker) ? stripped : marker + stripped;
    apply(text.slice(0, from) + nextLine + text.slice(lineEnd), from + nextLine.length);
  };

  const insertBlock = (block: string) => {
    const ta = taRef.current;
    if (!ta) return;
    const { selectionStart: start, value: text } = ta;
    const needsNewline = start > 0 && text[start - 1] !== "\n";
    const inserted = (needsNewline ? "\n" : "") + block + "\n";
    apply(text.slice(0, start) + inserted + text.slice(start), start + inserted.length);
  };

  const uploadFiles = async (files: File[]) => {
    if (!onUploadImage) return;
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      const url = await onUploadImage(file);
      if (url) insertBlock(`![${file.name}](${url})`);
    }
  };

  const pickImage = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => void uploadFiles(Array.from(input.files ?? []));
    input.click();
  };

  const buttons: { icon: typeof Bold; title: string; run: () => void }[] = [
    { icon: Heading1, title: "Heading 1", run: () => heading(1) },
    { icon: Heading2, title: "Heading 2", run: () => heading(2) },
    { icon: Heading3, title: "Heading 3", run: () => heading(3) },
    { icon: Bold, title: "Bold", run: () => wrap("**") },
    { icon: Italic, title: "Italic", run: () => wrap("*") },
    { icon: Strikethrough, title: "Strikethrough", run: () => wrap("~~") },
    { icon: Code, title: "Inline code", run: () => wrap("`", "`", "code") },
    { icon: Link2, title: "Link", run: () => wrap("[", "](url)") },
    { icon: List, title: "Bullet list", run: () => prefixLines("- ") },
    { icon: ListOrdered, title: "Numbered list", run: () => prefixLines("1. ") },
    { icon: ListChecks, title: "Task list", run: () => prefixLines("- [ ] ") },
    { icon: TextQuote, title: "Quote", run: () => prefixLines("> ") },
    { icon: SquareCode, title: "Code block", run: () => insertBlock("```\ncode\n```") },
    { icon: Table, title: "Table", run: () => insertBlock("| a | b |\n| --- | --- |\n| 1 | 2 |") },
    { icon: Minus, title: "Divider", run: () => insertBlock("---") },
    ...(onUploadImage ? [{ icon: Image, title: "Image", run: pickImage }] : []),
  ];

  return (
    <div>
      {/* Toolbar — mirrors the rich TopBar's actions as markdown syntax edits. */}
      <div className="sticky top-0 z-[5] flex flex-wrap items-center gap-0.5 rounded-t-md border-b border-subtle bg-surface px-1.5 py-1">
        {buttons.map(({ icon: Icon, title, run }) => (
          <button
            key={title}
            type="button"
            title={title}
            // onMouseDown+preventDefault keeps the textarea selection/focus intact.
            onMouseDown={(event) => {
              event.preventDefault();
              run();
            }}
            className="cursor-pointer rounded p-1.5 text-fg-secondary hover:bg-elevated hover:text-heading"
          >
            <Icon size={15} aria-hidden />
          </button>
        ))}
      </div>
      <textarea
        ref={taRef}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          // detect on the NEXT frame so selectionStart reflects the edit
          requestAnimationFrame(detectTrigger);
        }}
        onKeyDown={onKeyDown}
        onKeyUp={detectTrigger}
        onClick={detectTrigger}
        onPaste={(event) => {
          const files = Array.from(event.clipboardData?.files ?? []);
          if (files.length && onUploadImage) {
            event.preventDefault();
            void uploadFiles(files);
          }
        }}
        placeholder={placeholder}
        autoFocus={autoFocus}
        rows={Math.max(4, value.split("\n").length)}
        className="w-full resize-y bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed text-fg placeholder:text-fg-faint outline-none"
      />
    </div>
  );
}
