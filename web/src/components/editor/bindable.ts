import { editorViewCtx, parserCtx, prosePluginsCtx, type Editor } from "@milkdown/kit/core";
import { Plugin, type Plugin as ProsePlugin } from "@milkdown/kit/prose/state";
import type { BindableEditor } from "@radd/plugin-sdk";

/**
 * The editor as an `EditorBinding` sees it (RADD-1397): the view, the markdown it opened with, a
 * parser into its schema, and a way to run extra ProseMirror plugins.
 *
 * Plugins are added the way Milkdown adds its own late ones: into `prosePluginsCtx` as well as the
 * live state, so a later reconfigure from that list (a plugin registered after create) keeps them.
 * The editor knows nothing about what the plugins do — the binding builds them from the shared
 * `prosemirror-*` modules, which are this editor's own instances.
 */
export function bindableEditor(editor: Editor, markdown: string): BindableEditor {
  const view = editor.action((ctx) => ctx.get(editorViewCtx));
  const reconfigure = (next: (plugins: ProsePlugin[]) => ProsePlugin[]) =>
    editor.action((ctx) => {
      ctx.update(prosePluginsCtx, next);
      view.updateState(view.state.reconfigure({ plugins: ctx.get(prosePluginsCtx) }));
    });
  return {
    view,
    markdown,
    parse: (text) => editor.action((ctx) => ctx.get(parserCtx)(text)),
    addPlugins: (plugins) => {
      const added = [...plugins];
      reconfigure((current) => [...current, ...added]);
      let removed = false;
      return () => {
        if (removed) return;
        removed = true;
        reconfigure((current) => current.filter((plugin) => !added.includes(plugin)));
      };
    },
  };
}

/**
 * Reports every document change — including the ones a binding applies. Milkdown's listener skips
 * a transaction flagged `addToHistory: false`, which is exactly how a binding applies a change
 * that arrived from elsewhere, so without this the editor's `onChange` (and whatever saves from
 * it) would stop at this client's own typing.
 */
export function documentChangePlugin(onChange: () => void): ProsePlugin {
  return new Plugin({
    view: () => ({
      update: (view, previous) => {
        if (!view.state.doc.eq(previous.doc)) onChange();
      },
    }),
  });
}
