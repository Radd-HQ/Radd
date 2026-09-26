import type { ComponentType, ReactNode } from "react";
import type { TextAnchor } from "./anchoring";
import type { EditorBinding, EditorTransform } from "./editor-extensions";
import { bridged } from "./bridge";
import { TextArea } from "./primitives";

/** The host's editor, viewer, markdown renderer and reading pane, bridged: Milkdown, ProseMirror and
 *  CodeMirror are too heavy to bundle into a plugin. Additions go through `editor-extensions.ts`. */

/** A reader ticked a checklist box: its index among the task items in document order. */
export interface TaskToggle {
  index: number;
  checked: boolean;
}

/** An open inline comment anchored in the document, so a review can count what it strands. */
export interface InlineAnchorRef {
  id: string;
  anchor: TextAnchor;
}

export interface RichEditorProps {
  /** The seed markdown; the editor is uncontrolled after mount (remount with a `key` to reseed). */
  value: string;
  onChange: (markdown: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  className?: string;
  /** Offer the `radd:*` extension picker in the toolbar (page bodies). */
  extensions?: boolean;
  /** The attachment parent pasted and inserted images are stored on. Omit to disable images. */
  attachTo?: { entityType: string; entityId: string };
  /** A transform to run over the whole document once the editor is ready — a read action's
   *  hand-off to edit mode (`ReadActionProps.transform`). */
  initialTransform?: EditorTransform;
  inlineAnchors?: InlineAnchorRef[];
  /** A review ended with those passages gone and the person chose to resolve their comments. */
  onDetachedComments?: (ids: string[]) => void;
  /** Bind the document to a copy that lives elsewhere (`EditorBinding`); `value` is what the
   *  binding may seed it from. Key the editor by `binding.key`. */
  binding?: EditorBinding;
}

export interface RichViewerProps {
  text: string;
  className?: string;
  /** Mount at once instead of when scrolled near — for surfaces that read the rendered output. */
  eager?: boolean;
  /** Fires once the rendered document is in the DOM. */
  onReady?: () => void;
  /** Present only when the reader may write this text. */
  onToggleTask?: (toggle: TaskToggle) => Promise<unknown>;
  /** The element task indexes count across, when this viewer is one segment of a document. */
  taskScope?: () => HTMLElement | null;
}

export interface MarkdownProps {
  text: string;
}

/** A reading surface with room for a panel beside its text (`useReadingPane`). */
export interface ReadingPaneProps {
  children: ReactNode;
}

/** A button in the editor toolbar, drawn like the host's own. */
export interface EditorToolbarButtonProps {
  icon: ReactNode;
  /** Its accessible name and tooltip. */
  title: string;
  /** Clicked: the button's rect, to anchor a popover under it. The editor keeps its selection. */
  onPick: (anchor: DOMRect) => void;
  disabled?: boolean;
}

/** What the host provides for documents. */
export interface DocumentHost {
  RichEditor?: ComponentType<RichEditorProps>;
  RichViewer?: ComponentType<RichViewerProps>;
  Markdown?: ComponentType<MarkdownProps>;
  ReadingPane?: ComponentType<ReadingPaneProps>;
  EditorToolbarButton?: ComponentType<EditorToolbarButtonProps>;
}

const plain = "whitespace-pre-wrap text-[13px] leading-relaxed text-fg";

/** The host's rich markdown editor, else a plain text area. */
export const RichEditor = bridged("RichEditor", (props) => (
  <TextArea aria-label={props.placeholder ?? "Text"} placeholder={props.placeholder}
    defaultValue={props.value} onChange={(event) => props.onChange(event.target.value)} />
));

/** The host's rendered-markdown viewer, else the raw text. */
export const RichViewer = bridged("RichViewer", (props) => <div className={plain}>{props.text}</div>);

/** The host's read-mode markdown renderer (mentions, issue chips, `radd:*` blocks), else raw text. */
export const Markdown = bridged("Markdown", (props) => <div className={plain}>{props.text}</div>);

/** Room for a panel beside the content (`useReadingPane`); without a host, just the content —
 *  answers then open where they were asked for. */
export const ReadingPane = bridged("ReadingPane", (props) => <>{props.children}</>);

/** A toolbar button for an `editor.toolbar.action` contribution. */
export const EditorToolbarButton = bridged("EditorToolbarButton", (props) => (
  <button type="button" title={props.title} aria-label={props.title} disabled={props.disabled}
    onMouseDown={(event) => event.preventDefault()}
    onClick={(event) => props.onPick(event.currentTarget.getBoundingClientRect())}>
    {props.icon}
  </button>
));
