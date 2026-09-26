import type { EditorToolbarButtonProps } from "@radd/plugin-sdk";

/**
 * A toolbar button that opens a popover rather than running a command — the host's own (extensions)
 * and every `editor.toolbar.action` contribution's, through the SDK's `EditorToolbarButton`. The icon
 * carries the class its proofs look for (`svg.radd-extension-toolbar-icon` here).
 */
export function ToolbarExtraButton({ icon, title, onPick, disabled = false }: EditorToolbarButtonProps) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      // A run or review already owns the editor — a second one is refused downstream anyway, and
      // a button that only ever earns a toast is worse than one that says it is unavailable.
      disabled={disabled}
      // Keep the editor's selection: a transform applies to it.
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => onPick(event.currentTarget.getBoundingClientRect())}
      className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-fg-secondary transition-colors hover:bg-elevated hover:text-heading focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus disabled:pointer-events-none disabled:opacity-40"
    >
      {icon}
    </button>
  );
}
