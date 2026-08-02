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
/**
 * An issue addressed by URL rather than by the `#KEY` token — `/issues/TD-1`,
 * or an absolute link to THIS instance (RADD-711 follow-up). Content written
 * outside the editor arrives this way: the generated release-notes pages link
 * `[RADD-704](https://project.radd-hq.com/issues/RADD-704)`, and before this
 * those matched EXTERNAL_RE and opened a NEW TAB — the opposite of peeking.
 * Other hosts are left alone; only this origin's issue paths are claimed.
 */
const ISSUE_URL_RE = /^(?:https?:\/\/[^/]+)?\/issues\/([A-Za-z][A-Za-z0-9]{0,9}-\d+)(?:[?#].*)?$/;

/** The issue key a href addresses, or null. Covers both forms. */
export function issueKeyOf(href: string, origin = ""): string | null {
  if (ISSUE_KEY_RE.test(href)) return href;
  const match = ISSUE_URL_RE.exec(href);
  if (!match) return null;
  // An absolute URL must point at THIS instance; a link to someone else's
  // tracker is an external link and must keep behaving like one.
  if (/^https?:/i.test(href) && origin && !href.startsWith(origin)) return null;
  return match[1];
}

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
    const urlKey = issueKeyOf(href);
    const kind = UUID_RE.test(href)
      ? "mention"
      : ISSUE_KEY_RE.test(href) && node.text === href
        ? "issue"
        : urlKey && node.text === urlKey
          ? "issue-url"
          : null;
    if (!kind) return;
    const cls = kind === "mention" ? "radd-chip radd-chip-mention" : "radd-chip radd-chip-issue";
    // An issue addressed by URL carries no `#` trigger — it was written outside
    // the editor (the generated release notes, a pasted link). Chip the link
    // itself; there is no trigger char to absorb.
    if (kind === "issue-url") {
      decorations.push(Decoration.inline(pos, pos + node.nodeSize, { class: cls }));
      return;
    }
    // The app's own tokens: the trigger char must sit right before the link.
    const $pos = state.doc.resolve(pos);
    const trigger = kind === "mention" ? "@" : "#";
    const prev =
      $pos.parentOffset > 0
        ? $pos.parent.textBetween($pos.parentOffset - 1, $pos.parentOffset)
        : "";
    if (prev !== trigger) return;
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
              const issueKey = issueKeyOf(href, window.location.origin);
              if (issueKey) {
                event.preventDefault();
                if (options.readonly) options.openIssue(issueKey);
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
