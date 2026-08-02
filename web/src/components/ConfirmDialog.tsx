import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";

export interface ConfirmOptions {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red confirm button — for destructive actions. */
  danger?: boolean;
  /** Hide the cancel button (alert()-style informational notices). */
  hideCancel?: boolean;
}

interface ConfirmDialogProps extends ConfirmOptions {
  onConfirm: () => void;
  onCancel: () => void;
}

/** Modal yes/no dialog — the themed replacement for window.confirm/alert. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  hideCancel = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  // Modal auto-focuses its first control (the X); move focus to the safe
  // default instead — cancel for destructive prompts, confirm otherwise.
  const footerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const buttons = footerRef.current?.querySelectorAll("button");
    if (!buttons || buttons.length === 0) return;
    (danger && !hideCancel ? buttons[0] : buttons[buttons.length - 1]).focus();
  }, [danger, hideCancel]);

  return (
    <Modal title={title} onClose={onCancel}>
      <div className="text-[13px] text-fg-secondary">{message}</div>
      <div ref={footerRef} className="mt-4 flex justify-end gap-2">
        {!hideCancel && (
          <Button variant="ghost" onClick={onCancel}>
            {cancelLabel}
          </Button>
        )}
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

/**
 * Promise-based confirm, mirroring `window.confirm`: render the returned
 * `dialog` element, then `if (await confirm({ title, message, danger: true })) …`.
 * Resolves true on confirm, false on cancel/Escape/overlay-click.
 */
export function useConfirm(): [ReactNode, (options: ConfirmOptions) => Promise<boolean>] {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolverRef = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback((next: ConfirmOptions) => {
    // A second confirm() before the first settles would orphan the first
    // promise — its awaiter would hang forever. Resolve it false (the
    // safe answer) before taking over the dialog.
    resolverRef.current?.(false);
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
    });
  }, []);

  const settle = (ok: boolean) => {
    resolverRef.current?.(ok);
    resolverRef.current = null;
    setOptions(null);
  };

  const dialog = options ? (
    <ConfirmDialog {...options} onConfirm={() => settle(true)} onCancel={() => settle(false)} />
  ) : null;
  return [dialog, confirm];
}
