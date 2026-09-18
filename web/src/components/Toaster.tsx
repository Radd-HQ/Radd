import { useSyncExternalStore } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, CheckCircle2, ShieldAlert, X } from "lucide-react";
import { dismissToast, getToasts, subscribeToasts, ToastKind, type ToastAction } from "../lib/toast";

/** Global toast stack (bottom-right). Fed by lib/toast — e.g. the api 403 handler. */
export function Toaster() {
  const toasts = useSyncExternalStore(subscribeToasts, getToasts);
  const navigate = useNavigate();
  const go = (id: number, action: ToastAction) => {
    dismissToast(id);
    // The store is typed loosely on purpose (it is fed from outside React);
    // the route strings come from RoutePath, so the cast is a formality.
    void navigate({ to: action.to, params: action.params ?? {} } as unknown as Parameters<typeof navigate>[0]);
  };
  if (toasts.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2"
    >
      {toasts.map((toast) => {
        const success = toast.kind === ToastKind.success;
        const Icon = success ? CheckCircle2 : ShieldAlert;
        return (
        <div
          key={toast.id}
          className={
            "flex items-start gap-2 rounded-md border bg-surface px-3 py-2.5 text-[13px] shadow-pop animate-menu-in " +
            (success ? "border-emerald-500/40 text-emerald-300" : "border-red-500/40 text-red-300")
          }
        >
          <Icon size={15} className="mt-px shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{toast.message}</span>
          {toast.action && (
            <button
              type="button"
              onClick={() => go(toast.id, toast.action!)}
              data-toast-action
              className="flex shrink-0 items-center gap-0.5 rounded px-1.5 py-0.5 text-[12px] font-medium underline-offset-2 hover:underline cursor-pointer"
            >
              {toast.action.label}
              <ArrowUpRight size={12} aria-hidden />
            </button>
          )}
          <button
            type="button"
            onClick={() => dismissToast(toast.id)}
            aria-label="Dismiss"
            className="rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <X size={13} />
          </button>
        </div>
        );
      })}
    </div>
  );
}
