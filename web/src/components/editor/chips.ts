import { $prose } from "@milkdown/kit/utils";
import { Plugin, PluginKey } from "@milkdown/kit/prose/state";
import { Decoration, DecorationSet } from "@milkdown/kit/prose/view";
import type { EditorState } from "@milkdown/kit/prose/state";

/** The app's two inline tokens, as they exist in the ProseMirror doc: a plain
 * trigger char (`@`/`#`) followed by a link-marked text — `@[Name](uuid)` /
 * `#[TD-123](TD-123)` in the serialized markdown. */
const UUID_RE = /^[0-9a-fA-F-]{36}$/;
const ISSUE_KEY_RE = /^[A-Za-z][A-Za-z0-9]{0,9}-\d+$/;
const EXTERNAL_RE = /^(?:https?:|mailto:)/i;

export interface ChipOptions {
  /** Open an issue by key (router navigation). */
  openIssue: (key: string) => void;
  /** Read mode: external links open in a new tab; issue chips navigate. In edit
   * mode chip clicks are consumed (no navigation mid-edit, no link tooltip). */
  readonly: boolean;
}

function chipDecorations(state: EditorState): DecorationSet {
  const decorations: Decoration[] = [];
  state.doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return;
    const link = node.marks.find((mark) => mark.type.name === "link");
    if (!link) return;
    const href = String(link.attrs.href ?? "");
    const kind = UUID_RE.test(href)
      ? "mention"
      : ISSUE_KEY_RE.test(href) && node.text === href
        ? "issue"
        : null;
    if (!kind) return;
    // Only chip the app's tokens: the trigger char must sit right before the link.
    const $pos = state.doc.resolve(pos);
    const trigger = kind === "mention" ? "@" : "#";
    const prev =
      $pos.parentOffset > 0
        ? $pos.parent.textBetween($pos.parentOffset - 1, $pos.parentOffset)
        : "";
    if (prev !== trigger) return;
    const cls = kind === "mention" ? "radd-chip radd-chip-mention" : "radd-chip radd-chip-issue";
    decorations.push(Decoration.inline(pos - 1, pos, { class: cls }));
    decorations.push(Decoration.inline(pos, pos + node.nodeSize, { class: cls }));
  });
  return DecorationSet.create(state.doc, decorations);
}

/** Renders `@user` / `#issue` tokens as colored chips (editor AND read-only viewer —
 * same look in both), and routes clicks: issue chips open the issue (read mode),
 * external links open a new tab (read mode), chip clicks never open the link
 * tooltip or navigate the SPA to a raw `TD-123`/uuid href. */
export function mentionChipsPlugin(options: ChipOptions) {
  return $prose(
    () =>
      new Plugin({
        key: new PluginKey("radd-mention-chips"),
        props: {
          decorations: chipDecorations,
          // NOT handleClick: that fires on mouseup, too late to cancel an anchor's
          // native click-navigation (a raw `TD-123`/uuid href resolves relative to
          // the current route). Intercept the real DOM click instead.
          handleDOMEvents: {
            click(_view, event) {
              const anchor = (event.target as HTMLElement | null)?.closest?.("a");
              if (!anchor) return false;
              const href = anchor.getAttribute("href") ?? "";
              if (ISSUE_KEY_RE.test(href)) {
                event.preventDefault();
                if (options.readonly) options.openIssue(href);
                return true;
              }
              if (UUID_RE.test(href)) {
                event.preventDefault();
                return true;
              }
              if (options.readonly && EXTERNAL_RE.test(href)) {
                event.preventDefault();
                window.open(href, "_blank", "noopener,noreferrer");
                return true;
              }
              return false;
            },
          },
        },
      }),
  );
}
