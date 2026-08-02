import { lazy, Suspense } from "react";
import type { ComponentProps } from "react";
import type { RichEditor } from "./RichEditor";

// Crepe + ProseMirror is heavy, so it lives in its own chunk that only loads when
// an editor actually mounts — keeps the initial app bundle lean.
const RichEditorImpl = lazy(() =>
  import("./RichEditor").then((module) => ({ default: module.RichEditor })),
);

/** Drop-in for RichEditor that code-splits the editor engine behind Suspense. */
export function LazyRichEditor(props: ComponentProps<typeof RichEditor>) {
  return (
    <Suspense
      fallback={
        <div className="min-h-24 animate-pulse rounded-md border border-strong bg-surface px-3 py-2 text-[13px] text-fg-faint">
          Loading editor…
        </div>
      }
    >
      <RichEditorImpl {...props} />
    </Suspense>
  );
}
