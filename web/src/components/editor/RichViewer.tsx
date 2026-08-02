import { useEffect, useRef } from "react";
import { Crepe, CrepeFeature } from "@milkdown/crepe";
import { jiraToMarkdown } from "../../lib/jira-markup";
import { useOpenIssueRef } from "../../lib/hooks";
import { mentionChipsPlugin } from "./chips";
import "@milkdown/crepe/theme/common/style.css";
import "@milkdown/crepe/theme/classic-dark.css";
import "./rich-editor.css";

/**
 * Read-mode renderer = the SAME Milkdown/Crepe engine as `RichEditor`, in
 * `setReadonly` mode — so content looks identical in read and edit (headings,
 * tables, code blocks with copy button, images, chips). No toolbar/menu chrome;
 * `@`/`#` chips + link routing come from the shared `mentionChipsPlugin`.
 */
export function RichViewer({
  text,
  className = "",
  onReady,
}: {
  text: string;
  className?: string;
  /** Fires once the editor has actually rendered into the DOM.
   *
   *  Crepe creates ASYNCHRONOUSLY, so anything that reads the rendered output —
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

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const crepe = new Crepe({
      root,
      // Backwards-compat: old Jira pages markup renders as markdown (no-op on native).
      defaultValue: jiraToMarkdown(text),
      features: {
        [CrepeFeature.TopBar]: false,
        [CrepeFeature.Toolbar]: false,
        [CrepeFeature.BlockEdit]: false,
        [CrepeFeature.Placeholder]: false,
        [CrepeFeature.LinkTooltip]: false,
        [CrepeFeature.Cursor]: false,
        [CrepeFeature.AI]: false,
        [CrepeFeature.Latex]: false,
      },
    });
    crepe.editor.use(
      mentionChipsPlugin({
        readonly: true,
        openIssue: (key) => void openRefStable.current(key),
      }),
    );
    crepe.setReadonly(true);
    let live = true;
    const created = crepe.create().then(() => {
      // `live` guards the unmount race: create resolving after teardown must not
      // announce a viewer that is no longer on the page.
      if (live) onReadyStable.current?.();
    });
    return () => {
      live = false;
      // Destroy only after create resolves, so an unmount mid-init can't race.
      void created.then(() => crepe.destroy());
    };
    // Recreate when the content changes (comment edited, page saved).
  }, [text]);

  return <div ref={rootRef} className={"radd-rich-editor radd-rich-viewer " + className} />;
}
