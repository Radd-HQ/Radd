import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNodeViewContext } from "@prosemirror-adapter/react";
import { Pencil, Trash2 } from "lucide-react";
import { CONFIG_ON_INSERT, configOnInsertKey } from "./extension-node";
import {
  ExtensionError,
  UnknownExtension,
  lookupPageExtension,
  parseExtensionParams,
} from "../../lib/page-extensions";
import { ExtensionConfig } from "./ExtensionConfig";
import "../pages/extensions"; // side-effect: registers the first-party extensions

/**
 * An extension block, rendered LIVE inside the editor (RADD-746).
 *
 * The same registry, the same `render`, the same failure cards as read mode —
 * `PageBody` and this view disagreeing about what a block looks like would
 * defeat the point of showing it while editing. What edit mode adds is the
 * chrome: a hover row to reconfigure or remove the block, because the
 * alternative was editing raw JSON inside a fence.
 *
 * `data-extension` mirrors the read-mode attribute deliberately: it is what
 * lets a headless check assert a fence became an ELEMENT rather than staying
 * source, and the assertion should read the same on both surfaces.
 */
export function ExtensionNodeView() {
  const { node, view, getPos, setAttrs, selected, decorations } = useNodeViewContext();
  const [editing, setEditing] = useState(false);
  // Inserted from the menu a moment ago: open the form, so "what can this take?"
  // is answered at the point of asking rather than by guessing at JSON (RADD-747).
  const requestedOnInsert = decorations.some(
    (decoration) => (decoration.spec as Record<string, unknown>)[CONFIG_ON_INSERT] === true,
  );
  useEffect(() => {
    if (!requestedOnInsert) return;
    setEditing(true);
    // Clear the request in its own transaction, so the decoration goes and this
    // cannot re-fire. Deferred: dispatching during ProseMirror's own update
    // would re-enter the view it is in the middle of building.
    const timer = setTimeout(() => {
      view.dispatch(view.state.tr.setMeta(configOnInsertKey, null));
    }, 0);
    return () => clearTimeout(timer);
  }, [requestedOnInsert, view]);
  const name = String(node.attrs.name ?? "");
  const body = String(node.attrs.body ?? "");
  const extension = lookupPageExtension(name);
  const parsed = parseExtensionParams(body);

  const remove = () => {
    const pos = getPos();
    if (pos === undefined) return;
    view.dispatch(view.state.tr.delete(pos, pos + node.nodeSize));
    view.focus();
  };

  return (
    <div
      data-extension={name}
      data-extension-editable
      contentEditable={false}
      className={
        "group relative my-1 rounded-lg " +
        (selected ? "outline-2 outline-offset-2 outline-focus" : "")
      }
    >
      {/* Hover chrome, INSIDE the wrapper's box on purpose.

          It sat at `-top-3` first, which looked better and did not work: an
          absolutely-positioned child above its parent's box is outside the
          area that triggers `group-hover`, so moving the pointer from the block
          toward the button dismissed the button on the way. The proof caught it
          by hit-testing the click point — what was painted there was the H1
          above, not the button. Keep the chrome within the group it belongs to.

          The card's own header is left-aligned, so the top-right corner is
          empty and nothing is covered. */}
      <div className="radd-extension-chrome pointer-events-none absolute top-1.5 right-1.5 z-10 flex gap-1 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100">
        <button
          type="button"
          onClick={() => setEditing(true)}
          title={`Configure radd:${name}`}
          aria-label={`Configure radd:${name}`}
          className="cursor-pointer text-fg-secondary shadow-lift hover:text-heading focus-visible:outline-2 focus-visible:outline-focus"
        >
          <Pencil size={13} />
        </button>
        <button
          type="button"
          onClick={remove}
          title={`Remove radd:${name}`}
          aria-label={`Remove radd:${name}`}
          className="cursor-pointer text-fg-secondary shadow-lift hover:text-red-400 focus-visible:outline-2 focus-visible:outline-focus"
        >
          <Trash2 size={13} />
        </button>
      </div>
      {!extension ? (
        <UnknownExtension name={name} />
      ) : !parsed.ok ? (
        <ExtensionError name={name} error={parsed.error} />
      ) : (
        extension.render(parsed.params)
      )}
      {editing &&
        createPortal(
          <ExtensionConfig
            name={name}
            body={body}
            onClose={() => setEditing(false)}
            onSave={(next) => {
              setAttrs({ body: next });
              setEditing(false);
            }}
          />,
          document.body,
        )}
    </div>
  );
}
