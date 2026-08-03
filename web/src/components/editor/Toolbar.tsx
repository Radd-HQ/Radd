import {
  Bold,
  Code,
  Image as ImageIcon,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  Quote,
  SquareCode,
  Strikethrough,
  Table as TableIcon,
  type LucideIcon,
} from "lucide-react";
import { Select } from "../Select";
import type { ToolbarSnapshot } from "./toolbar-state";

/**
 * The editor's fixed toolbar — ours (RADD-749).
 *
 * We were already fighting the one it replaces: retinted 18px/8:1 with an accent
 * pill because it shipped no `.active` styling at all, the AI button injected
 * through a `buildTopBar` builder, and every item acting on `mousedown` rather
 * than `click` — which silently passed a render proof against broken code and
 * would break any keyboard-driven affordance.
 *
 * So: real `<button>`s in the house kit, acting on CLICK, reachable by Tab, with
 * `aria-pressed` saying what is on. The commands are Milkdown's own, dispatched
 * by the caller — this component renders and reports, and knows nothing about
 * the editor beyond the snapshot it is handed.
 */

/** What a button does, in the caller's vocabulary. */
export const ToolbarAction = {
  bold: "bold",
  italic: "italic",
  strike: "strike",
  inlineCode: "inlineCode",
  link: "link",
  bulletList: "bulletList",
  orderedList: "orderedList",
  quote: "quote",
  codeBlock: "codeBlock",
  image: "image",
  table: "table",
} as const;
export type ToolbarActionValue = (typeof ToolbarAction)[keyof typeof ToolbarAction];

/** Paragraph and H1–H3. H4–H6 add noise, not structure, at issue/pages scale. */
const BLOCK_OPTIONS = [
  { value: "0", label: "Paragraph" },
  { value: "1", label: "Heading 1" },
  { value: "2", label: "Heading 2" },
  { value: "3", label: "Heading 3" },
];

interface Item {
  action: ToolbarActionValue;
  icon: LucideIcon;
  title: string;
  /** Reads the snapshot — a mark name, or a predicate for block-ish states. */
  active?: (snapshot: ToolbarSnapshot) => boolean;
}

const MARK_ITEMS: Item[] = [
  { action: ToolbarAction.bold, icon: Bold, title: "Bold", active: (s) => s.marks.includes("strong") },
  { action: ToolbarAction.italic, icon: Italic, title: "Italic", active: (s) => s.marks.includes("emphasis") },
  { action: ToolbarAction.strike, icon: Strikethrough, title: "Strikethrough", active: (s) => s.marks.includes("strike_through") },
  { action: ToolbarAction.inlineCode, icon: Code, title: "Inline code", active: (s) => s.marks.includes("inlineCode") },
  { action: ToolbarAction.link, icon: LinkIcon, title: "Link", active: (s) => s.marks.includes("link") },
];

const BLOCK_ITEMS: Item[] = [
  { action: ToolbarAction.bulletList, icon: List, title: "Bulleted list", active: (s) => s.list === "bullet_list" },
  { action: ToolbarAction.orderedList, icon: ListOrdered, title: "Numbered list", active: (s) => s.list === "ordered_list" },
  { action: ToolbarAction.quote, icon: Quote, title: "Quote", active: (s) => s.inBlockquote },
  { action: ToolbarAction.codeBlock, icon: SquareCode, title: "Code block", active: (s) => s.block === "code_block" },
];

export function EditorToolbar({
  snapshot,
  onAction,
  onHeading,
  images,
  tables,
  extra,
}: {
  snapshot: ToolbarSnapshot;
  onAction: (action: ToolbarActionValue, anchor: DOMRect) => void;
  /** 0 = paragraph, 1–3 = heading level. */
  onHeading: (level: number) => void;
  /** Image insertion is only offered where an upload handler exists. */
  images: boolean;
  tables: boolean;
  /** AI and extension buttons, which are per-surface. */
  extra?: React.ReactNode;
}) {
  const insertItems: Item[] = [
    ...(images ? [{ action: ToolbarAction.image, icon: ImageIcon, title: "Image" }] : []),
    ...(tables ? [{ action: ToolbarAction.table, icon: TableIcon, title: "Table" }] : []),
  ];

  return (
    <div
      role="toolbar"
      aria-label="Formatting"
      // Sticky so it stays reachable in a long document, and a solid background
      // so content scrolling under it stays legible.
      className="radd-editor-toolbar sticky top-0 z-[5] flex flex-wrap items-center gap-0.5 rounded-t-md border-b border-subtle bg-surface px-1.5 py-1"
    >
      <Select
        size="sm"
        aria-label="Text style"
        className="w-32"
        value={String(snapshot.block === "heading" ? snapshot.level : 0)}
        onChange={(value) => onHeading(Number(value))}
        options={BLOCK_OPTIONS}
      />
      <Divider />
      {MARK_ITEMS.map((item) => (
        <ToolbarButton key={item.action} item={item} snapshot={snapshot} onAction={onAction} />
      ))}
      <Divider />
      {BLOCK_ITEMS.map((item) => (
        <ToolbarButton key={item.action} item={item} snapshot={snapshot} onAction={onAction} />
      ))}
      {insertItems.length > 0 && <Divider />}
      {insertItems.map((item) => (
        <ToolbarButton key={item.action} item={item} snapshot={snapshot} onAction={onAction} />
      ))}
      {extra}
    </div>
  );
}

const Divider = () => <span className="mx-0.5 h-4 w-px shrink-0 bg-[var(--color-border-subtle)]" />;

function ToolbarButton({
  item,
  snapshot,
  onAction,
}: {
  item: Item;
  snapshot: ToolbarSnapshot;
  onAction: (action: ToolbarActionValue, anchor: DOMRect) => void;
}) {
  const active = item.active?.(snapshot) ?? false;
  const Icon = item.icon;
  return (
    <button
      type="button"
      title={item.title}
      aria-label={item.title}
      aria-pressed={item.active ? active : undefined}
      data-toolbar-action={item.action}
      // onMouseDown preventDefault, NOT onMouseDown-to-act: the click has to stay
      // a click so it is keyboard-reachable, but the editor must keep its
      // selection — without this, focusing the button collapses the selection and
      // "bold the selected words" bolds nothing.
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => onAction(item.action, event.currentTarget.getBoundingClientRect())}
      className={
        "inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors " +
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus " +
        (active
          ? "bg-[color-mix(in_srgb,var(--accent-fill)_24%,transparent)] text-accent-text-strong"
          : "text-fg-secondary hover:bg-elevated hover:text-heading")
      }
    >
      <Icon size={16} aria-hidden />
    </button>
  );
}
