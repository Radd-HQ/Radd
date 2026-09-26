import { useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles } from "lucide-react";
import { EditorToolbarButton, type EditorToolbarActionProps } from "@radd/plugin-sdk";
import { AiActionPicker } from "./ActionPicker";
import { useEditorAi } from "./gate";
import { aiTransform } from "./transform";

/** The toolbar's AI button (`editor.toolbar.action`): Ask AI's actions without needing a selection —
 *  a run covers the selection, else the whole document. */
export function AiToolbarAction({ editor }: EditorToolbarActionProps) {
  const ai = useEditorAi();
  const [menu, setMenu] = useState<{ left: number; top: number } | null>(null);
  if (!ai) return null;
  return (
    <>
      <EditorToolbarButton
        // `svg.radd-ai-toolbar-icon` is the handle the render proofs have always looked for.
        icon={<Sparkles size={16} className="radd-ai-toolbar-icon" aria-hidden />}
        title="AI"
        disabled={editor.busy}
        onPick={(rect) => setMenu({ left: Math.min(rect.left, window.innerWidth - 300), top: rect.bottom + 4 })}
      />
      {menu &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[59]" onMouseDown={() => setMenu(null)} />
            <div
              style={{ position: "fixed", left: menu.left, top: menu.top }}
              className="z-[60] w-72 rounded-md border border-strong bg-surface p-1.5 shadow-pop animate-menu-in"
              data-ai-toolbar-menu
            >
              <AiActionPicker
                actions={ai.actions}
                onPick={(run) => {
                  setMenu(null);
                  editor.transform(aiTransform(run));
                }}
                autoFocus
              />
            </div>
          </>,
          document.body,
        )}
    </>
  );
}
