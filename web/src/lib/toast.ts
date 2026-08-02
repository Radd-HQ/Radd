/**
 * Minimal global toast store (no context needed — the api client pushes from
 * outside React). Subscribed via `useSyncExternalStore` in <Toaster />.
 * Sole producer today: the 403 handler in api.ts (spec 04 Phase 3).
 */

export const ToastKind = {
  error: "error",
  success: "success",
} as const;
export type ToastKindValue = (typeof ToastKind)[keyof typeof ToastKind];

export interface Toast {
  id: number;
  kind: ToastKindValue;
  message: string;
}

/** How long a toast stays on screen. */
export const TOAST_TTL_MS = 6000;

/** Shown for a 403 whose body carries no usable message. */
export const FORBIDDEN_FALLBACK_MESSAGE = "You don't have permission to do that.";

let nextId = 1;
let toasts: readonly Toast[] = [];
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function pushToast(message: string, kind: ToastKindValue = ToastKind.error) {
  // Parallel queries hitting the same 403 shouldn't stack duplicate toasts.
  if (toasts.some((toast) => toast.message === message && toast.kind === kind)) return;
  const toast: Toast = { id: nextId++, kind, message };
  toasts = [...toasts, toast];
  emit();
  setTimeout(() => dismissToast(toast.id), TOAST_TTL_MS);
}

export function dismissToast(id: number) {
  if (!toasts.some((toast) => toast.id === id)) return;
  toasts = toasts.filter((toast) => toast.id !== id);
  emit();
}

export function subscribeToasts(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getToasts(): readonly Toast[] {
  return toasts;
}
