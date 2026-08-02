import { $prose } from "@milkdown/kit/utils";
import { Plugin, PluginKey } from "@milkdown/kit/prose/state";
import type { EditorView } from "@milkdown/kit/prose/view";

/** An active `@`/`#`/`/` trigger in the editor: what was typed and where.
 * `@`/`#` = mentions (anywhere after whitespace); `/` = quick actions (block start). */
export interface MentionQuery {
  type: "@" | "#" | "/";
  query: string;
  from: number; // doc position of the trigger char
  to: number; // caret position
  coords: { left: number; bottom: number };
}

/** Bridge between the ProseMirror plugin and the React popup. React reassigns
 * `onQuery`/`keydown` each render (so they see current state); the plugin calls them. */
export interface MentionStore {
  view: EditorView | null;
  onQuery: (query: MentionQuery | null) => void;
  keydown: (action: "up" | "down" | "enter" | "escape") => boolean;
}

// A trigger fires only at line start or after whitespace (so emails/snake_case don't).
// Shared with the plain-markdown editor (PlainEditor) — same triggers in both modes.
export const TRIGGER_RE = /(?:^|\s)([@#])([\p{L}\p{N}._-]*)$/u;
// `/` quick actions: only at LINE START (like GitLab/Jira quick actions), so typing
// paths ("/usr/bin") mid-sentence never triggers. Spaces allowed — queries like
// "/assign hussein" filter by every token. A second "/" kills the match.
export const SLASH_RE = /^\/([\p{L}\p{N}._ -]*)$/u;
export const KEY_ACTIONS: Record<string, "up" | "down" | "enter" | "escape"> = {
  ArrowUp: "up",
  ArrowDown: "down",
  Enter: "enter",
  Tab: "enter",
  Escape: "escape",
};

/** Milkdown plugin: detect `@`/`#` typing, report it to React, and route the nav
 * keys to the popup while it's open. Added via `crepe.editor.use(...)`. */
export function mentionProsePlugin(store: MentionStore) {
  return $prose(
    () =>
      new Plugin({
        key: new PluginKey("radd-mention"),
        view: () => ({
          update(view) {
            store.view = view;
            const sel = view.state.selection;
            if (!sel.empty || !sel.$from.parent.isTextblock) return store.onQuery(null);
            const $from = sel.$from;
            const before = $from.parent.textBetween(
              Math.max(0, $from.parentOffset - 60),
              $from.parentOffset,
              undefined,
              "￼",
            );
            // SLASH_RE anchors ^ to the window start — only valid when the window IS
            // the block start (offset ≤ 60), else a mid-text "/" could false-match.
            const slash = $from.parentOffset <= 60 ? SLASH_RE.exec(before) : null;
            const match = slash ?? TRIGGER_RE.exec(before);
            if (!match) return store.onQuery(null);
            const type = slash ? "/" : (match[1] as "@" | "#");
            const query = slash ? match[1] : match[2];
            const to = sel.from;
            const from = to - (query.length + 1);
            const coords = view.coordsAtPos(to);
            store.onQuery({
              type,
              query,
              from,
              to,
              coords: { left: coords.left, bottom: coords.bottom },
            });
          },
        }),
        props: {
          handleKeyDown(_view, event) {
            const action = KEY_ACTIONS[event.key];
            return action ? store.keydown(action) : false;
          },
        },
      }),
  );
}

/** Replace the typed `@query`/`#query` with the picked reference. `@` → `@[Name](uuid)`
 * and `#` → `#[KEY](KEY)` in the serialized markdown (text trigger + a link mark) — the
 * tokens the reader turns into a mention chip / issue link. */
export function insertMention(
  view: EditorView,
  q: MentionQuery,
  label: string,
  href: string,
): void {
  const { schema, tr } = view.state;
  const linkMark = schema.marks.link.create({ href });
  const content = [schema.text(q.type), schema.text(label, [linkMark]), schema.text(" ")];
  view.dispatch(tr.replaceWith(q.from, q.to, content).scrollIntoView());
  view.focus();
}

/** Delete the typed `/query` text once a quick action is picked — the action mutates
 * the issue; the trigger text was never content. */
export function removeTrigger(view: EditorView, q: MentionQuery): void {
  view.dispatch(view.state.tr.delete(q.from, q.to));
  view.focus();
}
