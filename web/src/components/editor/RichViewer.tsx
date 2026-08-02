import { useEffect, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Crepe, CrepeFeature } from "@milkdown/crepe";
import { jiraToMarkdown } from "../../lib/jira-markup";
import { RoutePath } from "../../lib/constants";
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
export function RichViewer({ text, className = "" }: { text: string; className?: string }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const crepe = new Crepe({
      root,
      // Backwards-compat: old Jira wiki markup renders as markdown (no-op on native).
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
        openIssue: (key) =>
          void navigateRef.current({ to: RoutePath.issue, params: { itemKey: key } }),
      }),
    );
    crepe.setReadonly(true);
    const created = crepe.create();
    return () => {
      // Destroy only after create resolves, so an unmount mid-init can't race.
      void created.then(() => crepe.destroy());
    };
    // Recreate when the content changes (comment edited, page saved).
  }, [text]);

  return <div ref={rootRef} className={"radd-rich-editor radd-rich-viewer " + className} />;
}
