import { useEffect, useRef } from "react";
import { $view } from "@milkdown/kit/utils";
import { makeEditor } from "./create-editor";
import { codeBlockSchema, imageSchema } from "@milkdown/kit/preset/commonmark";
import { listItemBlockComponent } from "@milkdown/kit/component/list-item-block";
import { ProsemirrorAdapterProvider, useNodeViewFactory } from "@prosemirror-adapter/react";
import { jiraToMarkdown } from "../../lib/jira-markup";
import { useOpenIssueRef } from "../../lib/hooks";
import { mentionChipsPlugin } from "./chips";
import { CodeBlockView } from "./CodeBlockView";
import { ImageNodeView } from "./ImageNodeView";
import "./editor.css";
import "./rich-editor.css";

/**
 * Read-mode renderer = the SAME engine as `RichEditor`, not editable — so
 * content looks identical in read and edit (headings,
 * tables, code blocks with copy button, images, chips). No toolbar/menu chrome;
 * `@`/`#` chips + link routing come from the shared `mentionChipsPlugin`.
 */
export function RichViewer(props: {
  text: string;
  className?: string;
  onReady?: () => void;
}) {
  return (
    <ProsemirrorAdapterProvider>
      <RichViewerInner {...props} />
    </ProsemirrorAdapterProvider>
  );
}

function RichViewerInner({
  text,
  className = "",
  onReady,
}: {
  text: string;
  className?: string;
  /** Fires once the editor has actually rendered into the DOM.
   *
   *  The editor creates ASYNCHRONOUSLY, so anything that reads the rendered output —
   *  assigning heading anchors (RADD-710), printing (RADD-736) — sees an empty
   *  container if it runs on mount. This is that signal. */
  onReady?: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const onReadyStable = useRef(onReady);
  onReadyStable.current = onReady;
  // RADD-711: an issue chip opens the PEEK panel over what you are reading
  // rather than navigating away. A wiki page is usually the thing you were
  // reading FOR the references, and the issue view already works this way for
  // its own child rows (RADD-699) — same helper, so one rule covers both.
  const openRef = useOpenIssueRef();
  const openRefStable = useRef(openRef);
  openRefStable.current = openRef;
  const nodeViewFactory = useNodeViewFactory();

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    // Milkdown directly (RADD-755), NOT editable — the same engine as the
    // editor, which is the whole reason read and edit look identical.
    const editor = makeEditor({
      root,
      // Backwards-compat: old Jira pages markup renders as markdown (no-op on native).
      value: jiraToMarkdown(text),
      editable: false,
    });
    editor.use(
      mentionChipsPlugin({
        readonly: true,
        openIssue: (key) => void openRefStable.current(key),
      }),
    );
    // The SAME node view as the editor, non-editable. Two components that merely
    // agree today is how read and edit drift apart.
    editor.use(
      $view(codeBlockSchema.node, () =>
        nodeViewFactory({ component: CodeBlockView, stopEvent: () => true }),
      ),
    );
    // Images too (RADD-751): the width lives in the URL, so read mode has to
    // apply it or a resized image would be resized only while editing.
    editor.use(
      $view(imageSchema.node, () => nodeViewFactory({ component: ImageNodeView })),
    );
    // Read mode renders lists through the same component as the editor, or the
    // two disagree about what a list looks like (RADD-754).
    editor.use(listItemBlockComponent);
        let live = true;
    const created = editor.create().then(() => {
      // `live` guards the unmount race: create resolving after teardown must not
      // announce a viewer that is no longer on the page.
      if (live) onReadyStable.current?.();
    });
    return () => {
      live = false;
      // Destroy only after create resolves, so an unmount mid-init can't race.
      void created.then(() => editor.destroy());
    };
    // Recreate when the content changes (comment edited, page saved).
  }, [text]);

  return <div ref={rootRef} className={"radd-rich-editor radd-rich-viewer " + className} />;
}
