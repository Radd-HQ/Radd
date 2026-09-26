import { useEffect, useRef } from "react";
import { $view } from "@milkdown/kit/utils";
import { makeEditor } from "./create-editor";
import { codeBlockSchema, imageSchema } from "@milkdown/kit/preset/commonmark";
import { listItemBlockComponent } from "@milkdown/kit/component/list-item-block";
import { ProsemirrorAdapterProvider, useNodeViewFactory } from "@prosemirror-adapter/react";
import type { RichViewerProps, TaskToggle } from "@radd/plugin-sdk";
import { jiraToMarkdown } from "../../lib/jira-markup";
import { useOpenIssueRef } from "../../lib/hooks";
import { mentionChipsPlugin } from "./chips";
import { CodeBlockView } from "./CodeBlockView";
import { ImageNodeView } from "./ImageNodeView";
import "./editor.css";
import "./rich-editor.css";

type ViewerProps = Omit<RichViewerProps, "eager">;

/**
 * Read mode: the SAME engine as `RichEditor`, not editable, so read and edit look identical; chips and
 * link routing come from the shared `mentionChipsPlugin`. The editor creates ASYNCHRONOUSLY, so
 * whatever reads the rendered output (heading anchors, printing) waits for `onReady`. Without a
 * `taskScope`, task indexes count across this viewer (which then carries `data-task-scope`).
 */
export function RichViewer(props: ViewerProps) {
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
  onToggleTask,
  taskScope,
}: ViewerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const taskScopeStable = useRef(taskScope);
  taskScopeStable.current = taskScope;
  const onToggleStable = useRef(onToggleTask);
  onToggleStable.current = onToggleTask;
  // Legacy Jira markup is converted for display; its stored text has no GFM
  // markers to flip, so it is never toggleable.
  const toggleable = Boolean(onToggleTask) && jiraToMarkdown(text) === text;
  const onReadyStable = useRef(onReady);
  onReadyStable.current = onReady;
  // An issue chip opens the PEEK over what you are reading (same helper as the issue view).
  const openRef = useOpenIssueRef();
  const openRefStable = useRef(openRef);
  openRefStable.current = openRef;
  const nodeViewFactory = useNodeViewFactory();

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
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

  useTaskToggle(rootRef, toggleable, onToggleStable, text, taskScopeStable);

  return (
    <div
      ref={rootRef}
      className={"radd-rich-editor radd-rich-viewer " + className}
      data-task-toggle={toggleable ? "" : undefined}
      data-task-scope={taskScope ? undefined : ""}
    />
  );
}

const TASK_LABEL = ".label.checked, .label.unchecked";

/**
 * RADD-1296: tick a box in READ mode. Milkdown's list component ignores a
 * click when the view is not editable, so the viewer listens itself (capture
 * phase, ahead of the component's own handler), resolves WHICH box by its
 * position among the task labels — document order, the order the server's
 * rewriter counts in — and hands it to the surface. The labels also become
 * real checkboxes for the keyboard and screen readers while toggleable.
 */
function useTaskToggle(
  rootRef: React.RefObject<HTMLDivElement | null>,
  toggleable: boolean,
  onToggle: React.RefObject<((toggle: TaskToggle) => Promise<unknown>) | undefined>,
  text: string,
  taskScope: React.RefObject<(() => HTMLElement | null) | undefined>,
) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root || !toggleable) return;
    // Every box in the scope — minus those of a NESTED scope (an included page
    // inside this one), whose markers live in another document.
    const scopeLabels = () => {
      const scope = taskScope.current?.() ?? root;
      return [...scope.querySelectorAll<HTMLElement>(TASK_LABEL)].filter(
        (label) => label.closest("[data-task-scope]") === scope,
      );
    };
    const labels = () => [...root.querySelectorAll<HTMLElement>(TASK_LABEL)];
    const fire = (label: HTMLElement) => {
      if (root.hasAttribute("data-task-busy")) return;
      const index = scopeLabels().indexOf(label);
      const send = onToggle.current;
      if (index < 0 || !send) return;
      root.setAttribute("data-task-busy", "");
      void send({ index, checked: !label.classList.contains("checked") }).finally(() =>
        root.removeAttribute("data-task-busy"),
      );
    };
    const onPointerDown = (event: PointerEvent) => {
      const label = (event.target as HTMLElement | null)?.closest<HTMLElement>(TASK_LABEL);
      if (!label || !root.contains(label)) return;
      event.preventDefault();
      event.stopPropagation();
      fire(label);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const label = (event.target as HTMLElement | null)?.closest<HTMLElement>(TASK_LABEL);
      if (!label || (event.key !== " " && event.key !== "Enter")) return;
      event.preventDefault();
      fire(label);
    };
    // The editor renders asynchronously and re-renders labels on update, so
    // the ARIA pass watches the subtree rather than running once.
    const mark = () => {
      for (const label of labels()) {
        const checked = label.classList.contains("checked") ? "true" : "false";
        if (label.getAttribute("aria-checked") !== checked) label.setAttribute("aria-checked", checked);
        if (label.getAttribute("role") !== "checkbox") label.setAttribute("role", "checkbox");
        if (label.tabIndex !== 0) label.tabIndex = 0;
      }
    };
    const observer = new MutationObserver(mark);
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
    mark();
    root.addEventListener("pointerdown", onPointerDown, true);
    root.addEventListener("keydown", onKeyDown);
    return () => {
      observer.disconnect();
      root.removeEventListener("pointerdown", onPointerDown, true);
      root.removeEventListener("keydown", onKeyDown);
    };
  }, [rootRef, toggleable, onToggle, text, taskScope]);
}
